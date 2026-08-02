import importlib
import pkgutil
import inspect
from typing import Dict, Type
import structlog
from app.plugins.base import DatabaseConnector
import app.plugins.connectors

logger = structlog.get_logger(__name__)

class PluginManager:
    def __init__(self):
        self._plugins: Dict[str, Type[DatabaseConnector]] = {}

    def register_plugin(self, plugin_class: Type[DatabaseConnector]):
        # We instantiate to get the name, or require name as a class attribute.
        # Here we just instantiate temporarily.
        try:
            instance = plugin_class()
            self._plugins[instance.name] = plugin_class
            logger.info("Registered database plugin", plugin=instance.name)
        except Exception as e:
            logger.error("Failed to register plugin", plugin=plugin_class.__name__, error=str(e))

    def discover_plugins(self):
        logger.info("Discovering database plugins...")
        package = app.plugins.connectors
        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            full_module_name = f"{package.__name__}.{module_name}"
            module = importlib.import_module(full_module_name)
            
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, DatabaseConnector) and obj is not DatabaseConnector:
                    self.register_plugin(obj)
                    
    def get_plugin(self, name: str) -> Type[DatabaseConnector]:
        return self._plugins.get(name)

    @property
    def plugins(self) -> Dict[str, Type[DatabaseConnector]]:
        return self._plugins
