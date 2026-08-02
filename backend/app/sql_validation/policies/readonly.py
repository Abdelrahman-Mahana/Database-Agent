from typing import List
from app.sql_validation.interfaces import IPolicy, IValidator

class ReadOnlyPolicy(IPolicy):
    def __init__(self, stmt_val, ast_val, perm_val):
        self.validators = [stmt_val, ast_val, perm_val]
        
    @property
    def name(self) -> str:
        return "READ_ONLY"
        
    def get_validators(self) -> List[IValidator]:
        return self.validators
