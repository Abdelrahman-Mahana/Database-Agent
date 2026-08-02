from abc import ABC, abstractmethod
from typing import List
from app.dialect.models import (
    DialectQuery, DialectExpression, DialectRelation, DialectJoin, DialectFilter, 
    DialectProjection, DialectAggregate, DialectSort, DialectLimit
)
from app.sql_renderer.models import SQLDocument
from app.sql_renderer.parameter_builder import ParameterBuilder

class ISQLRenderer(ABC):
    @property
    @abstractmethod
    def dialect_name(self) -> str:
        pass
        
    @abstractmethod
    def render(self, query: DialectQuery) -> SQLDocument:
        pass
        
    @abstractmethod
    def render_relation(self, relation: DialectRelation) -> str:
        pass
        
    @abstractmethod
    def render_projection(self, projection: DialectProjection, param_builder: ParameterBuilder) -> str:
        pass
        
    @abstractmethod
    def render_filter(self, filter_obj: DialectFilter, param_builder: ParameterBuilder) -> str:
        pass
        
    @abstractmethod
    def render_join(self, joins: List[DialectJoin], param_builder: ParameterBuilder) -> str:
        pass
        
    @abstractmethod
    def render_expression(self, expr: DialectExpression, param_builder: ParameterBuilder) -> str:
        pass
        
    @abstractmethod
    def render_group_by(self, group_obj: DialectAggregate, param_builder: ParameterBuilder) -> str:
        pass
        
    @abstractmethod
    def render_order_by(self, order_obj: DialectSort, param_builder: ParameterBuilder) -> str:
        pass
        
    @abstractmethod
    def render_limit(self, limit_obj: DialectLimit, param_builder: ParameterBuilder) -> str:
        pass

class IRendererRegistry(ABC):
    @abstractmethod
    def register(self, renderer: ISQLRenderer) -> None:
        pass
        
    @abstractmethod
    def get(self, dialect_name: str) -> ISQLRenderer:
        pass

class IRendererFactory(ABC):
    @abstractmethod
    def get_renderer(self, dialect_name: str) -> ISQLRenderer:
        pass
