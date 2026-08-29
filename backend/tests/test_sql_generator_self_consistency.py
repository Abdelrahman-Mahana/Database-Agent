import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.orchestration.sql_generator import SQLGenerator
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.utils.helpers import normalize_sql


@pytest.fixture
def test_catalog() -> SchemaCatalog:
    return SchemaCatalog(
        fingerprint="test",
        dialect="sqlite",
        database_name="test",
        tables={
            "customers": TableProfile(
                name="customers",
                columns=[
                    ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="name", type="VARCHAR"),
                ],
                primary_key=["customer_id"],
            ),
        },
    )


@pytest.mark.asyncio
async def test_self_consistency_excludes_invalid_identifier_candidates(test_catalog):
    """Invalid identifier candidates must be skipped, not silently kept in the vote pool."""
    primary_llm = MagicMock()
    self_consistency_llm = MagicMock()
    generator = SQLGenerator(primary_llm, self_consistency_llm)

    bad_response = MagicMock()
    bad_response.content = "SELECT fake_column FROM customers"
    bad_response.response_metadata = {"token_usage": {}}

    good_response = MagicMock()
    good_response.content = "SELECT name FROM customers"
    good_response.response_metadata = {"token_usage": {}}

    generator.self_consistency_chain = MagicMock()
    generator.self_consistency_chain.ainvoke = AsyncMock(side_effect=[bad_response, good_response])

    mock_db = MagicMock()
    mock_db_ctx = MagicMock()
    mock_db_ctx.schema = {
        "customers": {"columns": [{"name": "customer_id"}, {"name": "name"}]},
    }
    mock_db_ctx.catalog = test_catalog

    with patch.object(generator.schema_service, "_get_db_fingerprint", return_value="fp"), \
         patch("app.agent.orchestration.sql_generator.get_cached_sql", return_value=(None, None)), \
         patch("app.agent.orchestration.sql_generator.set_cached_sql"), \
         patch.object(generator.schema_service, "get_database_context", return_value=mock_db_ctx), \
         patch.object(generator.validator, "validate_execution", return_value=(True, None)), \
         patch.object(generator, "last_generation_meta", create=True), \
         patch("app.agent.orchestration.sql_generator.settings") as mock_settings:

        mock_settings.enable_self_consistency = True
        mock_settings.sql_candidates = 2

        sql = await generator.generate_sql(
            question="List customer names",
            schema_text="customers(customer_id, name)",
            db=mock_db,
            use_self_consistency=True,
        )

    norm = normalize_sql(sql)
    assert "fake_column" not in norm
    assert "select name from customers" in norm


@pytest.mark.asyncio
async def test_self_consistency_excludes_invalid_join_candidates(test_catalog):
    orders_catalog = SchemaCatalog(
        fingerprint="test",
        dialect="sqlite",
        database_name="test",
        tables={
            **test_catalog.tables,
            "orders": TableProfile(
                name="orders",
                columns=[
                    ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
                ],
                primary_key=["order_id"],
                foreign_keys=[
                    {
                        "constrained_columns": ["customer_id"],
                        "referred_table": "customers",
                        "referred_columns": ["customer_id"],
                    }
                ],
            ),
            "products": TableProfile(
                name="products",
                columns=[ColumnProfile(name="product_id", type="INTEGER", primary_key=True)],
                primary_key=["product_id"],
            ),
        },
    )

    primary_llm = MagicMock()
    self_consistency_llm = MagicMock()
    generator = SQLGenerator(primary_llm, self_consistency_llm)

    bad_response = MagicMock()
    bad_response.content = (
        "SELECT customers.name FROM customers JOIN products ON customers.customer_id = products.product_id"
    )
    bad_response.response_metadata = {"token_usage": {}}

    good_response = MagicMock()
    good_response.content = "SELECT name FROM customers"
    good_response.response_metadata = {"token_usage": {}}

    generator.self_consistency_chain = MagicMock()
    generator.self_consistency_chain.ainvoke = AsyncMock(side_effect=[bad_response, good_response])

    mock_db = MagicMock()
    mock_db_ctx = MagicMock()
    mock_db_ctx.schema = {
        "customers": {"columns": [{"name": "customer_id"}, {"name": "name"}]},
        "orders": {"columns": [{"name": "order_id"}, {"name": "customer_id"}]},
        "products": {"columns": [{"name": "product_id"}]},
    }
    mock_db_ctx.catalog = orders_catalog

    with patch.object(generator.schema_service, "_get_db_fingerprint", return_value="fp"), \
         patch("app.agent.orchestration.sql_generator.get_cached_sql", return_value=(None, None)), \
         patch("app.agent.orchestration.sql_generator.set_cached_sql"), \
         patch.object(generator.schema_service, "get_database_context", return_value=mock_db_ctx), \
         patch.object(generator.validator, "validate_execution", return_value=(True, None)), \
         patch.object(generator, "last_generation_meta", create=True), \
         patch("app.agent.orchestration.sql_generator.settings") as mock_settings:

        mock_settings.enable_self_consistency = True
        mock_settings.sql_candidates = 2

        sql = await generator.generate_sql(
            question="List customer names",
            schema_text="customers, orders, products",
            db=mock_db,
            use_self_consistency=True,
        )

    norm = normalize_sql(sql)
    assert "fake_column" not in norm
    assert "select name from customers" in norm
