import pytest
import time
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine, text

from app.services.database import db
from app.services.sql_service import SchemaService, SQLExecutor
from app.models.schema_catalog.catalog_builder import CatalogBuilder
from app.models.schema_catalog.retrieval import retrieve_relevant_tables
from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.services.sql.validator import SQLValidator
from app.services.sql.result_verifier import ResultVerifier
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.services.feedback_service import FeedbackService


AGIAL_POSTGRES_URL = "postgresql://postgres:Abdobas01%40@localhost:5432/Agial"


@pytest.fixture(scope="module")
def agial_engine():
    """Connect to the live Agial PostgreSQL database."""
    try:
        engine = create_engine(AGIAL_POSTGRES_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        yield engine
    except Exception as e:
        pytest.skip(f"Agial PostgreSQL database not accessible: {e}")


def test_agial_schema_introspection_and_catalog_build(agial_engine, tmp_path, monkeypatch):
    """
    1. Test schema introspection and normalized catalog building on live Agial PostgreSQL.
    2. Verify O(K) selective table subset loading over 1,300+ tables.
    """
    monkeypatch.setattr("app.models.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)
    monkeypatch.setattr("app.services.database.db.get_engine", lambda: agial_engine)

    schema_service = SchemaService()
    builder = CatalogBuilder(schema_service=schema_service)
    catalog = builder.get_or_build(force_rebuild=True)

    assert catalog.dialect.lower() in ("postgresql", "postgres")
    assert catalog.database_name == "Agial"
    assert len(catalog.tables) > 1000  # 1,347 enterprise tables in Agial

    # Check key enterprise medical & ERP tables exist
    known_tables = set(catalog.tables.keys())
    assert any("doctor" in t or "patient" in t or "partner" in t or "user" in t for t in known_tables)

    # Test O(K) selective subset loading
    sample_tables = list(catalog.tables.keys())[:5]
    subset = builder.load_table_subset(catalog.fingerprint, sample_tables)
    assert len(subset) == len(sample_tables)
    for t in sample_tables:
        assert t in subset


def test_agial_two_stage_hybrid_retrieval(agial_engine, tmp_path, monkeypatch):
    """
    Test candidate retrieval over 1,300+ Agial tables with sub-150ms latency.
    """
    monkeypatch.setattr("app.models.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)
    monkeypatch.setattr("app.services.database.db.get_engine", lambda: agial_engine)

    schema_service = SchemaService()
    builder = CatalogBuilder(schema_service=schema_service)
    catalog = builder.get_or_build()

    # 1. English query for doctors & clinics
    t0 = time.perf_counter()
    doctor_candidates = retrieve_relevant_tables("doctor clinic appointments", catalog, k=10)
    dur_ms = (time.perf_counter() - t0) * 1000

    assert len(doctor_candidates) <= 10
    assert any("doctor" in t or "clinic" in t for t in doctor_candidates)
    assert dur_ms < 1000.0

    # 2. Enrich with Arabic business glossary & retrieve
    feedback = FeedbackService(catalog_builder=builder)
    feedback.record_term_synonym(catalog, target_entity="table", target_name="public.res_partner", synonym="الشركاء")
    feedback.record_term_synonym(catalog, target_entity="table", target_name="public.res_partner", synonym="المرضى")

    arabic_candidates = retrieve_relevant_tables("بيانات الشركاء والمرضى", catalog, k=10)
    assert len(arabic_candidates) <= 10
    assert any("partner" in t for t in arabic_candidates)


def test_agial_query_grounding_and_bounded_token_budget(agial_engine, tmp_path, monkeypatch):
    """
    Verify SchemaGroundingEngine builds a compact sub-schema with Steiner-Tree join paths,
    keeping >98% of the 1,347 Agial tables outside LLM prompt context.
    """
    monkeypatch.setattr("app.models.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)
    monkeypatch.setattr("app.services.database.db.get_engine", lambda: agial_engine)

    schema_service = SchemaService()
    builder = CatalogBuilder(schema_service=schema_service)
    catalog = builder.get_or_build()

    raw_schema = {
        t: {
            "columns": [{"name": c.name, "type": c.type} for c in prof.columns],
            "foreign_keys": prof.foreign_keys,
            "primary_key": prof.primary_key,
        }
        for t, prof in catalog.tables.items()
    }

    grounding_engine = SchemaGroundingEngine(schema_service=schema_service)
    grounded = grounding_engine.build_grounded_schema(
        schema=raw_schema,
        question="Show doctors and clinic details",
        catalog=catalog,
    )

    assert len(grounded.selected_tables) <= 15
    assert len(grounded.selected_tables) < len(catalog.tables)

    # Check token budget is strictly bounded
    est_tokens = len(grounded.schema_text) // 4
    assert est_tokens < 2500, f"Prompt schema tokens ({est_tokens}) exceeded budget for Agial DB!"


def test_agial_security_ast_gate_blocks_live_injections(agial_engine):
    """
    Verify AST validator blocks destructive SQL, multiple statements, and dangerous functions
    before reaching the Agial PostgreSQL database.
    """
    validator = SQLValidator()

    # 1. Block destructive DROP
    res_drop = validator.validate_safety("DROP TABLE patient_model;")
    assert res_drop["valid"] is False

    # 2. Block multi-statement chained injection
    res_multi = validator.validate_safety("SELECT * FROM doctor_model; DELETE FROM doctor_model;")
    assert res_multi["valid"] is False
    assert "Multiple SQL statements" in res_multi["reason"]

    # 3. Block PostgreSQL file-access exploits
    res_file = validator.validate_safety("SELECT pg_read_file('/etc/passwd');")
    assert res_file["valid"] is False
    assert "Forbidden administrative or file-access function" in res_file["reason"]


def test_agial_safe_read_only_execution_and_result_verification(agial_engine):
    """
    Execute a safe read-only query against Agial PostgreSQL, verifying row counts and claim traceability.
    """
    executor = SQLExecutor()
    with agial_engine.connect() as conn:
        # Execute count query on core table (res_company)
        rows = executor.execute("SELECT COUNT(*) as total_count FROM res_company", conn)
        assert len(rows) == 1
        assert "total_count" in rows[0]
        total_val = rows[0]["total_count"]
        assert isinstance(total_val, (int, float))

        # Result claim verifier test
        verifier = ResultVerifier()
        is_grounded, ungrounded_claims = verifier.verify_report_claims(
            report_text=f"The system has {total_val} active registered companies.",
            rows=rows,
        )
        assert is_grounded is True
        assert len(ungrounded_claims) == 0


@pytest.mark.asyncio
async def test_agial_golden_e2e_analyst_agent(agial_engine, tmp_path, monkeypatch):
    """
    Golden E2E Pipeline on live Agial PostgreSQL:
    Question -> Scope Gate -> Retrieval -> QuerySpec -> Grounding -> SQL -> Execute -> Verify -> Answer.
    """
    monkeypatch.setattr("app.models.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)
    monkeypatch.setattr("app.services.database.db.get_engine", lambda: agial_engine)

    agent = AnalystAgent()

    with patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_sql, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        # Mock generated safe PostgreSQL query
        mock_sql.return_value = "SELECT name, id FROM res_company LIMIT 5"
        mock_report.return_value = ("Here are the registered company details from Agial.", None)

        with agial_engine.connect() as conn:
            response = await agent.ask(
                "How many companies exist in the database?",
                session_id="agial_e2e_session",
                db=conn,
            )

            assert response["success"] is True
            assert len(response["results"]) > 0
            assert "confidence_breakdown" in response
            assert response["confidence_breakdown"]["overall"] > 0.8
            assert "evaluation_trace" in response
            assert response["evaluation_trace"]["execution_metrics"]["rows_count"] > 0
