from app.dialect.translator import BaseDialectTranslator

class OracleTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="oracle", quote_char='"')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "STDDEV",
            "VARIANCE": "VARIANCE",
            "MEDIAN": "MEDIAN"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "VARCHAR2",
            "DATETIME": "TIMESTAMP",
            "DOUBLE": "NUMBER"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
