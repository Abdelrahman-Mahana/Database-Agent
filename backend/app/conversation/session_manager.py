from app.conversation.interfaces import ISessionManager
import uuid

class SessionManager(ISessionManager):
    def get_or_create_session(self, session_id: str = None) -> str:
        if not session_id:
            return str(uuid.uuid4())
        return session_id
