from typing import Any, List
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from app.database.discovery.interfaces import IDatabaseInspector
from app.database.discovery.models import (
    DatabaseMetadata, SchemaMetadata, TableMetadata, ColumnMetadata,
    StatisticsMetadata, IndexMetadata, ForeignKeyMetadata, ConstraintMetadata,
    RelationshipEdge
)
from app.database.discovery.registry import registry

class GenericSQLAlchemyInspector(IDatabaseInspector):
    """
    Generic Database Inspector using SQLAlchemy.
    Builds the DatabaseMetadata hierarchy and relationship graph.
    """
    def inspect(self, engine_or_connection: Any, db_name: str) -> DatabaseMetadata:
        engine: Engine = engine_or_connection
        inspector = inspect(engine)
        
        version = None
        try:
            version = str(engine.dialect.server_version_info)
        except Exception:
            pass

        metadata = DatabaseMetadata(
            name=db_name,
            version=version
        )
        
        schema_names = inspector.get_schema_names()
        if not schema_names:
            schema_names = [None]  # type: ignore
            
        for schema_name in schema_names:
            schema_meta = SchemaMetadata(name=schema_name or "default")
            
            # Extract Tables
            try:
                table_names = inspector.get_table_names(schema=schema_name)
            except Exception:
                table_names = []
            
            for table_name in table_names:
                table_meta = self._build_table_metadata(inspector, table_name, schema_name, is_view=False)
                schema_meta.tables.append(table_meta)
                
            # Extract Views
            try:
                view_names = inspector.get_view_names(schema=schema_name)
            except Exception:
                view_names = []
                
            for view_name in view_names:
                view_meta = self._build_table_metadata(inspector, view_name, schema_name, is_view=True)
                schema_meta.views.append(view_meta)
                
            # Materialized views
            try:
                mview_names = getattr(inspector, "get_materialized_view_names", lambda schema: [])(schema=schema_name)
                for mview_name in mview_names:
                    mview_meta = self._build_table_metadata(inspector, mview_name, schema_name, is_view=True)
                    mview_meta.is_materialized_view = True
                    schema_meta.materialized_views.append(mview_meta)
            except Exception:
                pass
                
            metadata.schemas.append(schema_meta)
            
        # Build Relationship Graph across the entire database
        metadata.relationships = self._build_relationship_graph(metadata)
            
        return metadata
        
    def _build_table_metadata(self, inspector, table_name: str, schema_name: str, is_view: bool) -> TableMetadata:
        table_meta = TableMetadata(name=table_name, is_view=is_view)
        
        # Base columns
        try:
            columns = inspector.get_columns(table_name, schema=schema_name)
            for col in columns:
                col_meta = ColumnMetadata(
                    name=col.get("name"),
                    data_type=str(col.get("type")),
                    nullable=col.get("nullable", True),
                    default=str(col.get("default")) if col.get("default") is not None else None,
                    comment=col.get("comment")
                )
                table_meta.columns.append(col_meta)
        except Exception:
            pass
            
        # Primary Keys
        try:
            pk_info = inspector.get_pk_constraint(table_name, schema=schema_name)
            if pk_info and pk_info.get("constrained_columns"):
                table_meta.primary_keys = pk_info["constrained_columns"]
                for col in table_meta.columns:
                    if col.name in table_meta.primary_keys:
                        col.primary_key = True
        except Exception:
            pass
            
        # Foreign Keys
        try:
            fks = inspector.get_foreign_keys(table_name, schema=schema_name)
            for fk in fks:
                fk_meta = ForeignKeyMetadata(
                    name=fk.get("name") or f"fk_{table_name}_{fk.get('referred_table', 'unknown')}",
                    constrained_columns=fk.get("constrained_columns", []),
                    referred_schema=fk.get("referred_schema") or schema_name,
                    referred_table=fk.get("referred_table", ""),
                    referred_columns=fk.get("referred_columns", [])
                )
                table_meta.foreign_keys.append(fk_meta)
                # Mark columns as FK
                for col in table_meta.columns:
                    if col.name in fk_meta.constrained_columns:
                        col.foreign_key = True
        except Exception:
            pass
            
        # Indexes
        try:
            indexes = inspector.get_indexes(table_name, schema=schema_name)
            for idx in indexes:
                idx_meta = IndexMetadata(
                    name=idx.get("name") or "idx_unknown",
                    columns=idx.get("column_names", []),
                    unique=idx.get("unique", False)
                )
                table_meta.indexes.append(idx_meta)
                
                # Mark columns
                for col in table_meta.columns:
                    if col.name in idx_meta.columns:
                        col.indexed = True
                        if idx_meta.unique:
                            col.unique = True
        except Exception:
            pass
            
        # Unique Constraints
        try:
            uqs = inspector.get_unique_constraints(table_name, schema=schema_name)
            for uq in uqs:
                uq_meta = ConstraintMetadata(
                    name=uq.get("name") or "uq_unknown",
                    type="UNIQUE"
                )
                table_meta.constraints.append(uq_meta)
                # Mark columns unique if applicable (SQLAlchemy uq constraint has column_names)
                if "column_names" in uq:
                    for col in table_meta.columns:
                        if col.name in uq["column_names"]:
                            col.unique = True
        except Exception:
            pass
            
        # Check Constraints
        try:
            checks = inspector.get_check_constraints(table_name, schema=schema_name)
            for check in checks:
                check_meta = ConstraintMetadata(
                    name=check.get("name") or "chk_unknown",
                    type="CHECK",
                    definition=check.get("sqltext")
                )
                table_meta.constraints.append(check_meta)
        except Exception:
            pass
            
        # Table Statistics
        # We'd fetch row counts via dialect-specific queries or standard metrics if available
        # But as per the generic requirement, we leave it as None unless we can safely query it
        table_meta.statistics = StatisticsMetadata(row_count=None)
            
        return table_meta
        
    def _build_relationship_graph(self, db_meta: DatabaseMetadata) -> List[RelationshipEdge]:
        edges = []
        for schema in db_meta.schemas:
            # Tables
            for table in schema.tables:
                for fk in table.foreign_keys:
                    edge = RelationshipEdge(
                        source_schema=schema.name,
                        source_table=table.name,
                        source_columns=fk.constrained_columns,
                        target_schema=fk.referred_schema or schema.name,
                        target_table=fk.referred_table,
                        target_columns=fk.referred_columns,
                        relationship_name=fk.name
                    )
                    edges.append(edge)
            # Views (some might have FKs modeled)
            for view in schema.views:
                for fk in view.foreign_keys:
                    edge = RelationshipEdge(
                        source_schema=schema.name,
                        source_table=view.name,
                        source_columns=fk.constrained_columns,
                        target_schema=fk.referred_schema or schema.name,
                        target_table=fk.referred_table,
                        target_columns=fk.referred_columns,
                        relationship_name=fk.name
                    )
                    edges.append(edge)
        return edges

# Register the generic inspector
registry.register("generic_sqlalchemy", GenericSQLAlchemyInspector)
