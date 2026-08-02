from abc import ABC, abstractmethod
from typing import Any
from app.logical_query.models import (
    LogicalQuery, LogicalExpression, LogicalRelation, LogicalJoin,
    LogicalFilter, LogicalProjection
)
from app.dialect.models import (
    DialectQuery, DialectExpression, DialectRelation, DialectJoin,
    DialectFilter, DialectProjection
)

class IDialectTranslator(ABC):
    @property
    @abstractmethod
    def dialect_name(self) -> str:
        pass
        
    @abstractmethod
    def translate_relation(self, relation: LogicalRelation) -> DialectRelation:
        pass
        
    @abstractmethod
    def translate_join(self, join: LogicalJoin) -> DialectJoin:
        pass
        
    @abstractmethod
    def translate_filter(self, filter_obj: LogicalFilter) -> DialectFilter:
        pass
        
    @abstractmethod
    def translate_projection(self, projection: LogicalProjection) -> DialectProjection:
        pass
        
    @abstractmethod
    def translate_expression(self, expr: LogicalExpression) -> DialectExpression:
        pass
        
    @abstractmethod
    def map_function(self, logical_function: str) -> str:
        pass
        
    @abstractmethod
    def map_type(self, logical_type: str) -> str:
        pass

class ITranslatorRegistry(ABC):
    @abstractmethod
    def register(self, translator: IDialectTranslator) -> None:
        pass
        
    @abstractmethod
    def get(self, dialect_name: str) -> IDialectTranslator:
        pass

class ITranslatorFactory(ABC):
    @abstractmethod
    def get_translator(self, dialect_name: str) -> IDialectTranslator:
        pass

class IDialectOptimizer(ABC):
    @abstractmethod
    def optimize(self, query: DialectQuery) -> DialectQuery:
        pass

class IAstBuilder(ABC):
    @abstractmethod
    def build_ast(self, query: LogicalQuery, translator: IDialectTranslator) -> DialectQuery:
        pass
