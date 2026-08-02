from app.dialect.translator import BaseDialectTranslator

class SQLiteTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="sqlite", quote_char='"')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "AVG",
            "VARIANCE": "AVG",
            "MEDIAN": "AVG"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "TEXT",
            "DATETIME": "TEXT",
            "DOUBLE": "REAL"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
