from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext, Severity

class RowLimitValidator(IValidator):
    def __init__(self, max_rows: int = 1000, enforce_limit: bool = True):
        self.max_rows = max_rows
        self.enforce_limit = enforce_limit

    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        violations = []
        
        if self.enforce_limit:
            if not ast.limit:
                violations.append(Violation(
                    rule="MISSING_LIMIT",
                    code="LMT-001",
                    message="Query must have a row LIMIT for safety.",
                    reason="Unbounded queries can crash the analytical application by pulling millions of rows.",
                    suggested_fix=f"Append LIMIT {self.max_rows} to your query.",
                    severity=Severity.ERROR
                ))
            elif ast.limit.limit > self.max_rows:
                violations.append(Violation(
                    rule="LIMIT_EXCEEDS_MAX",
                    code="LMT-002",
                    message=f"Query limit {ast.limit.limit} exceeds maximum allowed {self.max_rows}.",
                    reason="Requesting too many rows exceeds platform bounds.",
                    suggested_fix=f"Reduce your LIMIT to be {self.max_rows} or fewer.",
                    severity=Severity.ERROR
                ))
                
        return violations
