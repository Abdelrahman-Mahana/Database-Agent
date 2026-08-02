from typing import Optional, Dict
from datetime import datetime, timezone
import structlog
from app.database.discovery.service import DiscoveryService
from app.database.intelligence.models import SchemaIntelligence
from app.database.intelligence.interfaces import (
    IRelationshipDetector, ISemanticClassifier, ITableClassifier,
    IBusinessDomainDetector, IGraphBuilder
)

logger = structlog.get_logger(__name__)

class SchemaIntelligenceService:
    def __init__(
        self,
        discovery_service: DiscoveryService,
        relationship_detector: IRelationshipDetector,
        semantic_classifier: ISemanticClassifier,
        table_classifier: ITableClassifier,
        domain_detector: IBusinessDomainDetector,
        graph_builder: IGraphBuilder
    ):
        self.discovery_service = discovery_service
        self.relationship_detector = relationship_detector
        self.semantic_classifier = semantic_classifier
        self.table_classifier = table_classifier
        self.domain_detector = domain_detector
        self.graph_builder = graph_builder
        
        self._cache: Dict[str, SchemaIntelligence] = {}

    async def build_intelligence(self, plugin_name: str) -> SchemaIntelligence:
        logger.info("Building schema intelligence", plugin=plugin_name)
        
        metadata = self.discovery_service.get_metadata()
        if not metadata:
            metadata = await self.discovery_service.discover(plugin_name)
            
        # Detect augmented relationships
        all_relationships = self.relationship_detector.detect(metadata)
        
        # Build graph
        graph = self.graph_builder.build(metadata, all_relationships)
        
        all_tables = []
        for schema in metadata.schemas:
            all_tables.extend(schema.tables)
            all_tables.extend(schema.views)
            all_tables.extend(schema.materialized_views)
            
        # Detect domains
        domains = self.domain_detector.detect(all_tables)
        
        # Classify tables and columns
        table_classifications = []
        for table in all_tables:
            tbl_class = self.table_classifier.classify_table(table)
            for col in table.columns:
                col_sem = self.semantic_classifier.classify_column(col)
                tbl_class.columns.append(col_sem)
            table_classifications.append(tbl_class)
            
        intelligence = SchemaIntelligence(
            database_name=metadata.name,
            relationship_graph=graph,
            tables=table_classifications,
            business_domains=domains,
            generated_at=datetime.now(timezone.utc)
        )
        
        self._cache[plugin_name] = intelligence
        logger.info("Intelligence build complete", plugin=plugin_name)
        return intelligence

    def get_intelligence(self, plugin_name: str) -> Optional[SchemaIntelligence]:
        return self._cache.get(plugin_name)

    def clear(self, plugin_name: Optional[str] = None):
        if plugin_name:
            self._cache.pop(plugin_name, None)
        else:
            self._cache.clear()
