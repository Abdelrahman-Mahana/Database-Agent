"""Show the configured database and verify that Chinook is readable."""
import os
import sys
from sqlalchemy import text

# Add parent directory (backend) to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.db import DATABASE_URL, engine

def reset():
    print(f"Configured database: {DATABASE_URL}")
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ).fetchall()
    print("Available tables:")
    for (table_name,) in tables:
        print(f"- {table_name}")
    print("Chinook database is ready.")

if __name__ == "__main__":
    reset()
