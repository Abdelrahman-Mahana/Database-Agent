"""ORM models are intentionally not hardcoded.

The analyst reads the active database schema at runtime with SQLAlchemy
Inspector, which lets the app work with Chinook now and other SQLite or
PostgreSQL databases later.
"""
