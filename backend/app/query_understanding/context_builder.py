from typing import List
from app.query_understanding.interfaces import IContextBuilder
from app.query_understanding.models import QueryContext, QueryEntities
from app.database.discovery.models import DatabaseMetadata
from app.database.intelligence.models import SchemaIntelligence
from app.database.profiling.models import DatabaseProfile

class DeterministicContextBuilder(IContextBuilder):
    def build(
        self, 
        entities: QueryEntities, 
        metrics: List[str], 
        dimensions: List[str], 
        metadata: DatabaseMetadata, 
        intelligence: SchemaIntelligence, 
        profile: DatabaseProfile
    ) -> QueryContext:
        
        context = QueryContext()
        
        # Pull only relevant tables
        for schema in metadata.schemas:
            for table in schema.tables:
                if table.name in entities.tables:
                    context.tables.append({"name": table.name, "schema": schema.name})
                    
                    # Pull only relevant columns
                    relevant_cols = set(entities.columns + metrics + dimensions)
                    for col in table.columns:
                        if col.name in relevant_cols:
                            context.columns.append({
                                "table": table.name,
                                "name": col.name,
                                "type": col.data_type
                            })
                            
        # Profile statistics for relevant tables/columns (stubbed mapping)
        if profile:
            for t_prof in profile.tables:
                if t_prof.table_name in entities.tables:
                    context.statistics.append({
                        "table": t_prof.table_name,
                        "rows": t_prof.total_rows
                    })
                    
        # Filter relationships from Intelligence graph
        if intelligence:
            pass # Deterministically filter relationships that connect entities.tables
            
        return context
