"""Golden evaluation dataset (Phase 0 of the rebuild plan).

Every entry is a bilingual (Arabic/English) natural-language question paired
with what a *correct* deterministic understanding of it should look like —
independent of which LLM is behind the agent. This lets us measure the
non-LLM layers (semantic parsing, schema grounding, analysis-type
classification) for free, on every commit, without spending a single token.

`expected_tables`: the minimum set of tables that MUST appear in the grounded
schema for the generated SQL to even be possible. Extra tables pulled in via
FK-neighborhood expansion are fine (that's by design); missing an expected
table is a hard failure — the SQL generator would have no shot at answering
correctly with an incomplete schema.

`expected_analysis_type`: what `classify_analysis_type()` should return.
Wrong classification silently costs money: an AGGREGATION being misread as
MULTI_STEP triggers the Planner (2-3x the LLM calls) for no reason; a
COMPARISON misread as LOOKUP skips report verification and risks a
half-synthesized answer.

Two schemas are covered because a plan/eval built against a single schema
tends to overfit to that schema's exact table/column names.
"""

CHINOOK_CASES = [
    dict(
        q="How many customers are there?",
        expected_tables={"Customer"},
        expected_analysis_type="count",
    ),
    dict(
        q="كام عميل موجود في قاعدة البيانات؟",
        expected_tables={"Customer"},
        expected_analysis_type="count",
    ),
    dict(
        q="What is the total revenue from all invoices?",
        expected_tables={"Invoice"},
        expected_analysis_type="aggregation",
    ),
    dict(
        q="Show me the top 5 best-selling artists",
        expected_tables={"Artist"},
        expected_analysis_type="ranking",
    ),
    dict(
        q="اعرضلي أفضل 5 فنانين مبيعاً",
        expected_tables={"Artist"},
        expected_analysis_type="ranking",
    ),
    dict(
        q="Compare total sales in the USA vs Canada",
        expected_tables={"Invoice", "Customer"},
        expected_analysis_type="comparison",
    ),
    dict(
        q="Show the monthly sales trend for 2012",
        expected_tables={"Invoice"},
        expected_analysis_type="trend",
    ),
    dict(
        q="Show the monthly sales of the best-selling artist",
        expected_tables={"Artist", "Invoice"},
        expected_analysis_type="multi_step",
    ),
    dict(
        q="List all tracks longer than 5 minutes",
        expected_tables={"Track"},
        expected_analysis_type="lookup",
    ),
    dict(
        q="What's the average invoice total per country?",
        expected_tables={"Invoice", "Customer"},
        expected_analysis_type="aggregation",
    ),
]

NORTHWIND_CASES = [
    dict(
        q="How many orders were placed in total?",
        expected_tables={"Orders"},
        expected_analysis_type="count",
    ),
    dict(
        q="كام طلب اتعمل خلال يناير؟",
        expected_tables={"Orders"},
        expected_analysis_type="count",
    ),
    dict(
        q="What is the total freight cost across all orders?",
        expected_tables={"Orders"},
        expected_analysis_type="aggregation",
    ),
    dict(
        q="Show the top 10 customers by total order value",
        expected_tables={"Customers", "Orders"},
        expected_analysis_type="ranking",
    ),
    dict(
        q="Compare sales performance between employees",
        expected_tables={"Employees", "Orders"},
        expected_analysis_type="comparison",
    ),
    dict(
        q="Show monthly order trend for 1997",
        expected_tables={"Orders"},
        expected_analysis_type="trend",
    ),
    dict(
        q="List all products that are out of stock",
        expected_tables={"Products"},
        expected_analysis_type="lookup",
    ),
    dict(
        q="What is the average unit price per category?",
        expected_tables={"Products", "Categories"},
        expected_analysis_type="aggregation",
    ),
    dict(
        q="اعرضلي أعلى 10 عملاء حسب إجمالي الطلبات",
        expected_tables={"Customers", "Orders"},
        expected_analysis_type="ranking",
    ),
    dict(
        q="Show the best-selling product's monthly sales",
        expected_tables={"Products", "Order Details"},
        expected_analysis_type="multi_step",
    ),
]

# Off-schema questions the agent should decline (UNANSWERABLE) rather than
# hallucinate SQL for. These require a live LLM call to actually verify
# (the sentinel is emitted by the model), so they're listed here for the
# *live* eval run (see run_baseline.py --live) rather than the offline pass.
OFF_SCHEMA_CASES = [
    dict(q="What is the weather like today?", schema="chinook"),
    dict(q="من هو رئيس مصر؟", schema="chinook"),
    dict(q="What is our employee satisfaction score?", schema="chinook"),
]
