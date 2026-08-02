from abc import ABC, abstractmethod
from typing import Any, Dict, List, Generator
from app.result_processing.models import ProcessedResult, ResultSchema, GenericDataType, ResultProcessingConfig
from app.execution.models import ExecutionResult

class ITypeNormalizer(ABC):
    @abstractmethod
    def normalize(self, native_type: str) -> GenericDataType:
        pass
        
    @abstractmethod
    def convert_value(self, value: Any, target_type: GenericDataType) -> Any:
        pass

class IMetadataExtractor(ABC):
    @abstractmethod
    def extract(self, execution_result: ExecutionResult) -> ResultSchema:
        pass

class IChunkReader(ABC):
    @abstractmethod
    def read_chunks(self, execution_result: ExecutionResult, chunk_size: int) -> Generator[List[Dict[str, Any]], None, None]:
        pass

class IStreamProcessor(ABC):
    @abstractmethod
    def process_stream(self, execution_result: ExecutionResult, config: ResultProcessingConfig) -> Generator[ProcessedResult, None, None]:
        pass

class IProcessor(ABC):
    @abstractmethod
    def process(self, execution_result: ExecutionResult, config: ResultProcessingConfig) -> ProcessedResult:
        pass

class ISerializer(ABC):
    @abstractmethod
    def serialize_dict(self, result: ProcessedResult) -> Dict[str, Any]:
        pass
        
    @abstractmethod
    def serialize_json(self, result: ProcessedResult) -> str:
        pass
        
    @abstractmethod
    def serialize_arrow(self, result: ProcessedResult) -> Any:
        pass
