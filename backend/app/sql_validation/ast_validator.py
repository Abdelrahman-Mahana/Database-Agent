from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext, Severity

class AstValidator(IValidator):
    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        violations = []
        
        if not ast.relations and not ast.joins:
            violations.append(Violation(
                rule="NO_SOURCE_TABLE",
                code="AST-001",
                message="Query must have at least one source table or join.",
                reason="A query must read from a table to be a valid analytical operation.",
                suggested_fix="Add a FROM clause referencing a valid table.",
                severity=Severity.ERROR
            ))
            
        if not ast.projections or not ast.projections.expressions:
            violations.append(Violation(
                rule="NO_PROJECTION",
                code="AST-002",
                message="Query must select at least one column.",
                reason="A SELECT statement without columns returns nothing useful.",
                suggested_fix="Specify the columns you wish to retrieve in the SELECT clause.",
                severity=Severity.ERROR
            ))
            
        return violations
