from abc import ABC, abstractmethod
from typing import List
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import ValidationResult, Violation, ValidationContext

class IValidator(ABC):
    @abstractmethod
    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        pass

class IPolicy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass
        
    @abstractmethod
    def get_validators(self) -> List[IValidator]:
        pass

class IPolicyEngine(ABC):
    @abstractmethod
    def evaluate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> ValidationResult:
        pass
