import structlog
from typing import Optional
from app.sql_renderer.models import SQLDocument
from app.sql_renderer.interfaces import IRendererFactory
from app.sql_renderer.cache import SQLCache
from app.dialect.service import DialectTranslationService

logger = structlog.get_logger(__name__)

class SQLRenderingService:
    def __init__(
        self,
        factory: IRendererFactory,
        cache: SQLCache,
        dialect_service: DialectTranslationService
    ):
        self.factory = factory
        self.cache = cache
        self.dialect_service = dialect_service

    def render(self, query_id: str) -> SQLDocument:
        logger.info("Rendering SQL", query_id=query_id)
        
        cached = self.cache.get_by_dialect_query(query_id)
        if cached:
            return cached
            
        dialect_query = self.dialect_service.get_query(query_id)
        if not dialect_query:
            raise ValueError(f"Dialect Query {query_id} not found")
            
        renderer = self.factory.get_renderer(dialect_query.dialect_name)
        
        document = renderer.render(dialect_query)
        self.cache.set(document)
        return document

    def get_document(self, query_id: str) -> Optional[SQLDocument]:
        return self.cache.get(query_id)
