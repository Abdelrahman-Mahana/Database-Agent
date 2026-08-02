import structlog
from app.sql_validation.models import ValidationContext, ValidationResult
from app.sql_validation.interfaces import IPolicyEngine
from app.sql_validation.cache import ValidationCache
from app.sql_renderer.service import SQLRenderingService
from app.dialect.service import DialectTranslationService

logger = structlog.get_logger(__name__)

class SQLValidationService:
    def __init__(
        self,
        engine: IPolicyEngine,
        cache: ValidationCache,
        sql_renderer_service: SQLRenderingService,
        dialect_service: DialectTranslationService
    ):
        self.engine = engine
        self.cache = cache
        self.sql_renderer_service = sql_renderer_service
        self.dialect_service = dialect_service

    def validate_query(self, query_id: str, policy: str) -> ValidationResult:
        logger.info("Validating SQL Query", query_id=query_id, policy=policy)
        
        cached = self.cache.get(query_id, policy)
        if cached:
            return cached
            
        sql_doc = self.sql_renderer_service.get_document(query_id)
        if not sql_doc:
            raise ValueError(f"SQL Document {query_id} not found.")
            
        ast = self.dialect_service.get_query(query_id)
        if not ast:
            raise ValueError(f"Dialect AST {query_id} not found.")
            
        context = ValidationContext(policy=policy.upper(), query_id=query_id)
        
        result = self.engine.evaluate(sql_doc, ast, context)
        self.cache.set(query_id, policy, result)
        
        return result
