from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext, Severity

class ComplexityValidator(IValidator):
    def __init__(self, max_joins: int = 5):
        self.max_joins = max_joins

    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        violations = []
        
        join_count = len(ast.joins) if ast.joins else 0
        if join_count > self.max_joins:
            violations.append(Violation(
                rule="TOO_MANY_JOINS",
                code="CMP-001",
                message=f"Query has {join_count} joins, exceeding maximum allowed {self.max_joins}.",
                reason="Excessive joins degrade database performance significantly.",
                suggested_fix="Simplify the query to join fewer tables or pre-aggregate data.",
                severity=Severity.ERROR
            ))
            
        return violations
