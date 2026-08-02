from app.execution.interfaces import ITransactionManager, IConnection
from app.execution.models import TransactionMode

class TransactionManager(ITransactionManager):
    def begin(self, conn: IConnection, mode: TransactionMode) -> None:
        conn.begin(mode)
            
    def commit(self, conn: IConnection) -> None:
        conn.commit()
        
    def rollback(self, conn: IConnection) -> None:
        conn.rollback()
