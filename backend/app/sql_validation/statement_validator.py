from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext, Severity

class StatementValidator(IValidator):
    def __init__(self):
        self.allowed_statements = {"SELECT", "WITH", "UNION"}
        self.rejected_statements = {
            "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", 
            "ALTER", "DROP", "CREATE", "GRANT", "REVOKE"
        }

    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        violations = []
        sql_upper = sql_doc.sql.upper().strip()
        
        starts_with_allowed = any(sql_upper.startswith(stmt) for stmt in self.allowed_statements)
        if not starts_with_allowed:
            violations.append(Violation(
                rule="STATEMENT_TYPE_NOT_ALLOWED",
                code="STMT-001",
                message="Statement must start with SELECT, WITH, or UNION.",
                reason="DML and DDL commands are strictly prohibited in the analytical engine.",
                suggested_fix="Rewrite query as a SELECT statement.",
                severity=Severity.CRITICAL
            ))
            
        for rejected in self.rejected_statements:
            if f"{rejected} " in sql_upper or sql_upper.startswith(rejected):
                violations.append(Violation(
                    rule="DML_DDL_DETECTED",
                    code="STMT-002",
                    message=f"Dangerous statement detected: {rejected}",
                    reason="Modifying data or schema is not allowed.",
                    suggested_fix="Remove any DML or DDL commands from the query.",
                    severity=Severity.CRITICAL
                ))
                
        return violations
