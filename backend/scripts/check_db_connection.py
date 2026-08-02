"""Show the configured database and verify it is readable.

Run from anywhere: `python backend/scripts/check_db_connection.py`
"""
import os
import sys
from sqlalchemy import text

# This script now lives in backend/scripts/, so go up one extra level to
# reach backend/ (the actual project root that `app` is importable from).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.db import DATABASE_URL, engine

def check_connection():
    print(f"Configured database: {DATABASE_URL}")
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ).fetchall()
    print("Available tables:")
    for (table_name,) in tables:
        print(f"- {table_name}")
    print("Database connection is healthy.")

if __name__ == "__main__":
    check_connection()
