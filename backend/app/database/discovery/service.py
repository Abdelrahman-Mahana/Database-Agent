from typing import Optional
import structlog

from app.plugins.manager import PluginManager
from app.database.discovery.cache import DiscoveryCache
from app.database.discovery.models import DatabaseMetadata

logger = structlog.get_logger(__name__)

class DiscoveryService:
    def __init__(self, plugin_manager: PluginManager, cache: DiscoveryCache):
        self.plugin_manager = plugin_manager
        self.cache = cache

    async def discover(self, plugin_name: str) -> DatabaseMetadata:
        """
        Runs discovery on the specified plugin and caches the result.
        """
        logger.info("Starting database discovery", plugin=plugin_name)
        plugin_class = self.plugin_manager.get_plugin(plugin_name)
        
        if not plugin_class:
            raise ValueError(f"Plugin {plugin_name} not found")
            
        # The connector will use InspectorFactory internally to do the inspection
        plugin_instance = plugin_class()
        
        try:
            metadata = await plugin_instance.discover()
            self.cache.set(metadata)
            logger.info("Discovery complete", plugin=plugin_name, schemas_count=len(metadata.schemas))
            return metadata
        except Exception as e:
            logger.error("Discovery failed", plugin=plugin_name, error=str(e))
            raise

    def get_metadata(self) -> Optional[DatabaseMetadata]:
        return self.cache.get()

    async def refresh(self, plugin_name: str) -> DatabaseMetadata:
        self.cache.clear()
        return await self.discover(plugin_name)
