import structlog
from typing import Optional
from app.dialect.models import DialectQuery
from app.dialect.interfaces import ITranslatorFactory, IAstBuilder, IDialectOptimizer
from app.dialect.cache import DialectCache
from app.logical_query.service import LogicalQueryService

logger = structlog.get_logger(__name__)

class DialectTranslationService:
    def __init__(
        self,
        factory: ITranslatorFactory,
        ast_builder: IAstBuilder,
        optimizer: IDialectOptimizer,
        cache: DialectCache,
        logical_query_service: LogicalQueryService
    ):
        self.factory = factory
        self.ast_builder = ast_builder
        self.optimizer = optimizer
        self.cache = cache
        self.logical_query_service = logical_query_service

    def translate(self, logical_query_id: str, dialect_name: str) -> DialectQuery:
        logger.info("Translating logical query", logical_query_id=logical_query_id, dialect=dialect_name)
        
        cached = self.cache.get_by_logical_id(logical_query_id, dialect_name)
        if cached:
            return cached
            
        logical_query = self.logical_query_service.get_query(logical_query_id)
        if not logical_query:
            raise ValueError(f"Logical Query {logical_query_id} not found")
            
        translator = self.factory.get_translator(dialect_name)
        
        ast = self.ast_builder.build_ast(logical_query, translator)
        optimized = self.optimizer.optimize(ast)
        
        self.cache.set(optimized)
        return optimized

    def get_query(self, query_id: str) -> Optional[DialectQuery]:
        return self.cache.get(query_id)
