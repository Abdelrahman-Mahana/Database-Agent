from typing import List
from app.sql_validation.interfaces import IPolicy, IValidator

class AnalystPolicy(IPolicy):
    def __init__(self, stmt_val, ast_val, comp_val, limit_val, to_val, perm_val):
        self.validators = [stmt_val, ast_val, comp_val, limit_val, to_val, perm_val]
        
    @property
    def name(self) -> str:
        return "ANALYST"
        
    def get_validators(self) -> List[IValidator]:
        return self.validators
