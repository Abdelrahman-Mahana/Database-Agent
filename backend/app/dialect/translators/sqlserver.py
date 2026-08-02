from app.dialect.translator import BaseDialectTranslator

class SQLServerTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="sqlserver", quote_char='"')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "STDEV",
            "VARIANCE": "VAR",
            "MEDIAN": "PERCENTILE_CONT"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "NVARCHAR",
            "DATETIME": "DATETIME2",
            "DOUBLE": "FLOAT"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
