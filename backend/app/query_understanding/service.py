import structlog
from app.query_understanding.models import QueryUnderstanding
from app.query_understanding.interfaces import (
    IQueryNormalizer, IIntentClassifier, IEntityExtractor, 
    IMetricDetector, IDimensionDetector, IFilterExtractor, 
    ITimeParser, IAmbiguityDetector, IContextBuilder, 
    IRouter, IConfidenceScorer
)
from app.query_understanding.cache import QueryUnderstandingCache
from app.query_understanding.utils import generate_query_hash
from app.database.discovery.service import DiscoveryService
from app.database.intelligence.service import SchemaIntelligenceService
from app.database.profiling.service import DataProfilingService

logger = structlog.get_logger(__name__)

class QueryUnderstandingService:
    def __init__(
        self,
        normalizer: IQueryNormalizer,
        intent_classifier: IIntentClassifier,
        entity_extractor: IEntityExtractor,
        metric_detector: IMetricDetector,
        dimension_detector: IDimensionDetector,
        filter_extractor: IFilterExtractor,
        time_parser: ITimeParser,
        ambiguity_detector: IAmbiguityDetector,
        context_builder: IContextBuilder,
        router: IRouter,
        confidence_scorer: IConfidenceScorer,
        cache: QueryUnderstandingCache,
        discovery_service: DiscoveryService,
        intelligence_service: SchemaIntelligenceService,
        profiling_service: DataProfilingService
    ):
        self.normalizer = normalizer
        self.intent_classifier = intent_classifier
        self.entity_extractor = entity_extractor
        self.metric_detector = metric_detector
        self.dimension_detector = dimension_detector
        self.filter_extractor = filter_extractor
        self.time_parser = time_parser
        self.ambiguity_detector = ambiguity_detector
        self.context_builder = context_builder
        self.router = router
        self.confidence_scorer = confidence_scorer
        self.cache = cache
        
        self.discovery_service = discovery_service
        self.intelligence_service = intelligence_service
        self.profiling_service = profiling_service

    async def understand(self, plugin_name: str, query: str) -> QueryUnderstanding:
        logger.info("Understanding query", plugin=plugin_name, query=query)
        
        query_hash = generate_query_hash(plugin_name, query)
        cached = self.cache.get(query_hash)
        if cached:
            return cached
            
        metadata = self.discovery_service.get_metadata()
        if not metadata:
            metadata = await self.discovery_service.discover(plugin_name)
            
        intelligence = self.intelligence_service.get_intelligence(plugin_name)
        if not intelligence:
            intelligence = await self.intelligence_service.build_intelligence(plugin_name)
            
        profile = self.profiling_service.get_profile(plugin_name)
        
        # 1. Normalize
        normalized_query = self.normalizer.normalize(query)
        
        # 2. Intent
        intent = self.intent_classifier.classify(normalized_query)
        
        # 3. Entities
        entities = self.entity_extractor.extract(normalized_query, metadata)
        
        # 4. Metrics & Dimensions
        metrics = self.metric_detector.detect(entities, metadata, intelligence)
        dimensions = self.dimension_detector.detect(entities, metadata, intelligence)
        
        # 5. Filters & Time
        filters = self.filter_extractor.extract(normalized_query, entities, metadata)
        time_range = self.time_parser.parse(entities.time_expressions)
        
        # 6. Ambiguity
        ambiguities = self.ambiguity_detector.detect(normalized_query, entities, metrics, dimensions, metadata)
        
        # 7. Context Builder
        context = self.context_builder.build(entities, metrics, dimensions, metadata, intelligence, profile)
        
        # 8. Route & Confidence
        routing = self.router.route(intent, entities)
        confidence = self.confidence_scorer.score(intent, entities, ambiguities)
        
        result = QueryUnderstanding(
            original_query=query,
            normalized_query=normalized_query,
            intent=intent,
            entities=entities,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            time_range=time_range,
            ambiguities=ambiguities,
            context=context,
            routing=routing,
            confidence=confidence
        )
        
        self.cache.set(query_hash, result)
        return result

    def normalize_only(self, query: str) -> str:
        return self.normalizer.normalize(query)
