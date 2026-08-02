import asyncio
import time
from datetime import datetime, timezone
import structlog
from sqlalchemy.engine import Engine
from sqlalchemy import text

from app.config.settings import Settings
from app.database.discovery.models import DatabaseMetadata, TableMetadata, ColumnMetadata
from app.database.profiling.models import DatabaseProfile, TableProfile
from app.database.profiling.sampling import StrategyFactory
from app.database.profiling.factory import ProfilerFactory
from app.database.profiling.utils import generate_schema_hash, generate_profile_id
from app.database.profiling.profilers.numeric import NumericProfiler
from app.database.profiling.profilers.categorical import CategoricalProfiler
from app.database.profiling.profilers.text import TextProfiler
from app.database.profiling.profilers.datetime import DatetimeProfiler

logger = structlog.get_logger(__name__)

class StatisticsCollector:
    def __init__(self, settings: Settings, strategy_factory: StrategyFactory, profiler_factory: ProfilerFactory):
        self.settings = settings
        self.strategy_factory = strategy_factory
        self.profiler_factory = profiler_factory
        
    async def profile_database(self, metadata: DatabaseMetadata, engine: Engine, plugin_name: str, get_sample_query_func) -> DatabaseProfile:
        start_time = time.time()
        
        profile = DatabaseProfile(
            profile_id=generate_profile_id(plugin_name),
            database_name=metadata.name,
            schema_hash=generate_schema_hash(metadata),
            profiling_duration=0.0,
            sample_strategy="mixed",
            generated_at=datetime.now(timezone.utc)
        )
        
        semaphore = asyncio.Semaphore(self.settings.max_concurrent_profiles)
        
        async def profile_table_wrapper(schema_name: str, table: TableMetadata) -> TableProfile:
            async with semaphore:
                return await self.profile_table(engine, schema_name, table, get_sample_query_func)
        
        tasks = []
        for schema in metadata.schemas:
            for table in schema.tables:
                tasks.append(profile_table_wrapper(schema.name, table))
                
        table_profiles = await asyncio.gather(*tasks)
        profile.tables.extend(table_profiles)
        
        profile.profiling_duration = time.time() - start_time
        return profile
        
    async def profile_table(self, engine: Engine, schema_name: str, table: TableMetadata, get_sample_query_func) -> TableProfile:
        logger.info("Profiling table", table=table.name, schema=schema_name)
        
        try:
            with engine.connect() as conn:
                res = conn.execute(text(f"SELECT COUNT(*) FROM {schema_name}.{table.name}")).scalar()
                total_rows = res if res else 0
        except Exception as e:
            logger.error("Failed to count rows", error=str(e), table=table.name)
            total_rows = 0
            
        strategy = self.strategy_factory.get_strategy(total_rows)
        # Pass the ISamplingProvider to the profile_column method
        provider = get_sample_query_func
        
        t_profile = TableProfile(
            table_name=table.name,
            total_rows=total_rows,
            estimated_rows=total_rows,
            total_columns=len(table.columns)
        )
        
        for col in table.columns:
            try:
                c_profile = await self.profile_column(engine, schema_name, table.name, col, provider, strategy)
                t_profile.columns.append(c_profile)
            except Exception as e:
                logger.error("Failed to profile column", error=str(e), column=col.name, table=table.name)
                
        return t_profile

    async def profile_column(self, engine: Engine, schema_name: str, table_name: str, column: ColumnMetadata, provider: callable, strategy: object):
        profiler = self.profiler_factory.get_profiler_for_column(column)
        
        stats = {}
        top_values = None
        sample_size = self.settings.random_sample_size
        
        if isinstance(profiler, NumericProfiler) or isinstance(profiler, DatetimeProfiler):
            select_clause = f"""
                COUNT(*) as total,
                COUNT(DISTINCT {column.name}) as distinct_count,
                SUM(CASE WHEN {column.name} IS NULL THEN 1 ELSE 0 END) as null_count,
                MIN({column.name}) as min_val,
                MAX({column.name}) as max_val,
                AVG(CAST({column.name} AS FLOAT)) as mean_val
            """
            query = text(provider(schema_name, table_name, select_clause, strategy.name, sample_size))
            with engine.connect() as conn:
                result = conn.execute(query).fetchone()
                if result:
                    stats = dict(result._mapping)
                    
        elif isinstance(profiler, TextProfiler):
            select_clause = f"""
                COUNT(*) as total,
                COUNT(DISTINCT {column.name}) as distinct_count,
                SUM(CASE WHEN {column.name} IS NULL THEN 1 ELSE 0 END) as null_count,
                MAX(LENGTH(CAST({column.name} AS VARCHAR))) as max_len,
                MIN(LENGTH(CAST({column.name} AS VARCHAR))) as min_len,
                AVG(LENGTH(CAST({column.name} AS VARCHAR))) as avg_len
            """
            query = text(provider(schema_name, table_name, select_clause, strategy.name, sample_size))
            with engine.connect() as conn:
                result = conn.execute(query).fetchone()
                if result:
                    stats = dict(result._mapping)
                    
        elif isinstance(profiler, CategoricalProfiler):
            basic_select = f"""
                COUNT(*) as total,
                COUNT(DISTINCT {column.name}) as distinct_count,
                SUM(CASE WHEN {column.name} IS NULL THEN 1 ELSE 0 END) as null_count
            """
            query_basic = text(provider(schema_name, table_name, basic_select, strategy.name, sample_size))
            
            top_select = f"{column.name}, COUNT(*) as freq"
            query_top = text(provider(schema_name, table_name, top_select, strategy.name, sample_size, group_by=column.name, order_by="freq DESC", limit=self.settings.max_top_values))
            
            with engine.connect() as conn:
                basic = conn.execute(query_basic).fetchone()
                if basic:
                    stats = dict(basic._mapping)
                top_vals = conn.execute(query_top).fetchall()
                if top_vals:
                    top_values = {}
                    for row in top_vals:
                        val_str = str(row[0]) if row[0] is not None else "NULL"
                        top_values[val_str] = row[1]
                        
        return profiler.process(column, stats, top_values)
