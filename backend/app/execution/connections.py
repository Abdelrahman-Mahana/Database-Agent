from typing import Dict, Any
from app.execution.interfaces import IConnection
from app.sql_renderer.models import SQLDocument
from app.execution.models import TransactionMode

class DummyConnection(IConnection):
    def __init__(self, dialect: str):
        self.dialect = dialect
        self.is_open = False
        
    def connect(self) -> None:
        self.is_open = True
        
    def close(self) -> None:
        self.is_open = False
        
    def begin(self, mode: TransactionMode) -> None:
        if not self.is_open:
            raise Exception("Connection is closed.")
            
    def commit(self) -> None:
        if not self.is_open:
            raise Exception("Connection is closed.")
            
    def rollback(self) -> None:
        if not self.is_open:
            raise Exception("Connection is closed.")
        
    def execute(self, sql_doc: SQLDocument) -> Dict[str, Any]:
        if not self.is_open:
            raise Exception("Connection is closed.")
        return {
            "rows_returned": 0,
            "rows_affected": 0,
            "metadata": {
                "server_version": f"{self.dialect}-simulated-1.0",
                "execution_plan": "Simulated Plan",
                "ast_hash": sql_doc.ast_hash
            }
        }
        
    def cancel_current_execution(self) -> bool:
        return True
