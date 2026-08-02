from app.dialect.translator import BaseDialectTranslator

class MySQLTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="mysql", quote_char='`')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "STDDEV_SAMP",
            "VARIANCE": "VAR_SAMP",
            "MEDIAN": "AVG"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "VARCHAR",
            "DATETIME": "DATETIME",
            "DOUBLE": "DOUBLE"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
