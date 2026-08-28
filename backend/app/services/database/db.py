import contextvars
from typing import Dict, Any, Optional
from collections import OrderedDict
import threading
import time
import structlog

logger = structlog.get_logger(__name__)

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.pool import StaticPool

from app.core.config.settings import settings

# Thread-safe context variable for multi-tenancy
current_session_id = contextvars.ContextVar("current_session_id", default="default_session")

def normalize_database_url(url: str) -> str:
    """Normalize database connection URLs to use installed SQLAlchemy drivers."""
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql+psycopg2://" + u[len("postgres://"):]
    elif u.startswith("postgresql://") and not u.startswith("postgresql+"):
        u = "postgresql+psycopg2://" + u[len("postgresql://"):]
    elif u.startswith("mysql://") and not u.startswith("mysql+"):
        u = "mysql+pymysql://" + u[len("mysql://"):]
    return u


DATABASE_URL = normalize_database_url(settings.database_url)

class EngineCache:
    def __init__(self, capacity: int = 50):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.sessionmakers = {}
        self.lock = threading.Lock()

    def get_engine(self, url: str) -> Optional[Engine]:
        with self.lock:
            if url in self.cache:
                self.cache.move_to_end(url)
                return self.cache[url]
            return None
            
    def get_sessionmaker(self, url: str) -> Optional[sessionmaker]:
        with self.lock:
            if url in self.sessionmakers:
                self.cache.move_to_end(url)
                return self.sessionmakers[url]
            return None

    def set(self, url: str, engine: Engine, sm: sessionmaker):
        with self.lock:
            if url in self.cache:
                self.cache.move_to_end(url)
            self.cache[url] = engine
            self.sessionmakers[url] = sm
            
            if len(self.cache) > self.capacity:
                oldest_url, oldest_engine = self.cache.popitem(last=False)
                if oldest_url in self.sessionmakers:
                    del self.sessionmakers[oldest_url]
                logger.info("Evicting and disposing oldest database engine from cache.")
                try:
                    oldest_engine.dispose()
                except Exception as e:
                    logger.warning(f"Error disposing engine: {e}")

    def dispose_all(self):
        """Dispose of all cached SQLAlchemy engines and close connection pools."""
        with self.lock:
            for url, engine in list(self.cache.items()):
                try:
                    engine.dispose()
                except Exception as e:
                    logger.debug("Error disposing engine for %s: %s", url, e)
            self.cache.clear()
            self.sessionmakers.clear()

    def clear(self):
        self.dispose_all()

_engine_manager = EngineCache(capacity=50)

class TTLCache:
    def __init__(self, ttl_seconds: int = 30):
        self.ttl = ttl_seconds
        self.cache = {}
        self.lock = threading.Lock()
        
    def get(self, key: str) -> Optional[str]:
        with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                else:
                    del self.cache[key]
            return None
            
    def set(self, key: str, value: str):
        with self.lock:
            self.cache[key] = (value, time.time())

    def clear(self):
        with self.lock:
            self.cache.clear()

_session_url_cache = TTLCache(ttl_seconds=30)

def reset_database_layer():
    """Cleanly reset all cached database connections, pools, and tenant session mappings."""
    _engine_manager.dispose_all()
    _session_url_cache.clear()

from app.services.database.system_store import system_store

def get_session_url(sid: str) -> str:
    cached_url = _session_url_cache.get(sid)
    if cached_url:
        return cached_url
        
    stored_url = system_store.get_session_url(sid)
    if stored_url:
        _session_url_cache.set(sid, stored_url)
        return stored_url
            
    url = normalize_database_url(settings.database_url)
    _session_url_cache.set(sid, url)
    return url

def get_engine() -> Engine:
    """Get the database engine scoped to the current HTTP request's mapped URL."""
    sid = current_session_id.get()
    
    # Map the session ID to a URL, falling back to the global default setting
    url = get_session_url(sid)
    
    # Lazily initialize and cache the engine by URL
    cached_engine = _engine_manager.get_engine(url)
    if not cached_engine:
        is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        poolclass = StaticPool if is_sqlite else None
        
        kwargs = {}
        if not is_sqlite:
            kwargs["pool_size"] = settings.db_pool_size
            kwargs["max_overflow"] = settings.db_max_overflow
            kwargs["pool_recycle"] = settings.db_pool_recycle
            kwargs["pool_timeout"] = settings.db_pool_timeout
            kwargs["pool_pre_ping"] = True
            
        new_engine = create_engine(
            url,
            connect_args=connect_args,
            poolclass=poolclass,
            echo=False,
            **kwargs
        )
        new_sm = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)
        _engine_manager.set(url, new_engine, new_sm)
        return new_engine
        
    return cached_engine

def get_sessionmaker() -> sessionmaker:
    """Get the sessionmaker scoped to the current HTTP request's mapped URL."""
    get_engine()  # Ensure the engine and sessionmaker are initialized
    sid = current_session_id.get()
    url = get_session_url(sid)
    return _engine_manager.get_sessionmaker(url)

Base = declarative_base()

def get_db():
    """Yield a database session bound to the current request's tenant/engine."""
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def set_database_url(new_url: str):
    """Reconfigure database connection URL dynamically for the current session."""
    sid = current_session_id.get()
    normalized_url = normalize_database_url(new_url)
    
    # Store the mapping from session -> URL in local system store
    system_store.set_session_url(sid, normalized_url)
            
    # Update local TTL cache immediately to ensure consistency on this worker
    _session_url_cache.set(sid, normalized_url)
    
    # Return the engine to validate/initialize
    engine = get_engine()
    
    # Validate connection by attempting a connect
    with engine.connect() as conn:
        pass
        
    return engine


