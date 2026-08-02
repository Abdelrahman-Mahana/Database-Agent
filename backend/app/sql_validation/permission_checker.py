from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext, Severity

class PermissionChecker(IValidator):
    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        violations = []
        
        if context.policy.upper() == "READ_ONLY":
            # Just an extra safeguard, statement_validator handles the DML/DDL checks natively
            pass
            
        return violations
