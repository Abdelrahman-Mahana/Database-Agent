"""Show the configured database and verify that Chinook is readable."""
import os
import sys
from sqlalchemy import inspect, text

# Add parent directory (backend) to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.db import get_engine

def reset():
    engine = get_engine()
    print(f"Configured database: {engine.url.render_as_string(hide_password=True)}")
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print("Available tables:")
    for table_name in tables:
        print(f"- {table_name}")
    print("Database is ready.")

if __name__ == "__main__":
    reset()
