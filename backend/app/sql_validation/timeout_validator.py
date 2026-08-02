from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext, Severity

class TimeoutValidator(IValidator):
    def __init__(self, max_complexity_level: str = "HIGH"):
        self.max_complexity_level = max_complexity_level
        self.complexity_scores = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        violations = []
        
        query_score = self.complexity_scores.get(sql_doc.estimated_complexity.upper(), 1)
        max_score = self.complexity_scores.get(self.max_complexity_level.upper(), 3)
        
        if query_score > max_score:
            violations.append(Violation(
                rule="TIMEOUT_RISK",
                code="TMO-001",
                message=f"Estimated complexity {sql_doc.estimated_complexity} exceeds max {self.max_complexity_level} (Timeout Risk).",
                reason="The query is highly likely to time out based on structural complexity.",
                suggested_fix="Filter aggressively using indexes or split into smaller queries.",
                severity=Severity.WARNING
            ))
            
        return violations
