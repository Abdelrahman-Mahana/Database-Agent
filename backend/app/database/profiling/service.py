from typing import Optional
import structlog
from app.database.discovery.service import DiscoveryService
from app.database.profiling.cache import ProfilingCache
from app.database.profiling.statistics_collector import StatisticsCollector
from app.database.profiling.models import DatabaseProfile

logger = structlog.get_logger(__name__)

class DataProfilingService:
    def __init__(
        self,
        discovery_service: DiscoveryService,
        collector: StatisticsCollector,
        cache: ProfilingCache
    ):
        self.discovery_service = discovery_service
        self.collector = collector
        self.cache = cache

    async def build_profile(self, plugin_name: str) -> DatabaseProfile:
        logger.info("Building data profile", plugin=plugin_name)
        
        metadata = self.discovery_service.get_metadata()
        if not metadata:
            metadata = await self.discovery_service.discover(plugin_name)
            
        connector = self.discovery_service.plugin_manager.get_connector(plugin_name)
        if not connector:
            raise ValueError(f"Plugin {plugin_name} not found")
            
        try:
            # Assuming get_engine() is implemented, or we fallback to dummy
            engine = connector.get_engine()
            get_sample_query_func = connector.build_sample_query
        except AttributeError:
            from sqlalchemy import create_engine
            engine = create_engine("sqlite:///:memory:")
            # Dummy fallback for build_sample_query
            get_sample_query_func = lambda s, t, sc, st, sz, **kwargs: f"SELECT {sc} FROM {s}.{t}"
            logger.warning("Connector does not implement get_engine or build_sample_query. Using dummy fallback.")
            
        profile = await self.collector.profile_database(metadata, engine, plugin_name, get_sample_query_func)
        self.cache.set(plugin_name, profile)
        return profile

    def get_profile(self, plugin_name: str) -> Optional[DatabaseProfile]:
        return self.cache.get(plugin_name)

    async def refresh_profile(self, plugin_name: str) -> DatabaseProfile:
        self.cache.clear(plugin_name)
        return await self.build_profile(plugin_name)
