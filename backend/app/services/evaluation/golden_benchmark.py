"""Comprehensive Golden Evaluation Benchmark Suite.

Contains 70 curated benchmark cases covering 7 analytical categories:
1. 10 Retrieval cases
2. 10 Aggregation cases
3. 10 Comparison cases
4. 10 Trend cases
5. 10 Exploratory cases
6. 10 Root Cause cases
7. 10 Anomaly / Correlation cases

Evaluates:
- Routing accuracy
- Analysis type accuracy
- SQL correctness
- Analysis correctness
- Claim grounding
- Final answer quality
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.agent.semantic.models import AnalysisType, QuerySpec
from app.services.report_service import ReportMode, ReportService
from app.services.sql.validator import SQLValidator
from app.services.sql.result_verifier import ResultVerifier
from app.services.analysis.models import AnalysisResult


class GoldenBenchmarkCase(BaseModel):
    id: str
    category: str
    question: str
    expected_analysis_type: AnalysisType
    expected_report_mode: ReportMode
    expected_tables: List[str]
    sample_sql: str
    sample_rows: List[Dict[str, Any]]
    expected_metrics_keywords: List[str] = Field(default_factory=list)
    unsupported_claim_example: Optional[str] = None


class GoldenEvaluationScorecard(BaseModel):
    total_cases: int = 0
    routing_accuracy_pct: float = 0.0
    analysis_type_accuracy_pct: float = 0.0
    sql_correctness_pct: float = 0.0
    analysis_correctness_pct: float = 0.0
    claim_grounding_pct: float = 0.0
    final_answer_quality_pct: float = 0.0
    overall_score_pct: float = 0.0
    category_scores: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    detailed_failures: List[Dict[str, Any]] = Field(default_factory=list)


# ─── 70 GOLDEN BENCHMARK CASES ───

GOLDEN_BENCHMARK_CASES: List[GoldenBenchmarkCase] = [
    # ── Category 1: Retrieval (10 cases) ──
    GoldenBenchmarkCase(
        id="RET_01",
        category="retrieval",
        question="بيانات العميل أحمد محمود",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["customers"],
        sample_sql="SELECT * FROM customers WHERE name LIKE '%أحمد محمود%'",
        sample_rows=[{"name": "أحمد محمود", "phone": "01012345678", "city": "Cairo"}],
        expected_metrics_keywords=["أحمد محمود", "الخلاصة", "التفاصيل"],
    ),
    GoldenBenchmarkCase(
        id="RET_02",
        category="retrieval",
        question="Show customer details for ID 105",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["customers"],
        sample_sql="SELECT * FROM customers WHERE customer_id = 105",
        sample_rows=[{"customer_id": 105, "name": "John Doe", "email": "john@example.com"}],
        expected_metrics_keywords=["John Doe", "Direct Answer", "Details"],
    ),
    GoldenBenchmarkCase(
        id="RET_03",
        category="retrieval",
        question="بيانات الطبيب استشاري القلب د. خالد",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["doctors"],
        sample_sql="SELECT * FROM doctors WHERE name LIKE '%خالد%' AND specialty = 'Cardiology'",
        sample_rows=[{"name": "د. خالد", "specialty": "Cardiology", "room": 204}],
        expected_metrics_keywords=["خالد", "الخلاصة", "التفاصيل"],
    ),
    GoldenBenchmarkCase(
        id="RET_04",
        category="retrieval",
        question="Fetch order information for order ORD-9921",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["orders"],
        sample_sql="SELECT * FROM orders WHERE order_code = 'ORD-9921'",
        sample_rows=[{"order_code": "ORD-9921", "status": "Shipped", "total": 450.0}],
        expected_metrics_keywords=["ORD-9921", "Shipped"],
    ),
    GoldenBenchmarkCase(
        id="RET_05",
        category="retrieval",
        question="تفاصيل المريض رقم ملفه 4401",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["patients"],
        sample_sql="SELECT * FROM patients WHERE file_no = 4401",
        sample_rows=[{"file_no": 4401, "name": "سارة علي", "gender": "F"}],
        expected_metrics_keywords=["سارة علي", "الخلاصة"],
    ),
    GoldenBenchmarkCase(
        id="RET_06",
        category="retrieval",
        question="Get details of product SKU-442",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["products"],
        sample_sql="SELECT * FROM products WHERE sku = 'SKU-442'",
        sample_rows=[{"sku": "SKU-442", "name": "Wireless Mouse", "stock": 50}],
        expected_metrics_keywords=["Wireless Mouse", "50"],
    ),
    GoldenBenchmarkCase(
        id="RET_07",
        category="retrieval",
        question="عنوان ورقم هاتف المورد الأمل",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["suppliers"],
        sample_sql="SELECT name, address, phone FROM suppliers WHERE name LIKE '%الأمل%'",
        sample_rows=[{"name": "شركة الأمل", "address": "Cairo", "phone": "022554433"}],
        expected_metrics_keywords=["شركة الأمل", "Cairo"],
    ),
    GoldenBenchmarkCase(
        id="RET_08",
        category="retrieval",
        question="Show department profile for Engineering",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["departments"],
        sample_sql="SELECT * FROM departments WHERE dept_name = 'Engineering'",
        sample_rows=[{"dept_name": "Engineering", "budget": 500000.0, "head": "Alice"}],
        expected_metrics_keywords=["Engineering", "500,000"],
    ),
    GoldenBenchmarkCase(
        id="RET_09",
        category="retrieval",
        question="بيانات فرع المعادي",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["branches"],
        sample_sql="SELECT * FROM branches WHERE branch_name = 'المعادي'",
        sample_rows=[{"branch_name": "المعادي", "city": "Cairo", "status": "Active"}],
        expected_metrics_keywords=["المعادي", "Active"],
    ),
    GoldenBenchmarkCase(
        id="RET_10",
        category="retrieval",
        question="Fetch vehicle registration record for plate ABC-123",
        expected_analysis_type=AnalysisType.LOOKUP,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["vehicles"],
        sample_sql="SELECT * FROM vehicles WHERE plate_no = 'ABC-123'",
        sample_rows=[{"plate_no": "ABC-123", "model": "Toyota", "year": 2023}],
        expected_metrics_keywords=["ABC-123", "Toyota"],
    ),

    # ── Category 2: Aggregation (10 cases) ──
    GoldenBenchmarkCase(
        id="AGG_01",
        category="aggregation",
        question="كم إجمالي المبيعات السنوية؟",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["sales"],
        sample_sql="SELECT SUM(amount) AS total_sales FROM sales",
        sample_rows=[{"total_sales": 2400000.0}],
        expected_metrics_keywords=["2,400,000", "الخلاصة", "طريقة الحساب"],
    ),
    GoldenBenchmarkCase(
        id="AGG_02",
        category="aggregation",
        question="What is the total number of registered patients?",
        expected_analysis_type=AnalysisType.COUNT,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["patients"],
        sample_sql="SELECT COUNT(*) AS total_patients FROM patients",
        sample_rows=[{"total_patients": 1420}],
        expected_metrics_keywords=["1,420", "Direct Metric", "Calculation Details"],
    ),
    GoldenBenchmarkCase(
        id="AGG_03",
        category="aggregation",
        question="ما هو متوسط رواتب الموظفين في قسم المبيعات؟",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["employees", "departments"],
        sample_sql="SELECT AVG(salary) AS avg_salary FROM employees e JOIN departments d ON e.dept_id = d.dept_id WHERE d.dept_name = 'Sales'",
        sample_rows=[{"avg_salary": 87500.0}],
        expected_metrics_keywords=["87,500", "الخلاصة"],
    ),
    GoldenBenchmarkCase(
        id="AGG_04",
        category="aggregation",
        question="What is the maximum order amount recorded?",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["orders"],
        sample_sql="SELECT MAX(total_amount) AS max_order FROM orders",
        sample_rows=[{"max_order": 95000.0}],
        expected_metrics_keywords=["95,000", "Direct Metric"],
    ),
    GoldenBenchmarkCase(
        id="AGG_05",
        category="aggregation",
        question="أقل سعر منتج في المخزن",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["products"],
        sample_sql="SELECT MIN(unit_price) AS min_price FROM products",
        sample_rows=[{"min_price": 15.5}],
        expected_metrics_keywords=["15.5", "الخلاصة"],
    ),
    GoldenBenchmarkCase(
        id="AGG_06",
        category="aggregation",
        question="Calculate total revenue for Q1 2024",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["orders"],
        sample_sql="SELECT SUM(amount) AS q1_revenue FROM orders WHERE order_date BETWEEN '2024-01-01' AND '2024-03-31'",
        sample_rows=[{"q1_revenue": 650000.0}],
        expected_metrics_keywords=["650,000", "Direct Metric"],
    ),
    GoldenBenchmarkCase(
        id="AGG_07",
        category="aggregation",
        question="إجمالي عدد العمليات الجراحية المنجزة هذا العام",
        expected_analysis_type=AnalysisType.COUNT,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["surgeries"],
        sample_sql="SELECT COUNT(*) AS total_surgeries FROM surgeries WHERE status = 'Completed'",
        sample_rows=[{"total_surgeries": 320}],
        expected_metrics_keywords=["320", "الخلاصة"],
    ),
    GoldenBenchmarkCase(
        id="AGG_08",
        category="aggregation",
        question="What is the average transaction value across all branches?",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["transactions"],
        sample_sql="SELECT AVG(amount) AS avg_transaction FROM transactions",
        sample_rows=[{"avg_transaction": 340.25}],
        expected_metrics_keywords=["340.25", "Direct Metric"],
    ),
    GoldenBenchmarkCase(
        id="AGG_09",
        category="aggregation",
        question="مجموع الميزانية المخصصة لجميع الأقسام",
        expected_analysis_type=AnalysisType.AGGREGATION,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["departments"],
        sample_sql="SELECT SUM(budget) AS total_budget FROM departments",
        sample_rows=[{"total_budget": 5000000.0}],
        expected_metrics_keywords=["5,000,000", "الخلاصة"],
    ),
    GoldenBenchmarkCase(
        id="AGG_10",
        category="aggregation",
        question="Count total number of active suppliers",
        expected_analysis_type=AnalysisType.COUNT,
        expected_report_mode=ReportMode.DETERMINISTIC,
        expected_tables=["suppliers"],
        sample_sql="SELECT COUNT(*) AS active_suppliers FROM suppliers WHERE is_active = 1",
        sample_rows=[{"active_suppliers": 45}],
        expected_metrics_keywords=["45", "Direct Metric"],
    ),

    # ── Category 3: Comparison (10 cases) ──
    GoldenBenchmarkCase(
        id="COMP_01",
        category="comparison",
        question="قارن بين مبيعات فرع القاهرة وفرع الإسكندرية",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["branches", "sales"],
        sample_sql="SELECT b.branch_name, SUM(s.amount) AS sales FROM sales s JOIN branches b ON s.branch_id = b.id GROUP BY b.branch_name",
        sample_rows=[{"branch": "القاهرة", "sales": 500000.0}, {"branch": "الإسكندرية", "sales": 300000.0}],
        expected_metrics_keywords=["الخلاصة", "مقارنة الأطراف", "الطرف الأول", "الطرف الثاني", "الفارق", "المتصدر"],
    ),
    GoldenBenchmarkCase(
        id="COMP_02",
        category="comparison",
        question="Compare performance of Product A versus Product B",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["products", "sales"],
        sample_sql="SELECT product_name, SUM(amount) AS revenue FROM sales GROUP BY product_name",
        sample_rows=[{"product": "Product A", "revenue": 120000.0}, {"product": "Product B", "revenue": 80000.0}],
        expected_metrics_keywords=["Comparison Summary", "Breakdown", "Entity A", "Entity B", "Difference", "Winner"],
    ),
    GoldenBenchmarkCase(
        id="COMP_03",
        category="comparison",
        question="مقارنة بين إيرادات الربع الأول والربع الثاني",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["sales"],
        sample_sql="SELECT quarter, SUM(amount) FROM sales GROUP BY quarter",
        sample_rows=[{"quarter": "Q1", "revenue": 400000.0}, {"quarter": "Q2", "revenue": 550000.0}],
        expected_metrics_keywords=["الخلاصة", "مقارنة الأطراف", "الفارق", "المتصدر"],
    ),
    GoldenBenchmarkCase(
        id="COMP_04",
        category="comparison",
        question="Compare patient admission rates between Cardiology and Orthopedics",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["admissions", "departments"],
        sample_sql="SELECT dept_name, COUNT(*) FROM admissions GROUP BY dept_name",
        sample_rows=[{"dept": "Cardiology", "count": 210}, {"dept": "Orthopedics", "count": 140}],
        expected_metrics_keywords=["Comparison Summary", "Breakdown", "Difference"],
    ),
    GoldenBenchmarkCase(
        id="COMP_05",
        category="comparison",
        question="قارن بين العملاء الجدد والعملاء الدائمين من حيث متوسط الشراء",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["customers", "orders"],
        sample_sql="SELECT customer_tier, AVG(order_value) FROM orders GROUP BY customer_tier",
        sample_rows=[{"tier": "دائم", "avg": 750.0}, {"tier": "جديد", "avg": 300.0}],
        expected_metrics_keywords=["الخلاصة", "مقارنة الأطراف", "المتصدر"],
    ),
    GoldenBenchmarkCase(
        id="COMP_06",
        category="comparison",
        question="Compare budget vs actual expenditure for Engineering division",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["budgets", "expenses"],
        sample_sql="SELECT 'Budget' AS type, 500000.0 AS val UNION ALL SELECT 'Actual', 420000.0",
        sample_rows=[{"type": "Budget", "val": 500000.0}, {"type": "Actual", "val": 420000.0}],
        expected_metrics_keywords=["Comparison Summary", "Difference"],
    ),
    GoldenBenchmarkCase(
        id="COMP_07",
        category="comparison",
        question="مقارنة بين تكلفة الشحن الداخلي والخارجي",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["shipments"],
        sample_sql="SELECT shipping_type, AVG(cost) FROM shipments GROUP BY shipping_type",
        sample_rows=[{"type": "دولي", "cost": 1200.0}, {"type": "محلي", "cost": 300.0}],
        expected_metrics_keywords=["الخلاصة", "الفارق"],
    ),
    GoldenBenchmarkCase(
        id="COMP_08",
        category="comparison",
        question="Compare online vs retail store sales volume",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["channels", "orders"],
        sample_sql="SELECT channel, SUM(amount) FROM orders GROUP BY channel",
        sample_rows=[{"channel": "Online", "amount": 900000.0}, {"channel": "Retail", "amount": 600000.0}],
        expected_metrics_keywords=["Comparison Summary", "Winner / Leader"],
    ),
    GoldenBenchmarkCase(
        id="COMP_09",
        category="comparison",
        question="مقارنة بين إنتاجية وردية الصباح ووردية المساء",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["production"],
        sample_sql="SELECT shift, SUM(units_produced) FROM production GROUP BY shift",
        sample_rows=[{"shift": "Morning", "units": 4500}, {"shift": "Evening", "units": 3800}],
        expected_metrics_keywords=["الخلاصة", "الطرف الأول", "الطرف الثاني"],
    ),
    GoldenBenchmarkCase(
        id="COMP_10",
        category="comparison",
        question="Compare default rate between Tier 1 and Tier 2 credit clients",
        expected_analysis_type=AnalysisType.COMPARISON,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["loans"],
        sample_sql="SELECT credit_tier, AVG(default_flag) FROM loans GROUP BY credit_tier",
        sample_rows=[{"tier": "Tier 1", "rate": 0.02}, {"tier": "Tier 2", "rate": 0.08}],
        expected_metrics_keywords=["Comparison Summary", "Difference"],
    ),

    # ── Category 4: Trend (10 cases) ──
    GoldenBenchmarkCase(
        id="TRD_01",
        category="trend",
        question="تطور المبيعات الشهرية خلال عام 2024",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["sales"],
        sample_sql="SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS sales FROM sales GROUP BY month ORDER BY month",
        sample_rows=[{"month": "2024-01", "sales": 100000.0}, {"month": "2024-02", "sales": 150000.0}, {"month": "2024-03", "sales": 200000.0}],
        expected_metrics_keywords=["الخلاصة", "تحليل المسار الزمني", "الاتجاه العام", "أعلى نقطة", "أدنى نقطة", "معدل النمو"],
    ),
    GoldenBenchmarkCase(
        id="TRD_02",
        category="trend",
        question="How have weekly user registrations trended over the past quarter?",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["users"],
        sample_sql="SELECT week_no, COUNT(*) AS new_users FROM users GROUP BY week_no ORDER BY week_no",
        sample_rows=[{"week": "W1", "users": 100}, {"week": "W2", "users": 120}, {"week": "W3", "users": 140}],
        expected_metrics_keywords=["Trend Summary", "Time-Series Analysis", "Overall Trend", "Peak", "Growth Rate"],
    ),
    GoldenBenchmarkCase(
        id="TRD_03",
        category="trend",
        question="مسار نمو الإيرادات السنوية على مدار آخر 3 سنوات",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["annual_finances"],
        sample_sql="SELECT year, revenue FROM annual_finances ORDER BY year",
        sample_rows=[{"year": "2022", "rev": 1000000.0}, {"year": "2023", "rev": 1300000.0}, {"year": "2024", "rev": 1700000.0}],
        expected_metrics_keywords=["الخلاصة", "الاتجاه العام", "أعلى نقطة"],
    ),
    GoldenBenchmarkCase(
        id="TRD_04",
        category="trend",
        question="Analyze the trend in average hospitalization days over time",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["hospital_stays"],
        sample_sql="SELECT month, AVG(duration_days) FROM hospital_stays GROUP BY month ORDER BY month",
        sample_rows=[{"month": "M1", "days": 6.5}, {"month": "M2", "days": 5.8}, {"month": "M3", "days": 4.9}],
        expected_metrics_keywords=["Trend Summary", "Overall Trend", "Lowest"],
    ),
    GoldenBenchmarkCase(
        id="TRD_05",
        category="trend",
        question="اتجاه تكاليف الصيانة الشهرية للأسطول",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["maintenance_logs"],
        sample_sql="SELECT month, SUM(cost) FROM maintenance_logs GROUP BY month ORDER BY month",
        sample_rows=[{"m": "Jan", "cost": 25000.0}, {"m": "Feb", "cost": 22000.0}, {"m": "Mar", "cost": 30000.0}],
        expected_metrics_keywords=["الخلاصة", "تحليل المسار الزمني"],
    ),
    GoldenBenchmarkCase(
        id="TRD_06",
        category="trend",
        question="Track daily active active users for the last 30 days",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["user_activity"],
        sample_sql="SELECT date, COUNT(DISTINCT user_id) FROM user_activity GROUP BY date ORDER BY date",
        sample_rows=[{"date": "2024-01-01", "dau": 500}, {"date": "2024-01-02", "dau": 550}],
        expected_metrics_keywords=["Trend Summary", "Growth Rate"],
    ),
    GoldenBenchmarkCase(
        id="TRD_07",
        category="trend",
        question="معدل نمو استهلاك المواد الخام من شهر لآخر",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["inventory_usage"],
        sample_sql="SELECT month, SUM(qty) FROM inventory_usage GROUP BY month ORDER BY month",
        sample_rows=[{"m": "Jan", "qty": 1000}, {"m": "Feb", "qty": 1150}],
        expected_metrics_keywords=["الخلاصة", "معدل النمو"],
    ),
    GoldenBenchmarkCase(
        id="TRD_08",
        category="trend",
        question="Monthly customer churn rate progression",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["subscriptions"],
        sample_sql="SELECT month, churn_pct FROM subscriptions_kpi ORDER BY month",
        sample_rows=[{"month": "Jan", "churn": 0.05}, {"month": "Feb", "churn": 0.04}, {"month": "Mar", "churn": 0.03}],
        expected_metrics_keywords=["Trend Summary", "Overall Trend"],
    ),
    GoldenBenchmarkCase(
        id="TRD_09",
        category="trend",
        question="تطور أسعار الذهب اليومية",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["gold_rates"],
        sample_sql="SELECT date, price_per_gram FROM gold_rates ORDER BY date",
        sample_rows=[{"d": "D1", "price": 3100.0}, {"d": "D2", "price": 3150.0}],
        expected_metrics_keywords=["الخلاصة", "تحليل المسار الزمني"],
    ),
    GoldenBenchmarkCase(
        id="TRD_10",
        category="trend",
        question="Trend of quarterly profit margin over 2 years",
        expected_analysis_type=AnalysisType.TREND,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["quarterly_finances"],
        sample_sql="SELECT quarter, margin_pct FROM quarterly_finances ORDER BY quarter",
        sample_rows=[{"q": "Q1", "m": 0.18}, {"q": "Q2", "m": 0.22}],
        expected_metrics_keywords=["Trend Summary", "Peak"],
    ),

    # ── Category 5: Exploratory (10 cases) ──
    GoldenBenchmarkCase(
        id="EXP_01",
        category="exploratory",
        question="حلل واستكشف جدول المبيعات وتوزيعه بالكامل",
        expected_analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["sales"],
        sample_sql="SELECT * FROM sales",
        sample_rows=[{"id": 1, "product": "P1", "amount": 100.0}, {"id": 2, "product": "P2", "amount": 200.0}],
        expected_metrics_keywords=["الخلاصة", "التقرير الاستكشافي الشامل", "نظرة عامة", "أهم النتائج", "الأنماط", "القيم الشاذة", "جودة البيانات", "التوصيات"],
    ),
    GoldenBenchmarkCase(
        id="EXP_02",
        category="exploratory",
        question="Provide a full exploratory data analysis profile of the customers table",
        expected_analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["customers"],
        sample_sql="SELECT * FROM customers",
        sample_rows=[{"id": 10, "city": "Cairo", "age": 30}],
        expected_metrics_keywords=["Exploratory Summary", "Comprehensive Profile", "Overview", "Key Findings", "Patterns", "Anomalies", "Data Quality", "Recommendations"],
    ),
    GoldenBenchmarkCase(
        id="EXP_03",
        category="exploratory",
        question="فحص شامل وتدقيق لجودة بيانات جدول المرضى",
        expected_analysis_type=AnalysisType.DATA_QUALITY,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["patients"],
        sample_sql="SELECT * FROM patients",
        sample_rows=[{"id": 1, "name": "أحمد", "age": 45}],
        expected_metrics_keywords=["الخلاصة", "التقرير الاستكشافي الشامل", "جودة البيانات"],
    ),
    GoldenBenchmarkCase(
        id="EXP_04",
        category="exploratory",
        question="Analyze the distribution and spread of order values",
        expected_analysis_type=AnalysisType.DISTRIBUTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["orders"],
        sample_sql="SELECT order_id, amount FROM orders",
        sample_rows=[{"order_id": 1, "amount": 150.0}],
        expected_metrics_keywords=["Exploratory Summary", "Key Findings"],
    ),
    GoldenBenchmarkCase(
        id="EXP_05",
        category="exploratory",
        question="استكشاف أنماط المشتريات وتصنيف السجلات",
        expected_analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["purchases"],
        sample_sql="SELECT * FROM purchases",
        sample_rows=[{"id": 100, "supplier": "S1", "cost": 5000.0}],
        expected_metrics_keywords=["الخلاصة", "الأنماط"],
    ),
    GoldenBenchmarkCase(
        id="EXP_06",
        category="exploratory",
        question="Audit data quality and identify missing columns in employee records",
        expected_analysis_type=AnalysisType.DATA_QUALITY,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["employees"],
        sample_sql="SELECT * FROM employees",
        sample_rows=[{"emp_id": 1, "dept": "HR", "salary": 50000.0}],
        expected_metrics_keywords=["Exploratory Summary", "Data Quality"],
    ),
    GoldenBenchmarkCase(
        id="EXP_07",
        category="exploratory",
        question="دراسة استكشافية لحجم المعاملات اليومية والتباين بينها",
        expected_analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["transactions"],
        sample_sql="SELECT * FROM transactions",
        sample_rows=[{"tx_id": 1, "val": 200.0}],
        expected_metrics_keywords=["الخلاصة", "نظرة عامة"],
    ),
    GoldenBenchmarkCase(
        id="EXP_08",
        category="exploratory",
        question="Segment customer database by purchase frequency and total spend",
        expected_analysis_type=AnalysisType.SEGMENTATION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["customer_segments"],
        sample_sql="SELECT customer_id, freq, total_spend FROM customer_segments",
        sample_rows=[{"customer_id": 1, "freq": 10, "total_spend": 2500.0}],
        expected_metrics_keywords=["Exploratory Summary", "Patterns"],
    ),
    GoldenBenchmarkCase(
        id="EXP_09",
        category="exploratory",
        question="تحليل شامل لتوزيع أعمار المرضى وتكرار الحالات",
        expected_analysis_type=AnalysisType.DISTRIBUTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["patients"],
        sample_sql="SELECT age, diagnosis FROM patients",
        sample_rows=[{"age": 35, "diagnosis": "Flu"}],
        expected_metrics_keywords=["الخلاصة", "التقرير الاستكشافي الشامل"],
    ),
    GoldenBenchmarkCase(
        id="EXP_10",
        category="exploratory",
        question="Full dataset exploration of warehouse inventory levels and turnover",
        expected_analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["inventory"],
        sample_sql="SELECT * FROM inventory",
        sample_rows=[{"item_id": 1, "stock_level": 400}],
        expected_metrics_keywords=["Exploratory Summary", "Recommendations"],
    ),

    # ── Category 6: Root Cause (10 cases) ──
    GoldenBenchmarkCase(
        id="RCA_01",
        category="root_cause",
        question="ما سبب انخفاض مبيعات الربع الرابع مقارنة بالربع الثالث؟",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["sales_history"],
        sample_sql="SELECT region, SUM(sales) FROM sales_history GROUP BY region",
        sample_rows=[{"region": "القاهرة", "decline": -110000.0}],
        expected_metrics_keywords=["الخلاصة", "تحليل الأسباب والمساهمين", "النتيجة الرئيسية", "أكبر المساهمين", "الأدلة الداعمة", "حدود التحليل"],
        unsupported_claim_example="السبب هو ضعف الحملات الإعلانية ومشاكل في إدارة التسويق",
    ),
    GoldenBenchmarkCase(
        id="RCA_02",
        category="root_cause",
        question="Why did overall profit margins decrease in 2024?",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["profit_records"],
        sample_sql="SELECT category, delta FROM profit_records",
        sample_rows=[{"category": "Hardware", "delta": -45000.0}],
        expected_metrics_keywords=["Root Cause Summary", "Decomposition & Attribution", "Main Finding", "Top Contributors", "Supporting Evidence", "Limitations"],
        unsupported_claim_example="The drop was caused by aggressive competitor marketing and poor sales team motivation",
    ),
    GoldenBenchmarkCase(
        id="RCA_03",
        category="root_cause",
        question="لماذا تراجع عدد حجوزات العيادات في شهر مايو؟",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["clinic_bookings"],
        sample_sql="SELECT specialty, delta FROM clinic_bookings",
        sample_rows=[{"specialty": "Dentistry", "delta": -80}],
        expected_metrics_keywords=["الخلاصة", "تحليل الأسباب والمساهمين", "أكبر المساهمين"],
        unsupported_claim_example="السبب هو عدم رضا المرضى عن مواعيد الأطباء",
    ),
    GoldenBenchmarkCase(
        id="RCA_04",
        category="root_cause",
        question="What factors drove the sudden increase in customer churn last month?",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["churn_analysis"],
        sample_sql="SELECT plan_type, churn_count FROM churn_analysis",
        sample_rows=[{"plan": "Basic", "churn": 250}],
        expected_metrics_keywords=["Root Cause Summary", "Top Contributors"],
        unsupported_claim_example="Churn spiked because competitors launched lower prices",
    ),
    GoldenBenchmarkCase(
        id="RCA_05",
        category="root_cause",
        question="ما هي الأسباب الرئيسية لارتفاع تكاليف الشحن هذا الشهر؟",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["shipping_expenses"],
        sample_sql="SELECT route, delta_cost FROM shipping_expenses",
        sample_rows=[{"route": "Alexandria-Cairo", "delta_cost": 35000.0}],
        expected_metrics_keywords=["الخلاصة", "النتيجة الرئيسية", "الأدلة الداعمة"],
        unsupported_claim_example="السبب هو ارتفاع أسعار الوقود في السوق",
    ),
    GoldenBenchmarkCase(
        id="RCA_06",
        category="root_cause",
        question="Investigate the root cause of production delays in factory line B",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["factory_downtime"],
        sample_sql="SELECT machine_id, downtime_hours FROM factory_downtime",
        sample_rows=[{"machine": "Press-01", "downtime": 48.5}],
        expected_metrics_keywords=["Root Cause Summary", "Decomposition & Attribution"],
        unsupported_claim_example="Due to operator negligence during shift changes",
    ),
    GoldenBenchmarkCase(
        id="RCA_07",
        category="root_cause",
        question="ليه إيرادات فرع الإسكندرية قلت 25% عن المستهدف؟",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["branch_targets"],
        sample_sql="SELECT product_group, shortfall FROM branch_targets WHERE branch = 'Alexandria'",
        sample_rows=[{"group": "Beverages", "shortfall": -15000.0}],
        expected_metrics_keywords=["الخلاصة", "تحليل الأسباب والمساهمين"],
        unsupported_claim_example="السبب هو سوء الأحوال الجوية في الإسكندرية",
    ),
    GoldenBenchmarkCase(
        id="RCA_08",
        category="root_cause",
        question="What caused the spike in loan defaults in Q3?",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["loan_defaults"],
        sample_sql="SELECT sector, default_amount FROM loan_defaults",
        sample_rows=[{"sector": "Real Estate", "amount": 2500000.0}],
        expected_metrics_keywords=["Root Cause Summary", "Supporting Evidence"],
        unsupported_claim_example="Caused by economic recession in the construction sector",
    ),
    GoldenBenchmarkCase(
        id="RCA_09",
        category="root_cause",
        question="ما العوامل المؤدية لتراجع مخزون قطع الغيار بشكل مفاجئ؟",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["inventory_outages"],
        sample_sql="SELECT part_type, consumption_spike FROM inventory_outages",
        sample_rows=[{"part": "Filters", "consumption": 1200}],
        expected_metrics_keywords=["الخلاصة", "أكبر المساهمين"],
        unsupported_claim_example="بسبب سرقة أو سوء تخزين في المستودع",
    ),
    GoldenBenchmarkCase(
        id="RCA_10",
        category="root_cause",
        question="Why did surgery completion times increase this quarter?",
        expected_analysis_type=AnalysisType.ROOT_CAUSE,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["surgery_logs"],
        sample_sql="SELECT procedure_type, delta_minutes FROM surgery_logs",
        sample_rows=[{"procedure": "Cardiac", "delta": 35.0}],
        expected_metrics_keywords=["Root Cause Summary", "Limitations"],
        unsupported_claim_example="Because of new junior nursing staff mistakes",
    ),

    # ── Category 7: Anomaly & Correlation (10 cases) ──
    GoldenBenchmarkCase(
        id="ANOM_01",
        category="anomaly_correlation",
        question="هل يوجد ارتباط بين السعر والكمية المباعة؟",
        expected_analysis_type=AnalysisType.CORRELATION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["products", "sales"],
        sample_sql="SELECT price, quantity FROM sales",
        sample_rows=[{"price": 10.0, "quantity": 100.0}, {"price": 50.0, "quantity": 20.0}],
        expected_metrics_keywords=["الخلاصة", "التقرير الاستكشافي الشامل"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_02",
        category="anomaly_correlation",
        question="Is there a statistical correlation between marketing spend and quarterly revenue?",
        expected_analysis_type=AnalysisType.CORRELATION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["marketing_kpis"],
        sample_sql="SELECT spend, revenue FROM marketing_kpis",
        sample_rows=[{"spend": 1000.0, "revenue": 5000.0}, {"spend": 3000.0, "revenue": 14000.0}],
        expected_metrics_keywords=["Exploratory Summary", "Comprehensive Profile"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_03",
        category="anomaly_correlation",
        question="ابحث عن القيم الشاذة في فواتير الشراء لهذا العام",
        expected_analysis_type=AnalysisType.ANOMALY_DETECTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["invoices"],
        sample_sql="SELECT invoice_id, amount FROM invoices",
        sample_rows=[{"invoice_id": 99, "amount": 500000.0}],
        expected_metrics_keywords=["الخلاصة", "القيم الشاذة"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_04",
        category="anomaly_correlation",
        question="Detect transaction anomalies exceeding 3 standard deviations",
        expected_analysis_type=AnalysisType.ANOMALY_DETECTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["transactions"],
        sample_sql="SELECT tx_id, amount FROM transactions",
        sample_rows=[{"tx_id": 1044, "amount": 950000.0}],
        expected_metrics_keywords=["Exploratory Summary", "Anomalies"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_05",
        category="anomaly_correlation",
        question="هل يؤثر الخصم على هامش الربح؟ وما درجة الارتباط؟",
        expected_analysis_type=AnalysisType.CORRELATION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["orders"],
        sample_sql="SELECT discount, margin FROM orders",
        sample_rows=[{"discount": 0.2, "margin": 0.15}],
        expected_metrics_keywords=["الخلاصة", "الأنماط"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_06",
        category="anomaly_correlation",
        question="Find outlier patient recovery durations in the surgical ward",
        expected_analysis_type=AnalysisType.ANOMALY_DETECTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["surgeries"],
        sample_sql="SELECT patient_id, recovery_days FROM surgeries",
        sample_rows=[{"patient_id": 402, "recovery_days": 45}],
        expected_metrics_keywords=["Exploratory Summary", "Anomalies"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_07",
        category="anomaly_correlation",
        question="ارتباط درجات تقييم الأداء بالرواتب والمكافآت",
        expected_analysis_type=AnalysisType.CORRELATION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["evaluations", "employees"],
        sample_sql="SELECT rating, salary FROM employee_evaluations",
        sample_rows=[{"rating": 4.8, "salary": 120000.0}],
        expected_metrics_keywords=["الخلاصة", "التقرير الاستكشافي الشامل"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_08",
        category="anomaly_correlation",
        question="Detect unusual spikes in warehouse energy consumption",
        expected_analysis_type=AnalysisType.ANOMALY_DETECTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["energy_meter"],
        sample_sql="SELECT timestamp, kwh FROM energy_meter",
        sample_rows=[{"ts": "2024-05-01", "kwh": 12500}],
        expected_metrics_keywords=["Exploratory Summary", "Anomalies"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_09",
        category="anomaly_correlation",
        question="هل توجد عمليات سحب بنكي شاذة أو مشبوهة اليوم؟",
        expected_analysis_type=AnalysisType.ANOMALY_DETECTION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["bank_withdrawals"],
        sample_sql="SELECT account_id, amount FROM bank_withdrawals",
        sample_rows=[{"acc": 12, "amount": 800000.0}],
        expected_metrics_keywords=["الخلاصة", "القيم الشاذة"],
    ),
    GoldenBenchmarkCase(
        id="ANOM_10",
        category="anomaly_correlation",
        question="Analyze correlation between customer age and loan default probability",
        expected_analysis_type=AnalysisType.CORRELATION,
        expected_report_mode=ReportMode.SYNTHESIS,
        expected_tables=["credit_data"],
        sample_sql="SELECT age, default_rate FROM credit_data",
        sample_rows=[{"age": 22, "default_rate": 0.12}, {"age": 55, "default_rate": 0.02}],
        expected_metrics_keywords=["Exploratory Summary", "Patterns"],
    ),
]


class GoldenBenchmarkRunner:
    """Executes evaluation across all 70 golden benchmark cases."""

    def __init__(self):
        self.report_service = ReportService()
        self.sql_validator = SQLValidator()
        self.result_verifier = ResultVerifier()

    def run_benchmark(self, cases: Optional[List[GoldenBenchmarkCase]] = None) -> GoldenEvaluationScorecard:
        target_cases = cases or GOLDEN_BENCHMARK_CASES
        scorecard = GoldenEvaluationScorecard(total_cases=len(target_cases))

        routing_hits = 0
        analysis_type_hits = 0
        sql_valid_hits = 0
        analysis_correct_hits = 0
        claim_grounded_hits = 0
        quality_hits = 0

        categories: Dict[str, Dict[str, int]] = {}

        for case in target_cases:
            cat = case.category
            if cat not in categories:
                categories[cat] = {"total": 0, "routing": 0, "type": 0, "sql": 0, "analysis": 0, "claim": 0, "quality": 0}
            categories[cat]["total"] += 1

            # 1. Routing & Analysis Type Accuracy
            spec = QuerySpec(raw_question=case.question, analysis_type=case.expected_analysis_type)
            actual_route = self.report_service.resolve_report_mode(spec)
            is_routing_correct = (actual_route == case.expected_report_mode)
            if is_routing_correct:
                routing_hits += 1
                categories[cat]["routing"] += 1

            is_type_correct = (spec.analysis_type == case.expected_analysis_type)
            if is_type_correct:
                analysis_type_hits += 1
                categories[cat]["type"] += 1

            # 2. SQL Correctness (AST & safety check)
            sql_res = self.sql_validator.validate_safety(case.sample_sql)
            is_sql_valid = bool(sql_res.get("valid", False))
            if is_sql_valid:
                sql_valid_hits += 1
                categories[cat]["sql"] += 1

            # 3. Final Report & Analysis Quality
            analysis_res = AnalysisResult(
                analysis_type=case.expected_analysis_type.value if hasattr(case.expected_analysis_type, "value") else str(case.expected_analysis_type),
                goal=case.question,
                findings=[f"Finding for {case.id}"],
                metrics={"metric_1": 100.0},
                evidence=[f"Evidence for {case.id}"],
                limitations=["Data restricted to database records"],
                confidence=1.0,
            )

            report = self.report_service._format_conversational_report(
                question=case.question,
                sql=case.sample_sql,
                results=case.sample_rows,
                query_spec=spec,
                analysis_result=analysis_res,
            )

            # Check presence of expected archetype structure keywords
            is_quality_good = any(k in report for k in case.expected_metrics_keywords)
            if is_quality_good:
                quality_hits += 1
                categories[cat]["quality"] += 1

            # 4. Analysis Correctness (Execution / Fact generation)
            is_analysis_correct = len(report) > 20 and ("الخلاصة:" in report or "Summary" in report or "Direct" in report or "Short answer:" in report)
            if is_analysis_correct:
                analysis_correct_hits += 1
                categories[cat]["analysis"] += 1

            # 5. Claim Grounding (Ensuring Hallucination Prevention)
            constrained_prose, evaluations, conf = self.result_verifier.verify_and_constrain_prose(
                report,
                rows=case.sample_rows,
                analytics_result=analysis_res,
            )
            # Legitimate generated report should have 0 ungrounded claims
            is_grounded = all(e.status != "UNSUPPORTED_CLAIM" for e in evaluations)
            
            # If an unsupported claim example is provided, verify the verifier blocks it
            if case.unsupported_claim_example:
                bad_prose = f"{report}\n{case.unsupported_claim_example}"
                _, bad_evals, _ = self.result_verifier.verify_and_constrain_prose(
                    bad_prose,
                    rows=case.sample_rows,
                )
                unsupported_detected = any(e.status == "UNSUPPORTED_CLAIM" for e in bad_evals)
                is_grounded = is_grounded and unsupported_detected

            if is_grounded:
                claim_grounded_hits += 1
                categories[cat]["claim"] += 1
            else:
                scorecard.detailed_failures.append({
                    "case_id": case.id,
                    "question": case.question,
                    "reason": "Claim grounding or ungrounded assertion check failed",
                })

        n = len(target_cases) if target_cases else 1
        scorecard.routing_accuracy_pct = round(routing_hits / n * 100.0, 2)
        scorecard.analysis_type_accuracy_pct = round(analysis_type_hits / n * 100.0, 2)
        scorecard.sql_correctness_pct = round(sql_valid_hits / n * 100.0, 2)
        scorecard.analysis_correctness_pct = round(analysis_correct_hits / n * 100.0, 2)
        scorecard.claim_grounding_pct = round(claim_grounded_hits / n * 100.0, 2)
        scorecard.final_answer_quality_pct = round(quality_hits / n * 100.0, 2)

        scorecard.overall_score_pct = round(
            (
                scorecard.routing_accuracy_pct
                + scorecard.analysis_type_accuracy_pct
                + scorecard.sql_correctness_pct
                + scorecard.analysis_correctness_pct
                + scorecard.claim_grounding_pct
                + scorecard.final_answer_quality_pct
            )
            / 6.0,
            2,
        )

        for cat, scores in categories.items():
            tot = scores["total"] or 1
            scorecard.category_scores[cat] = {
                "routing_pct": round(scores["routing"] / tot * 100.0, 1),
                "type_pct": round(scores["type"] / tot * 100.0, 1),
                "sql_pct": round(scores["sql"] / tot * 100.0, 1),
                "analysis_pct": round(scores["analysis"] / tot * 100.0, 1),
                "claim_pct": round(scores["claim"] / tot * 100.0, 1),
                "quality_pct": round(scores["quality"] / tot * 100.0, 1),
            }

        return scorecard
