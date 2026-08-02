from app.dialect.translator import BaseDialectTranslator

class PostgreSQLTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="postgresql", quote_char='"')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "MEDIAN": "PERCENTILE_CONT",
            "STDDEV": "STDDEV_SAMP",
            "VARIANCE": "VAR_SAMP",
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "TEXT",
            "DATETIME": "TIMESTAMP",
            "DOUBLE": "DOUBLE PRECISION"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
