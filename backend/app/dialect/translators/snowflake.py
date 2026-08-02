from app.dialect.translator import BaseDialectTranslator

class SnowflakeTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="snowflake", quote_char='"')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "STDDEV_SAMP",
            "VARIANCE": "VAR_SAMP",
            "MEDIAN": "MEDIAN"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "VARCHAR",
            "DATETIME": "TIMESTAMP_NTZ",
            "DOUBLE": "FLOAT"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
