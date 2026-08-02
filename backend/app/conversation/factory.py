from app.conversation.interfaces import IConversationManager

class ConversationManagerRegistry:
    def __init__(self):
        self._managers = {}
        
    def register(self, name: str, manager: IConversationManager):
        self._managers[name] = manager
        
    def get(self, name: str) -> IConversationManager:
        return self._managers.get(name)

class ConversationManagerFactory:
    def __init__(self, registry: ConversationManagerRegistry, default_manager: IConversationManager):
        self.registry = registry
        self.default_manager = default_manager
        
    def get_manager(self, name: str = None) -> IConversationManager:
        if name:
             m = self.registry.get(name)
             if m: return m
        return self.default_manager
