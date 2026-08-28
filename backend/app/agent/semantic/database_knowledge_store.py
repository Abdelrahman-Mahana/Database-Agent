"""Database Knowledge Store — Manages domain glossaries, business rules, and golden few-shot patterns per database."""
import os
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GoldenPattern:
    """A verified question and high-quality SQL pattern."""
    question: str
    sql: str
    analysis_type: str = "general"
    tables: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class DatabaseKnowledge:
    """Domain knowledge and glossary rules for a specific database profile."""
    database_name: str
    dialect: str = "postgresql"
    glossary: Dict[str, str] = field(default_factory=dict)
    rules: List[str] = field(default_factory=list)
    golden_patterns: List[GoldenPattern] = field(default_factory=list)


class DatabaseKnowledgeStore:
    """
    Central repository of domain intelligence per database.
    Provides fast semantic lookup for few-shots, business rules, and table synonyms.
    """

    def __init__(self):
        self._profiles: Dict[str, DatabaseKnowledge] = {}
        self._load_default_profiles()

    def _load_default_profiles(self):
        """Initialize built-in knowledge for common enterprise databases."""
        # 1. Agial / Odoo ERP Profile (PostgreSQL)
        agial = DatabaseKnowledge(
            database_name="agial",
            dialect="postgresql",
            glossary={
                "فواتير": "account_move",
                "الفواتير": "account_move",
                "فاتورة": "account_move",
                "عملاء": "res_partner",
                "العملاء": "res_partner",
                "عميل": "res_partner",
                "موردين": "res_partner",
                "منتجات": "product_product / product_template",
                "حسابات": "account_account",
                "قيود": "account_move_line",
                "إيرادات": "SUM(am.amount_total) from account_move",
                "مبيعات": "SUM(am.amount_total) from account_move",
            },
            rules=[
                "In account_move, the primary date column for revenue and invoices is 'invoice_date' (or 'date').",
                "Always filter out NULL dates: am.invoice_date IS NOT NULL.",
                "For invoice revenue, use SUM(am.amount_total).",
                "For monthly grouping in PostgreSQL, use TO_CHAR(am.invoice_date, 'YYYY-MM').",
                "For customer names, join account_move am ON am.partner_id = rp.id to res_partner rp.",
                "For top/bottom rankings across months, calculate monthly sums and rank with ORDER BY total DESC / ASC.",
            ],
            golden_patterns=[
                GoldenPattern(
                    question="مسار الإيرادات الشهرية من الفواتير (account_move) وتحديد الشهور الأعلى والأدنى",
                    sql="""SELECT
  TO_CHAR(am.invoice_date, 'YYYY-MM') AS month,
  SUM(am.amount_total) AS total_revenue
FROM public.account_move AS am
WHERE am.invoice_date IS NOT NULL
GROUP BY TO_CHAR(am.invoice_date, 'YYYY-MM')
ORDER BY month ASC
LIMIT 500""",
                    analysis_type="trend",
                    tables=["account_move"],
                    description="Monthly revenue trajectory from invoices",
                ),
                GoldenPattern(
                    question="أعلى 10 عملاء من حيث إجمالي الفواتير",
                    sql="""SELECT
  rp.name AS customer_name,
  SUM(am.amount_total) AS total_amount,
  COUNT(am.id) AS invoice_count
FROM public.account_move AS am
JOIN public.res_partner AS rp ON am.partner_id = rp.id
WHERE am.invoice_date IS NOT NULL
GROUP BY rp.id, rp.name
ORDER BY total_amount DESC
LIMIT 10""",
                    analysis_type="ranking",
                    tables=["account_move", "res_partner"],
                    description="Top customers by invoice revenue",
                ),
                GoldenPattern(
                    question="عدد الفواتير وإجمالي المبالغ حسب الحالة",
                    sql="""SELECT
  am.state AS invoice_status,
  COUNT(am.id) AS total_invoices,
  SUM(am.amount_total) AS total_revenue
FROM public.account_move AS am
GROUP BY am.state
ORDER BY total_revenue DESC
LIMIT 500""",
                    analysis_type="aggregation",
                    tables=["account_move"],
                    description="Invoices breakdown by status",
                ),
            ]
        )
        self._profiles["agial"] = agial

        # 2. Chinook E-Commerce Profile (SQLite)
        chinook = DatabaseKnowledge(
            database_name="chinook",
            dialect="sqlite",
            glossary={
                "invoices": "Invoice",
                "customers": "Customer",
                "tracks": "Track",
                "artists": "Artist",
                "albums": "Album",
                "genres": "Genre",
                "employees": "Employee",
                "sales": "SUM(Total) from Invoice",
            },
            rules=[
                "In Invoice, the date column is 'InvoiceDate'.",
                "For monthly grouping in SQLite, use strftime('%Y-%m', InvoiceDate).",
                "For customer total spend, join Invoice with Customer ON Customer.CustomerId = Invoice.CustomerId.",
            ],
            golden_patterns=[
                GoldenPattern(
                    question="Top 5 customers by total spend",
                    sql="""SELECT
  c.CustomerId,
  c.FirstName || ' ' || c.LastName AS CustomerName,
  SUM(i.Total) AS TotalSpent
FROM Customer c
JOIN Invoice i ON c.CustomerId = i.CustomerId
GROUP BY c.CustomerId, c.FirstName, c.LastName
ORDER BY TotalSpent DESC
LIMIT 5""",
                    analysis_type="ranking",
                    tables=["Customer", "Invoice"],
                    description="Top customers by total invoice amount",
                ),
                GoldenPattern(
                    question="Monthly revenue trend",
                    sql="""SELECT
  strftime('%Y-%m', InvoiceDate) AS Month,
  SUM(Total) AS MonthlyRevenue
FROM Invoice
GROUP BY strftime('%Y-%m', InvoiceDate)
ORDER BY Month ASC""",
                    analysis_type="trend",
                    tables=["Invoice"],
                    description="Monthly revenue trajectory",
                )
            ]
        )
        self._profiles["chinook"] = chinook

    def get_profile(self, db_identifier: str = "") -> Optional[DatabaseKnowledge]:
        """Retrieve knowledge profile matching database name or URL substring."""
        if not db_identifier:
            return None
        ident_lower = db_identifier.lower()
        for name, prof in self._profiles.items():
            if name in ident_lower:
                return prof
        return None

    def register_golden_pattern(self, db_identifier: str, pattern: GoldenPattern):
        """Add a verified golden pattern to a database profile."""
        prof = self.get_profile(db_identifier)
        if not prof:
            prof = DatabaseKnowledge(database_name=db_identifier.lower())
            self._profiles[db_identifier.lower()] = prof
        prof.golden_patterns.append(pattern)

    def retrieve_relevant_knowledge(
        self,
        question: str,
        db_identifier: str = "",
        candidate_tables: Optional[List[str]] = None,
        max_patterns: int = 2,
    ) -> Dict[str, Any]:
        """
        Extract relevant domain rules, glossary mappings, and golden SQL examples
        tailored to the user question and candidate tables.
        """
        prof = self.get_profile(db_identifier)
        if not prof:
            return {"rules": [], "glossary": {}, "few_shots": []}

        q_lower = question.lower()
        cand_tables_clean = [t.lower().split(".")[-1] for t in (candidate_tables or [])]

        # 1. Filter matching glossary terms
        matched_glossary = {}
        for term, mapping in prof.glossary.items():
            if term.lower() in q_lower:
                matched_glossary[term] = mapping

        # 2. Filter matching golden patterns
        scored_patterns = []
        for pat in prof.golden_patterns:
            score = 0
            # Table match score
            for t in pat.tables:
                if t.lower() in cand_tables_clean or any(t.lower() in ct for ct in cand_tables_clean):
                    score += 3
            # Keyword match score
            pat_words = set(pat.question.lower().split())
            q_words = set(q_lower.split())
            overlap = len(pat_words & q_words)
            score += overlap

            if score > 0:
                scored_patterns.append((score, pat))

        scored_patterns.sort(key=lambda x: x[0], reverse=True)
        selected_patterns = [p[1] for p in scored_patterns[:max_patterns]]

        return {
            "rules": prof.rules,
            "glossary": matched_glossary,
            "few_shots": selected_patterns,
        }

    def format_prompt_knowledge_section(
        self,
        question: str,
        db_identifier: str = "",
        candidate_tables: Optional[List[str]] = None,
    ) -> str:
        """Format domain rules and golden few-shots for direct prompt injection."""
        data = self.retrieve_relevant_knowledge(
            question=question,
            db_identifier=db_identifier,
            candidate_tables=candidate_tables,
        )
        rules = data.get("rules", [])
        few_shots = data.get("few_shots", [])

        if not rules and not few_shots:
            return ""

        lines = ["=== DOMAIN KNOWLEDGE & GOLDEN PATTERNS ==="]
        if rules:
            lines.append("Database Rules:")
            for r in rules:
                lines.append(f"- {r}")

        if few_shots:
            lines.append("\nVerified Golden SQL Examples:")
            for i, shot in enumerate(few_shots, 1):
                lines.append(f"Example {i} Question: {shot.question}")
                lines.append(f"Example {i} SQL:\n{shot.sql.strip()}\n")

        return "\n".join(lines).strip()


# Global Singleton Knowledge Store
database_knowledge_store = DatabaseKnowledgeStore()
