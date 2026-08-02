from typing import Any, Dict
from sqlalchemy import create_engine
from app.plugins.base import DatabaseConnector
from app.database.discovery.models import DatabaseMetadata
from app.database.discovery.factory import InspectorFactory

class RedshiftConnector(DatabaseConnector):
    @property
    def name(self) -> str:
        return "redshift"
        
    async def connect(self, connection_params: Dict[str, Any]) -> None:
        pass
        
    async def disconnect(self) -> None:
        pass
        
    async def discover(self) -> DatabaseMetadata:
        engine = create_engine("redshift+psycopg2://dummy")
        inspector = InspectorFactory.create_inspector("generic_sqlalchemy")
        return inspector.inspect(engine, "redshift_db")

    def get_engine(self):
        return create_engine("redshift+psycopg2://dummy")

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
        if group_by:
            query += f" GROUP BY {group_by}"
            
        if strategy == "random":
            query += f" ORDER BY RANDOM() LIMIT {sample_size}"
        elif strategy == "limit":
            query += f" LIMIT {sample_size}"
        else:
            if order_by:
                query += f" ORDER BY {order_by}"
            if limit:
                query += f" LIMIT {limit}"
                
        return query
