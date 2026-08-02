from app.logical_query.interfaces import IExpressionBuilder
from app.logical_query.models import LogicalExpression, LogicalLiteral, ExpressionType, LogicalColumn

class DeterministicExpressionBuilder(IExpressionBuilder):
    def build(self, metadata: dict) -> LogicalExpression:
        # A simple factory for deterministic evaluation
        if "column" in metadata:
            return LogicalColumn(column_name=metadata["column"], table_name=metadata.get("table"))
        elif "literal" in metadata:
            return LogicalLiteral(value=metadata["literal"])
            
        return LogicalLiteral(value=str(metadata))
