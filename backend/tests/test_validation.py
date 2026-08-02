import pytest
from app.utils.validator import validate_sql, transpile_sql_to_dialect


def test_valid_queries():
    valid_queries = [
        "SELECT * FROM Artist;",
        "SELECT Name, COUNT(AlbumId) FROM Artist a JOIN Album al ON a.ArtistId = al.ArtistId GROUP BY Name;",
        "WITH sales AS (SELECT * FROM Invoice) SELECT * FROM sales;",
        "SELECT * FROM Track UNION SELECT * FROM Album;",
    ]
    for q in valid_queries:
        res = validate_sql(q)
        assert res["valid"], f"Query should be valid: {q}. Reason: {res.get('reason')}"


def test_unsafe_queries_blocked():
    unsafe_queries = [
        "DROP TABLE Artist;",
        "DELETE FROM Artist WHERE ArtistId = 1;",
        "INSERT INTO Artist (Name) VALUES ('New Artist');",
        "UPDATE Artist SET Name = 'New Name' WHERE ArtistId = 1;",
        "CREATE TABLE NewTable (id INT);",
        "ALTER TABLE Artist ADD COLUMN Test INT;",
        "TRUNCATE TABLE Artist;",
        "PRAGMA journal_mode=WAL;",
        "ATTACH DATABASE 'test.db' AS test;",
    ]
    for q in unsafe_queries:
        res = validate_sql(q)
        assert not res["valid"], f"Query should be blocked: {q}"
        assert res["query_type"] in ("unsafe", "invalid")


def test_syntax_error_blocked():
    syntax_error_queries = [
        "SELECT FROM WHERE;",
        "SELECT * FROM (SELECT * FROM Artist",  # Unclosed parenthesis
    ]
    for q in syntax_error_queries:
        res = validate_sql(q)
        assert not res["valid"], f"Syntax error query should be blocked: {q}"
        assert res["query_type"] == "invalid"
        assert "syntax error" in res["reason"].lower()


def test_dialect_transpilation():
    pg_concatenation = "SELECT CONCAT(FirstName, ' ', LastName) FROM Customer;"
    sqlite_result = transpile_sql_to_dialect(pg_concatenation, "sqlite")
    assert "||" in sqlite_result, f"Transpiled query should use SQLite concatenation operator, got: {sqlite_result}"
