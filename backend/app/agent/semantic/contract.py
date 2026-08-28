"""Core Semantic Contract Data Models.

Defines the mathematical and business specification required before SQL generation:
- Target Grain & Entity
- Business Measures & Formulas
- Dimensions & Groupings
- Normalized Time Specifications
- Typed Filter Predicates
- Sorting & Limit constraints
- Contract Freeze & Cryptographic Hashing
"""
from __future__ import annotations

import hashlib
import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GrainType(str, Enum):
    """The mathematical granularity of the query output."""
    SCALAR = "scalar"                    # Exactly 1 aggregate value (e.g. Total Revenue, Total Count)
    ENTITY_GRAIN = "entity"              # 1 row per primary entity instance (e.g. 1 row per customer)
    TEMPORAL_GRAIN = "temporal"          # 1 row per time period (e.g. 1 row per month, 1 row per year)
    MULTIDIMENSIONAL = "multidimensional"  # 1 row per combination of dimensions (e.g. Country x Year)
    LIST_GRAIN = "list"                  # Unaggregated list of records / entities


class FormulaType(str, Enum):
    """Mathematical aggregation or formula type."""
    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    CUSTOM = "custom"


class SemanticGrain(BaseModel):
    """Specifies the logical and physical grain of the target output."""
    grain_type: GrainType = GrainType.ENTITY_GRAIN
    primary_entity: Optional[str] = None
    grain_keys: List[str] = Field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grain_type": self.grain_type.value if hasattr(self.grain_type, "value") else str(self.grain_type),
            "primary_entity": self.primary_entity,
            "grain_keys": self.grain_keys,
            "description": self.description,
        }


class MetricSpec(BaseModel):
    """Formal business measure / metric definition."""
    metric_id: str
    display_name: str = ""
    formula_type: FormulaType = FormulaType.SUM
    expression: str = ""              # e.g. "Invoice.Total" or "InvoiceLine.UnitPrice * InvoiceLine.Quantity"
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    requires_distinct: bool = False
    is_calculated: bool = False
    unit: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)

    def to_sql_projection(self, table_alias: Optional[str] = None) -> str:
        """Format as SQL expression snippet."""
        col = self.source_column or self.expression or "*"
        if table_alias and "." not in col and col != "*":
            target = f"{table_alias}.{col}"
        else:
            target = col

        if self.formula_type == FormulaType.SUM:
            return f"SUM({target})"
        elif self.formula_type == FormulaType.COUNT_DISTINCT:
            return f"COUNT(DISTINCT {target})"
        elif self.formula_type == FormulaType.COUNT:
            return f"COUNT({target})"
        elif self.formula_type == FormulaType.AVG:
            return f"AVG({target})"
        elif self.formula_type == FormulaType.MIN:
            return f"MIN({target})"
        elif self.formula_type == FormulaType.MAX:
            return f"MAX({target})"
        elif self.expression:
            return self.expression
        return target


class DimensionSpec(BaseModel):
    """Grouping dimension or attribute specification."""
    dimension_id: str
    display_name: str = ""
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    temporal_grain: Optional[str] = None  # e.g. "YEAR", "MONTH", "DAY"
    is_primary_key: bool = False
    aliases: List[str] = Field(default_factory=list)

    def to_sql_column(self, table_alias: Optional[str] = None) -> str:
        col = self.source_column or self.dimension_id
        if table_alias and "." not in col:
            return f"{table_alias}.{col}"
        return col


class TimeSpec(BaseModel):
    """Normalized temporal scope and boundary conditions."""
    time_column: Optional[str] = None
    source_table: Optional[str] = None
    start_date: Optional[str] = None      # ISO format: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
    end_date: Optional[str] = None        # ISO format: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
    granularity: Optional[str] = None    # "YEAR", "QUARTER", "MONTH", "WEEK", "DAY"
    raw_expression: str = ""             # Original phrase e.g. "in 2012", "last month", "في عام 2023"
    is_relative: bool = False
    comparison_start_date: Optional[str] = None
    comparison_end_date: Optional[str] = None

    @property
    def has_bounds(self) -> bool:
        return bool(self.start_date or self.end_date)


class FilterOperator(str, Enum):
    """Normalized filter comparison operators."""
    EQ = "="
    NEQ = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"
    ILIKE = "ILIKE"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"


class FilterSpec(BaseModel):
    """Typed and grounded filter condition."""
    concept: str = ""
    target_table: Optional[str] = None
    target_column: Optional[str] = None
    operator: FilterOperator = FilterOperator.EQ
    raw_value: Any = None
    normalized_value: Any = None
    data_type: str = "text"              # text, integer, float, date, boolean
    is_mandatory: bool = True
    raw_expression: str = ""

    def to_sql_predicate(self, table_alias: Optional[str] = None) -> str:
        col = self.target_column or self.concept
        if table_alias and "." not in col:
            col = f"{table_alias}.{col}"

        op = self.operator.value if hasattr(self.operator, "value") else str(self.operator)
        if op in ("IS NULL", "IS NOT NULL"):
            return f"{col} {op}"

        val = self.normalized_value if self.normalized_value is not None else self.raw_value
        if op in ("IN", "NOT IN") and isinstance(val, (list, tuple, set)):
            formatted = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in val)
            return f"{col} {op} ({formatted})"
        elif op == "BETWEEN" and isinstance(val, (list, tuple)) and len(val) >= 2:
            v1 = f"'{val[0]}'" if isinstance(val[0], str) else str(val[0])
            v2 = f"'{val[1]}'" if isinstance(val[1], str) else str(val[1])
            return f"{col} BETWEEN {v1} AND {v2}"
        elif isinstance(val, str):
            # Escape quotes
            val_escaped = val.replace("'", "''")
            if op in ("LIKE", "ILIKE"):
                return f"{col} {op} '%{val_escaped}%'"
            return f"{col} {op} '{val_escaped}'"
        elif val is not None:
            return f"{col} {op} {val}"
        return f"{col} IS NOT NULL"


