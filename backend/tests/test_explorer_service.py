"""Tests for Database Explorer and Connection Manager services."""
import pytest
from app.services.connection_manager import ConnectionManager
from app.services.sql_service import SchemaService


def test_connection_manager_build_urls():
    cm = ConnectionManager()

    # PostgreSQL URL
    pg_url = cm.build_connection_url("postgresql", host="db.example.com", port=5432, database="mydb", username="admin", password="secretpassword", ssl_enabled=True, ssl_mode="require")
    assert "postgresql://admin:secretpassword@db.example.com:5432/mydb?sslmode=require" == pg_url

    # MySQL URL
    mysql_url = cm.build_connection_url("mysql", host="localhost", port=3306, database="testdb", username="root", password="pass", ssl_enabled=True)
    assert "mysql+pymysql://root:pass@localhost:3306/testdb?ssl=true" == mysql_url

    # SQLite URL
    sqlite_url = cm.build_connection_url("sqlite", file_path="sample.db")
    assert "sqlite:///sample.db" == sqlite_url

    # MongoDB URL
    mongo_url = cm.build_connection_url("mongodb", host="localhost", port=27017, database="analytics", ssl_enabled=True)
    assert "mongodb://localhost:27017/analytics?tls=true" == mongo_url


def test_connection_manager_masking_and_encryption(tmp_path):
    storage_file = tmp_path / "profiles.json"
    cm = ConnectionManager(storage_path=storage_file)

    raw_url = "postgresql://dbuser:supersecretpass@127.0.0.1:5432/proddb"
    masked = cm.mask_connection_url(raw_url)
    assert "supersecretpass" not in masked
    assert "postgresql://dbuser:••••••••@127.0.0.1:5432/proddb" == masked

    # Save profile with Fernet encryption
    profile = cm.save_profile("postgresql", "Production Analytics DB", raw_url)
    assert profile.connection_id is not None
    assert profile.display_name == "Production Analytics DB"

    # Decrypt profile
    decrypted_url = cm.get_profile_url(profile.connection_id)
    assert decrypted_url == raw_url

    # List saved profiles
    profiles_list = cm.list_saved_profiles()
    assert len(profiles_list) == 1
    assert profiles_list[0]["display_name"] == "Production Analytics DB"
    assert "supersecretpass" not in profiles_list[0]["masked_url"]


def test_schema_service_explorer_hierarchy():
    schema_service = SchemaService()
    explorer_data = schema_service.get_explorer_data()

    assert "tables" in explorer_data
    assert "views" in explorer_data
    assert "schema_tree" in explorer_data
    assert "summary" in explorer_data

    summary = explorer_data["summary"]
    assert "objects" in summary
    assert "columns" in summary

    # Verify hierarchy tree structure
    tree = explorer_data["schema_tree"]
    assert len(tree) > 0
    root = tree[0]
    assert root["kind"] == "catalog"
    assert "children" in root
