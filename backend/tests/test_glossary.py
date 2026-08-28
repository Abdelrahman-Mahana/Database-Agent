import pytest
from app.models.schema_catalog.glossary import _extract_json, build_glossary
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


def test_extract_json_markdown_fence():
    raw = """Here is the glossary:
```json
{
  "tables": {
    "users": {"description": "User accounts", "synonyms": ["accounts", "members"]}
  },
  "columns": {
    "users.id": {"description": "User ID", "synonyms": ["uid"]}
  }
}
```
Hope this helps!"""
    res = _extract_json(raw)
    assert res is not None
    assert "users" in res["tables"]
    assert "users.id" in res["columns"]


def test_extract_json_with_think_tags():
    raw = """<think>
Let me analyze the tables and columns.
Users has id and email.
</think>
{
  "tables": {
    "users": {"description": "User accounts", "synonyms": ["users"]}
  },
  "columns": {}
}"""
    res = _extract_json(raw)
    assert res is not None
    assert "users" in res["tables"]


def test_extract_json_trailing_commas():
    raw = """{
  "tables": {
    "users": {"description": "User accounts", "synonyms": ["users", ], },
  },
  "columns": {},
}"""
    res = _extract_json(raw)
    assert res is not None
    assert "users" in res["tables"]


def test_extract_json_invalid():
    assert _extract_json("Just plain text with no json") is None
    assert _extract_json("") is None
    assert _extract_json(None) is None


@pytest.mark.asyncio
async def test_build_glossary_with_mock_llm():
    catalog = SchemaCatalog(
        fingerprint="fp_mock",
        dialect="sqlite",
        database_name="TestDB",
        tables={
            "orders": TableProfile(
                name="orders",
                columns=[ColumnProfile(name="id", type="INTEGER"), ColumnProfile(name="amount", type="REAL")],
            )
        },
    )

    class MockLLM:
        async def generate(self, prompt: str, temperature: float = 0.0) -> str:
            return """```json
{
  "tables": {
    "orders": {"description": "Customer purchase orders", "synonyms": ["sales", "transactions"]}
  },
  "columns": {
    "orders.amount": {"description": "Total order amount in USD", "synonyms": ["price", "cost"]}
  }
}
```"""

    glossary = await build_glossary(catalog, MockLLM())
    assert "orders" in glossary["tables"]
    assert glossary["tables"]["orders"]["description"] == "Customer purchase orders"
    assert "orders.amount" in glossary["columns"]
    assert "price" in glossary["columns"]["orders.amount"]["synonyms"]