class SortSpec(BaseModel):
    """Sorting specification."""
    target: str                          # Column or metric id
    direction: str = "DESC"              # "ASC" or "DESC"
    is_metric: bool = True


class SemanticContract(BaseModel):
    """
    Formal, Frozen Semantic Contract.
    
    Establishes the exact business semantics, grain, measures, dimensions,
    filters, time bounds, and answerability status before SQL generation.
    Once frozen, any mutation is forbidden, and the AST Validator proves
    that the generated SQL adheres 100% to this contract.
    """
    contract_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    raw_question: str
    normalized_question: str = ""
    intent: str = "database"             # "database", "schema", "conversation", "off_topic"
    route: str = "data_query"            # "data_query", "schema", "conversation", "tools"
    
    # Core Semantics
    primary_entity: Optional[str] = None
    grain: SemanticGrain = Field(default_factory=SemanticGrain)
    measures: List[MetricSpec] = Field(default_factory=list)
    dimensions: List[DimensionSpec] = Field(default_factory=list)
    time_spec: Optional[TimeSpec] = None
    filters: List[FilterSpec] = Field(default_factory=list)
    sorting: List[SortSpec] = Field(default_factory=list)
    limit: Optional[int] = None
    expected_output_shape: str = "table" # "scalar", "list", "table", "ranking", "time_series"
    analysis_type: str = "unknown"

    # Answerability & Ambiguity Controls
    is_answerable: bool = True
    unsupported_reason: Optional[str] = None
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None
    ambiguity_candidates: List[str] = Field(default_factory=list)
    ambiguity_evidence: Optional[str] = None

    # Quality & Observability
    confidence: float = 1.0
    confidence_breakdown: Dict[str, float] = Field(default_factory=dict)
    
    # Contract Freeze Status
    is_frozen: bool = False
    contract_hash: str = ""

    def freeze(self) -> "SemanticContract":
        """Freeze contract state and compute immutable cryptographic hash."""
        payload = {
            "question": self.normalized_question or self.raw_question,
            "intent": self.intent,
            "route": self.route,
            "primary_entity": (self.primary_entity or "").lower(),
            "grain": self.grain.to_dict(),
            "measures": sorted([
                f"{m.metric_id}:{m.formula_type.value if hasattr(m.formula_type, 'value') else m.formula_type}:{m.source_table or ''}.{m.source_column or ''}"
                for m in self.measures
            ]),
            "dimensions": sorted([
                f"{d.dimension_id}:{d.source_table or ''}.{d.source_column or ''}:{d.temporal_grain or ''}"
                for d in self.dimensions
            ]),
            "time_spec": {
                "col": self.time_spec.time_column if self.time_spec else None,
                "start": self.time_spec.start_date if self.time_spec else None,
                "end": self.time_spec.end_date if self.time_spec else None,
                "granularity": self.time_spec.granularity if self.time_spec else None,
            } if self.time_spec else None,
            "filters": sorted([
                f"{f.target_table or ''}.{f.target_column or f.concept}:{f.operator.value if hasattr(f.operator, 'value') else f.operator}:{f.normalized_value}"
                for f in self.filters
            ]),
            "sorting": sorted([f"{s.target}:{s.direction}" for s in self.sorting]),
            "limit": self.limit,
            "shape": self.expected_output_shape,
        }
        serialized = json.dumps(payload, sort_keys=True)
        self.contract_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        self.is_frozen = True
        return self

    def summary(self) -> str:
        """Produce human-readable and LLM-friendly contract summary."""
        parts = [f"Semantic Contract [ID: {self.contract_id}, Hash: {self.contract_hash or 'unfrozen'}]"]
        if self.primary_entity:
            parts.append(f"  Primary Entity: {self.primary_entity}")
        parts.append(f"  Target Grain: {self.grain.grain_type.value if hasattr(self.grain.grain_type, 'value') else self.grain.grain_type} ({self.grain.description or 'default'})")
        
        if self.measures:
            m_strs = [f"{m.display_name or m.metric_id} ({m.formula_type.value if hasattr(m.formula_type, 'value') else m.formula_type} of {m.source_column or m.expression})" for m in self.measures]
            parts.append(f"  Measures ({len(self.measures)}): {', '.join(m_strs)}")
        
        if self.dimensions:
            d_strs = [f"{d.display_name or d.dimension_id} ({d.source_table or ''}.{d.source_column or ''})" for d in self.dimensions]
            parts.append(f"  Dimensions ({len(self.dimensions)}): {', '.join(d_strs)}")
        
        if self.time_spec and (self.time_spec.start_date or self.time_spec.raw_expression):
            parts.append(f"  Time Bounds: {self.time_spec.raw_expression} -> [{self.time_spec.start_date} to {self.time_spec.end_date}] on {self.time_spec.time_column or 'date'}")
        
        if self.filters:
            f_strs = [f.to_sql_predicate() for f in self.filters]
            parts.append(f"  Filters ({len(self.filters)}): {', '.join(f_strs)}")
        
        if self.sorting:
            s_strs = [f"{s.target} {s.direction}" for s in self.sorting]
            parts.append(f"  Sorting: {', '.join(s_strs)}")
            
        if self.limit:
            parts.append(f"  Limit: {self.limit}")
            
        parts.append(f"  Output Shape: {self.expected_output_shape}")
        return "\n".join(parts)
