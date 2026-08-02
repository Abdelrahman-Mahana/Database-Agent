from app.context_builder.interfaces import IContextExtractor
from app.context_builder.models import StructuredContext, ContextBuildRequest, TableContext, ColumnContext

class SchemaContextExtractor(IContextExtractor):
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        if request.schema_intelligence:
            context.schema_context.summary = request.schema_intelligence.get("summary", "")
            tables = request.schema_intelligence.get("tables", {})
            for t_name, t_data in tables.items():
                table_ctx = TableContext(name=t_name, description=t_data.get("description", ""))
                cols = t_data.get("columns", {})
                for c_name, c_data in cols.items():
                    table_ctx.columns[c_name] = ColumnContext(
                        name=c_name,
                        type=c_data.get("type", ""),
                        description=c_data.get("description", "")
                    )
                context.schema_context.tables[t_name] = table_ctx
                
        if request.database_metadata:
            context.database_context.dialect = request.database_metadata.get("dialect", "")
            context.database_context.version = request.database_metadata.get("version", "")
