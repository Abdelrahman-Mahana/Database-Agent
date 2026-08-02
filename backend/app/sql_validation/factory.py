from app.sql_validation.interfaces import IPolicyEngine
from app.sql_validation.registry import PolicyRegistry
from app.sql_validation.policy_engine import DeterministicPolicyEngine

class PolicyFactory:
    def __init__(self, registry: PolicyRegistry):
        self.registry = registry
        
    def create_engine(self) -> IPolicyEngine:
        return DeterministicPolicyEngine(self.registry.get_all())
