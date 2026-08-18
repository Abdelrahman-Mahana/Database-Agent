"""Show the configured database and verify it is readable.

Run from anywhere: `python backend/scripts/check_db_connection.py`
"""
import os
import sys
from sqlalchemy import inspect, text

# This script now lives in backend/scripts/, so go up one extra level to
# reach backend/ (the actual project root that `app` is importable from).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.db import get_engine

def check_connection():
    engine = get_engine()
    # SQLAlchemy masks passwords when rendered, unlike the raw setting.
    print(f"Configured database: {engine.url.render_as_string(hide_password=True)}")
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    tables = inspect(engine).get_table_names()
    print("Available tables:")
    for table_name in tables:
        print(f"- {table_name}")
    print("Database connection is healthy.")

if __name__ == "__main__":
    check_connection()
