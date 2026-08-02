from typing import List
from app.sql_validation.interfaces import IPolicyEngine, IPolicy
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import ValidationResult, ValidationContext, Severity

class DeterministicPolicyEngine(IPolicyEngine):
    def __init__(self, policies: List[IPolicy]):
        self.policies = {p.name.upper(): p for p in policies}

    def evaluate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> ValidationResult:
        policy = self.policies.get(context.policy.upper())
        if not policy:
            raise ValueError(f"Policy '{context.policy}' not found.")
            
        all_violations = []
        for validator in policy.get_validators():
            violations = validator.validate(sql_doc, ast, context)
            all_violations.extend(violations)
        
        allowed = True
        max_severity = None
        
        for v in all_violations:
            if v.severity in (Severity.ERROR, Severity.CRITICAL):
                allowed = False
                
            if max_severity is None or v.severity > max_severity:
                max_severity = v.severity
                
        return ValidationResult(
            allowed=allowed,
            severity=max_severity,
            violations=all_violations,
            warnings=[v.message for v in all_violations if v.severity in (Severity.INFO, Severity.WARNING)],
            confidence=1.0,
            policy_used=context.policy
        )
