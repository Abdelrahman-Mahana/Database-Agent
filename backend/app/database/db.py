"""Database engine and session setup."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from app.core.config import settings

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

is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
poolclass = StaticPool if is_sqlite else None

kwargs = {}
if not is_sqlite:
    kwargs["pool_size"] = settings.db_pool_size
    kwargs["max_overflow"] = settings.db_max_overflow
    kwargs["pool_pre_ping"] = True

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    poolclass=poolclass,
    echo=False,
    **kwargs
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Yield a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_database_url(new_url: str):
    """Reconfigure database connection URL dynamically and update engine."""
    global engine, SessionLocal, DATABASE_URL
    normalized_url = normalize_database_url(new_url)
    is_sqlite = normalized_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    poolclass = StaticPool if is_sqlite else None
    kwargs = {}
    if not is_sqlite:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_pre_ping"] = True

    new_engine = create_engine(
        normalized_url,
        connect_args=connect_args,
        poolclass=poolclass,
        echo=False,
        **kwargs
    )

    # Validate connection by attempting a connect
    with new_engine.connect() as conn:
        pass

    engine = new_engine
    DATABASE_URL = normalized_url
    SessionLocal.configure(bind=engine)
    return engine

