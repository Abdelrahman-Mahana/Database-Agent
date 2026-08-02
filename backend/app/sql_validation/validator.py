from typing import List
from app.sql_validation.interfaces import IValidator
from app.sql_renderer.models import SQLDocument
from app.dialect.models import DialectQuery
from app.sql_validation.models import Violation, ValidationContext

class CompositeValidator(IValidator):
    def __init__(self, validators: List[IValidator]):
        self.validators = validators

    def validate(self, sql_doc: SQLDocument, ast: DialectQuery, context: ValidationContext) -> List[Violation]:
        all_violations = []
        for validator in self.validators:
            violations = validator.validate(sql_doc, ast, context)
            all_violations.extend(violations)
        return all_violations
