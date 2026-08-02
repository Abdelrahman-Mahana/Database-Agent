from typing import List
from app.sql_validation.interfaces import IPolicy, IValidator

class AdminPolicy(IPolicy):
    def __init__(self, stmt_val, ast_val):
        self.validators = [stmt_val, ast_val]
        
    @property
    def name(self) -> str:
        return "ADMIN"
        
    def get_validators(self) -> List[IValidator]:
        return self.validators
