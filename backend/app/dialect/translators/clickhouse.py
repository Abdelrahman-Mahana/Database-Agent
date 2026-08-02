from app.dialect.translator import BaseDialectTranslator

class ClickHouseTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="clickhouse", quote_char='`')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "stddevSamp",
            "VARIANCE": "varSamp",
            "MEDIAN": "median"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "String",
            "DATETIME": "DateTime",
            "DOUBLE": "Float64"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
