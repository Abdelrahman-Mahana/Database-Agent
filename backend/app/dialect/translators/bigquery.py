from app.dialect.translator import BaseDialectTranslator

class BigQueryTranslator(BaseDialectTranslator):
    def __init__(self):
        super().__init__(name="bigquery", quote_char='`')
        
    def map_function(self, logical_function: str) -> str:
        mapping = {
            "STDDEV": "STDDEV_SAMP",
            "VARIANCE": "VAR_SAMP",
            "MEDIAN": "APPROX_QUANTILES"
        }
        return mapping.get(logical_function.upper(), logical_function.upper())
        
    def map_type(self, logical_type: str) -> str:
        mapping = {
            "STRING": "STRING",
            "DATETIME": "DATETIME",
            "DOUBLE": "FLOAT64"
        }
        return mapping.get(logical_type.upper(), logical_type.upper())
