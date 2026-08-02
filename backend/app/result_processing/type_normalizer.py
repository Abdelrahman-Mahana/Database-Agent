from typing import Any
from app.result_processing.interfaces import ITypeNormalizer
from app.result_processing.models import GenericDataType

class DeterministicTypeNormalizer(ITypeNormalizer):
    def __init__(self):
        self._type_map = {
            "int": GenericDataType.INTEGER,
            "int4": GenericDataType.INTEGER,
            "int8": GenericDataType.INTEGER,
            "bigint": GenericDataType.INTEGER,
            "float": GenericDataType.FLOAT,
            "float8": GenericDataType.FLOAT,
            "numeric": GenericDataType.DECIMAL,
            "decimal": GenericDataType.DECIMAL,
            "bool": GenericDataType.BOOLEAN,
            "boolean": GenericDataType.BOOLEAN,
            "date": GenericDataType.DATE,
            "datetime": GenericDataType.DATETIME,
            "timestamp": GenericDataType.TIMESTAMP,
            "uuid": GenericDataType.UUID,
            "json": GenericDataType.JSON,
            "jsonb": GenericDataType.JSON,
            "varchar": GenericDataType.STRING,
            "text": GenericDataType.STRING,
            "bytea": GenericDataType.BINARY,
            "blob": GenericDataType.BINARY
        }

    def normalize(self, native_type: str) -> GenericDataType:
        if not native_type:
            return GenericDataType.UNKNOWN
        return self._type_map.get(native_type.lower(), GenericDataType.STRING)

    def convert_value(self, value: Any, target_type: GenericDataType) -> Any:
        if value is None:
            return None
        # In a deterministic engine without true processing, 
        # we assume values are already correctly typed by the DB driver
        # or we cast them generically.
        if target_type == GenericDataType.STRING:
            return str(value)
        return value
