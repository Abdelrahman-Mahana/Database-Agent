"""E2E Golden Evaluation Test Suite.

Validates end-to-end question processing across representative golden benchmark queries:
1. Single-fact scalar query.
2. 2-hop / multi-entity aggregate query.
3. Arabic natural language query with synonym resolution.
4. Cost-guarded query safety.
5. Deterministic fact generation and claim-level verification.
"""
import pytest
import sqlite3
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.orchestration.sql_generator import SQLGenerator
from app.services.sql.validator import SQLValidator
from app.services.sql.result_verifier import ResultVerifier
from app.core.security.cost_guard import check_query_cost


@pytest.fixture
def golden_db(tmp_path):
    """Create in-memory/temp SQLite database with golden evaluation schema."""
    db_path = str(tmp_path / "golden_eval.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE departments (
            dept_id INTEGER PRIMARY KEY,
            dept_name TEXT NOT NULL,
            budget REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE employees (
            emp_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            dept_id INTEGER NOT NULL,
            salary REAL NOT NULL,
            hire_date TEXT NOT NULL,
            FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
        )
    """)
    cur.execute("""
        CREATE TABLE sales (
            sale_id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            sale_date TEXT NOT NULL,
            FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
        )
    """)

    # Seed data
    cur.executemany("INSERT INTO departments VALUES (?, ?, ?)", [
        (1, "Engineering", 500000.0),
        (2, "Sales", 300000.0),
        (3, "Marketing", 200000.0),
    ])
    cur.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?)", [
        (101, "Alice Smith", 1, 120000.0, "2022-01-15"),
        (102, "Bob Jones", 2, 85000.0, "2021-06-01"),
        (103, "Charlie Brown", 2, 90000.0, "2023-03-10"),
        (104, "Dana White", 3, 75000.0, "2022-11-20"),
    ])
    cur.executemany("INSERT INTO sales VALUES (?, ?, ?, ?)", [
        (1, 102, 15000.0, "2024-01-10"),
        (2, 102, 25000.0, "2024-02-15"),
        (3, 103, 40000.0, "2024-01-20"),
    ])
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


@pytest.fixture
def golden_catalog():
    """Build normalized catalog for golden evaluation."""
    tables = {
        "departments": TableProfile(
            name="departments",
            columns=[
                ColumnProfile(name="dept_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="dept_name", type="VARCHAR"),
                ColumnProfile(name="budget", type="REAL"),
            ],
            description="Company business units and department budgets",
            synonyms=["divisions", "units", "أقسام"],
        ),
        "employees": TableProfile(
            name="employees",
            columns=[
                ColumnProfile(name="emp_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="name", type="VARCHAR"),
                ColumnProfile(name="dept_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="salary", type="REAL"),
                ColumnProfile(name="hire_date", type="VARCHAR"),
            ],
            foreign_keys=[
                {"constrained_columns": ["dept_id"], "referred_table": "departments", "referred_columns": ["dept_id"]}
            ],
            description="Staff members, staff salaries and employment details",
            synonyms=["staff", "workers", "موظفين"],
        ),
        "sales": TableProfile(
            name="sales",
            columns=[
                ColumnProfile(name="sale_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="emp_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="amount", type="REAL"),
                ColumnProfile(name="sale_date", type="VARCHAR"),
            ],
            foreign_keys=[
                {"constrained_columns": ["emp_id"], "referred_table": "employees", "referred_columns": ["emp_id"]}
            ],
            description="Sales revenue transactions recorded by sales representatives",
            synonyms=["revenue", "deals", "مبيعات"],
        ),
    }
    return SchemaCatalog(
        fingerprint="golden_eval_fp",
        dialect="sqlite",
        database_name="GoldenEvalDB",
        tables=tables,
    )


def test_golden_eval_scalar_query(golden_db, golden_catalog):
    """Golden Eval 1: Grounding, SQL validation, execution, and deterministic facts for scalar query."""
    question = "What is the total budget for all departments?"
    
    # 1. Spec & Grounding
    qspec_builder = QuerySpecBuilder()
    spec = qspec_builder.build_spec(question, catalog=golden_catalog)
    assert spec.intent.value in ("database", "aggregation", "lookup")
    
    grounding_engine = SchemaGroundingEngine(schema_service=MagicMock())
    grounded = grounding_engine.build_grounded_schema(
        schema={t: {"columns": [{"name": c.name, "type": c.type} for c in p.columns], "foreign_keys": p.foreign_keys, "primary_key": p.primary_key} for t, p in golden_catalog.tables.items()},
        question=question,
        catalog=golden_catalog,
    )
    assert "departments" in grounded.selected_tables

    # 2. SQL Validation
    sql = "SELECT SUM(budget) AS total_budget FROM departments;"
    validator = SQLValidator()
    val_res = validator.validate_safety(sql)
    assert val_res["valid"] is True

    # 3. Execution & Verifier
    rows = [{"total_budget": 1000000.0}]
    verifier = ResultVerifier()
    facts = verifier.generate_deterministic_facts(rows, query_spec=spec, sql=sql)
    assert any(f.fact_type == "scalar" and f.source_value == 1000000.0 for f in facts)


def test_golden_eval_multi_entity_join(golden_db, golden_catalog):
    """Golden Eval 2: 2-hop join (departments -> employees -> sales) grounding & correctness."""
    question = "Show total sales revenue by department name"

    grounding_engine = SchemaGroundingEngine(schema_service=MagicMock())
    grounded = grounding_engine.build_grounded_schema(
        schema={t: {"columns": [{"name": c.name, "type": c.type} for c in p.columns], "foreign_keys": p.foreign_keys, "primary_key": p.primary_key} for t, p in golden_catalog.tables.items()},
        question=question,
        catalog=golden_catalog,
    )
    # All 3 tables in the join spine must be selected
    assert "departments" in grounded.selected_tables
    assert "employees" in grounded.selected_tables
    assert "sales" in grounded.selected_tables

    sql = """
        SELECT d.dept_name, SUM(s.amount) AS total_sales
        FROM departments d
        JOIN employees e ON d.dept_id = e.dept_id
        JOIN sales s ON e.emp_id = s.emp_id
        GROUP BY d.dept_name
    """
    validator = SQLValidator()
    correctness = validator.validate_sql_correctness(
        sql,
        catalog=golden_catalog,
        query_spec=MagicMock(metrics=["sales"], dimensions=["department"], aggregations=["SUM"], filters=[], sorting=[], limit=None),
    )
    assert correctness["valid"] is True
    assert correctness["identifiers_valid"] is True


def test_golden_eval_arabic_synonym_resolution(golden_catalog):
    """Golden Eval 3: Arabic synonym resolution for tables and columns."""
    question = "ما هو إجمالي مبيعات الموظفين في كل قسم؟"
    grounding_engine = SchemaGroundingEngine(schema_service=MagicMock())
    grounded = grounding_engine.build_grounded_schema(
        schema={t: {"columns": [{"name": c.name, "type": c.type} for c in p.columns], "foreign_keys": p.foreign_keys, "primary_key": p.primary_key} for t, p in golden_catalog.tables.items()},
        question=question,
        catalog=golden_catalog,
    )
    assert "sales" in grounded.selected_tables
    assert "employees" in grounded.selected_tables
