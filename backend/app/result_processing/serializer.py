import json
from typing import Dict, Any
from app.result_processing.interfaces import ISerializer
from app.result_processing.models import ProcessedResult

class ResultSerializer(ISerializer):
    def serialize_dict(self, result: ProcessedResult) -> Dict[str, Any]:
        return result.model_dump()
        
    def serialize_json(self, result: ProcessedResult) -> str:
        # Utilizing pydantic's builtin json serialization which handles datetimes
        return result.model_dump_json()
        
    def serialize_arrow(self, result: ProcessedResult) -> Any:
        # Placeholder for pyarrow table generation if pyarrow is installed
        # For a deterministic strict implementation without adding external non-standard dependencies,
        # we return a dict representation optimized for columnar format
        columns = {col.name: [] for col in result.schema_def.columns}
        for row in result.rows:
            for col_name in columns.keys():
                columns[col_name].append(row.get(col_name))
        return columns
