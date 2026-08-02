from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.conversation.models import (
    ConversationContext, MessageRequest, ValidationResult, MemoryContext, ConversationStateEnum, MemoryEntry, TrackedEntity, ContextReuseDecision
)
from app.context_builder.models import StructuredContext

class IShortTermMemory(ABC):
    @abstractmethod
    def add(self, session_id: str, entry: MemoryEntry) -> None:
        pass
    @abstractmethod
    def get(self, session_id: str) -> List[MemoryEntry]:
        pass
    @abstractmethod
    def clear(self, session_id: str) -> None:
        pass

class ILongTermMemory(ABC):
    @abstractmethod
    def store_insight(self, session_id: str, insight: MemoryEntry) -> None:
        pass
    @abstractmethod
    def retrieve(self, session_id: str) -> List[MemoryEntry]:
        pass

class IMemoryManager(ABC):
    @abstractmethod
    def build_memory_context(self, session_id: str) -> MemoryContext:
        pass

class IHistoryCompressor(ABC):
    @abstractmethod
    def compress(self, history: List[MemoryEntry]) -> List[MemoryEntry]:
        pass

class IEntityTracker(ABC):
    @abstractmethod
    def track(self, session_id: str, text: str, context: Optional[StructuredContext]) -> List[TrackedEntity]:
        pass

class IReferenceResolver(ABC):
    @abstractmethod
    def resolve(self, text: str, entities: List[TrackedEntity], memory: MemoryContext) -> Dict[str, TrackedEntity]:
        pass

class IIntentResolver(ABC):
    @abstractmethod
    def resolve(self, text: str, references: Dict[str, TrackedEntity]) -> str:
        pass

class IContextResolver(ABC):
    @abstractmethod
    def resolve(self, request: MessageRequest, memory: MemoryContext) -> ConversationContext:
        pass

class ITTLManager(ABC):
    @abstractmethod
    def check_expiration(self, last_active: Any) -> bool:
        pass
    @abstractmethod
    def is_context_valid(self, created_at: Any) -> bool:
        pass

class IContextReuse(ABC):
    @abstractmethod
    def evaluate_reuse(self, request: MessageRequest, memory: MemoryContext, ttl_manager: ITTLManager) -> ContextReuseDecision:
        pass

class IConversationValidator(ABC):
    @abstractmethod
    def validate(self, ctx: ConversationContext) -> ValidationResult:
        pass

class ISessionManager(ABC):
    @abstractmethod
    def get_or_create_session(self, session_id: Optional[str]) -> str:
        pass

class IConversationManager(ABC):
    @abstractmethod
    def process_message(self, request: MessageRequest) -> ConversationContext:
        pass
