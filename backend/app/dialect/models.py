from enum import Enum
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from uuid import uuid4

class DialectExpression(BaseModel):
    pass

class DialectIdentifier(DialectExpression):
    name: str
    quote_char: str = '"'

class DialectLiteral(DialectExpression):
    value: Any
    type_name: str = "UNKNOWN"

class DialectFunction(DialectExpression):
    name: str
    args: List[DialectExpression] = Field(default_factory=list)

class DialectOperator(DialectExpression):
    operator: str
    left: Optional[DialectExpression] = None
    right: Optional[DialectExpression] = None
    children: List[DialectExpression] = Field(default_factory=list) # For AND/OR

class DialectAlias(DialectExpression):
    expression: DialectExpression
    alias: DialectIdentifier

class DialectRelation(BaseModel):
    name: DialectIdentifier
    alias: Optional[DialectIdentifier] = None

class DialectJoin(BaseModel):
    join_type: str
    left: Union[DialectRelation, 'DialectJoin']
    right: DialectRelation
    condition: Optional[DialectExpression] = None

class DialectProjection(BaseModel):
    expressions: List[Union[DialectExpression, DialectAlias]] = Field(default_factory=list)

class DialectFilter(BaseModel):
    condition: DialectExpression

class DialectAggregate(BaseModel):
    expressions: List[DialectExpression] = Field(default_factory=list)

class DialectSort(BaseModel):
    orders: List[Dict[str, Union[DialectExpression, str]]] = Field(default_factory=list)

class DialectLimit(BaseModel):
    limit: int
    offset: int = 0

class DialectQuery(BaseModel):
    query_id: str = Field(default_factory=lambda: str(uuid4()))
    logical_query_id: str
    dialect_name: str
    
    relations: List[DialectRelation] = Field(default_factory=list)
    joins: List[DialectJoin] = Field(default_factory=list)
    projections: DialectProjection = Field(default_factory=DialectProjection)
    filters: Optional[DialectFilter] = None
    groupings: Optional[DialectAggregate] = None
    sorts: Optional[DialectSort] = None
    limit: Optional[DialectLimit] = None
    
    estimated_complexity: str = "LOW"
    confidence: float = 1.0

DialectJoin.model_rebuild()
