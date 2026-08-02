from typing import Any, Dict
from sqlalchemy import create_engine
from app.plugins.base import DatabaseConnector
from app.database.discovery.models import DatabaseMetadata
from app.database.discovery.factory import InspectorFactory

class BigQueryConnector(DatabaseConnector):
    @property
    def name(self) -> str:
        return "bigquery"
        
    async def connect(self, connection_params: Dict[str, Any]) -> None:
        pass
        
    async def disconnect(self) -> None:
        pass
        
    async def discover(self) -> DatabaseMetadata:
        engine = create_engine("bigquery://dummy")
        inspector = InspectorFactory.create_inspector("generic_sqlalchemy")
        return inspector.inspect(engine, "bigquery_db")

    def get_engine(self):
        return create_engine("bigquery://dummy")

    def build_sample_query(
        self, 
        schema_name: str, 
        table_name: str, 
        select_clause: str,
        strategy: str, 
        sample_size: int,
        group_by: str | None = None,
        order_by: str | None = None,
        limit: int | None = None
    ) -> str:
        query = f"SELECT {select_clause} FROM {schema_name}.{table_name}"
        if strategy == "random":
            query += f" TABLESAMPLE SYSTEM (10 PERCENT) LIMIT {sample_size}"
        elif strategy == "limit":
            query += f" LIMIT {sample_size}"
            
        if group_by:
            query += f" GROUP BY {group_by}"
        if order_by:
            query += f" ORDER BY {order_by}"
        if limit and strategy != "limit":
            query += f" LIMIT {limit}"
            
        return query
