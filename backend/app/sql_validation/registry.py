from typing import List
from app.sql_validation.interfaces import IPolicy

class PolicyRegistry:
    def __init__(self):
        self._policies: List[IPolicy] = []
        
    def register(self, policy: IPolicy):
        self._policies.append(policy)
        
    def get_all(self) -> List[IPolicy]:
        return self._policies
