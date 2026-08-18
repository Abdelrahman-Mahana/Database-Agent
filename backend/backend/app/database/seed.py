"""Chinook database readiness helpers.

The project uses the packaged SQLite Chinook database at ``backend/chinook.db``.
No synthetic data is generated at startup.
"""
from sqlalchemy import inspect

from app.database.db import engine

REQUIRED_CHINOOK_TABLES = {
    "Album",
    "Artist",
    "Customer",
    "Employee",
    "Genre",
    "Invoice",
    "InvoiceLine",
    "MediaType",
    "Playlist",
    "PlaylistTrack",
    "Track",
}


def seed_all():
    """Backward-compatible readiness check for the packaged Chinook database."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = sorted(REQUIRED_CHINOOK_TABLES - tables)
    if missing:
        raise RuntimeError(
            "Chinook database is missing required tables: " + ", ".join(missing)
        )
    print(f"Chinook database ready with {len(REQUIRED_CHINOOK_TABLES)} tables")


if __name__ == "__main__":
    seed_all()
