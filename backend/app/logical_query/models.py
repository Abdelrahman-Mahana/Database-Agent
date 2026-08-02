from enum import Enum
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from uuid import uuid4

class JoinType(str, Enum):
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"
    CROSS = "CROSS"

class LogicalOperator(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUALS = "GREATER_THAN_OR_EQUALS"
    LESS_THAN_OR_EQUALS = "LESS_THAN_OR_EQUALS"
    IN = "IN"
    NOT_IN = "NOT_IN"
    BETWEEN = "BETWEEN"
    LIKE = "LIKE"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"

class AggregationType(str, Enum):
    SUM = "SUM"
    AVG = "AVG"
    COUNT = "COUNT"
    MIN = "MIN"
    MAX = "MAX"
    MEDIAN = "MEDIAN"
    STDDEV = "STDDEV"
    VARIANCE = "VARIANCE"

class SortDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"

class ExpressionType(str, Enum):
    COLUMN = "COLUMN"
    LITERAL = "LITERAL"
    FUNCTION = "FUNCTION"
    OPERATOR = "OPERATOR"

class LogicalExpression(BaseModel):
    expr_type: ExpressionType
    value: Any = None
    children: List['LogicalExpression'] = Field(default_factory=list)

class LogicalColumn(LogicalExpression):
    expr_type: ExpressionType = ExpressionType.COLUMN
    table_name: Optional[str] = None
    column_name: str

class LogicalLiteral(LogicalExpression):
    expr_type: ExpressionType = ExpressionType.LITERAL

class LogicalFunction(LogicalExpression):
    expr_type: ExpressionType = ExpressionType.FUNCTION
    function_name: str

class LogicalAlias(BaseModel):
    expression: LogicalExpression
    alias: str

class LogicalRelation(BaseModel):
    table_name: str
    alias: Optional[str] = None

class LogicalJoin(BaseModel):
    join_type: JoinType
    left_relation: Union[LogicalRelation, 'LogicalJoin']
    right_relation: LogicalRelation
    condition: Optional[LogicalExpression] = None

class LogicalProjection(BaseModel):
    expressions: List[Union[LogicalExpression, LogicalAlias]] = Field(default_factory=list)

class LogicalFilter(BaseModel):
    condition: LogicalExpression

class LogicalAggregate(BaseModel):
    function: AggregationType
    expression: LogicalExpression

class LogicalGroup(BaseModel):
    grouping_expressions: List[LogicalExpression] = Field(default_factory=list)
    aggregations: List[LogicalAlias] = Field(default_factory=list)

class LogicalHaving(BaseModel):
    condition: LogicalExpression

class LogicalOrder(BaseModel):
    expression: LogicalExpression
    direction: SortDirection

class LogicalSort(BaseModel):
    orders: List[LogicalOrder] = Field(default_factory=list)

class LogicalLimit(BaseModel):
    limit: int
    offset: int = 0

class LogicalQuery(BaseModel):
    query_id: str = Field(default_factory=lambda: str(uuid4()))
    query_hash: str
    
    relations: List[LogicalRelation] = Field(default_factory=list)
    joins: List[LogicalJoin] = Field(default_factory=list)
    projections: LogicalProjection = Field(default_factory=LogicalProjection)
    filters: Optional[LogicalFilter] = None
    groupings: Optional[LogicalGroup] = None
    having: Optional[LogicalHaving] = None
    sorts: Optional[LogicalSort] = None
    limit: Optional[LogicalLimit] = None
    
    estimated_complexity: str = "LOW"
    confidence: float = 1.0

# Needed for self-referencing
LogicalExpression.model_rebuild()
LogicalJoin.model_rebuild()
