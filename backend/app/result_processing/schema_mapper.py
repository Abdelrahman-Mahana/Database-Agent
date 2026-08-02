# Schema Mapper can map internal schema to external schema, 
# for deterministic engine, it's a pass-through component.
from app.result_processing.models import ResultSchema

class SchemaMapper:
    def map_schema(self, schema: ResultSchema) -> ResultSchema:
        return schema
