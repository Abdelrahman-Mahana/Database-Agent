"""Static Arabic <-> English business-noun map used as a zero-cost first line
of defense for schema seed-table matching (app/schema_grounding/grounding_engine.py).

Why this exists, separately from the LLM-generated glossary
(app/schema_catalog/glossary.py):
  - The glossary is powerful (learns the ACTUAL schema's real synonyms,
    including domain-specific ones) but needs one LLM call per database
    before it's useful, and won't exist yet on a brand-new connection.
  - This map costs nothing, needs no setup, and covers the common case
    directly: a Northwind/Chinook-style schema uses ordinary English nouns
    (Customer, Order, Product, Employee...) for its tables, and an Arabic
    question about "العملاء" or "الطلبات" should match them immediately —
    without waiting for glossary enrichment or spending a token.

This is intentionally small and generic (not schema-specific) — it only
covers common relational-database business nouns, not domain jargon. Domain
jargon is exactly what the LLM-generated glossary is for.
"""
from __future__ import annotations

# Arabic term (incl. common colloquial spellings) -> list of English words to
# also search for when matching table/column names & sample values.
ARABIC_BUSINESS_TERMS: dict[str, list[str]] = {
    "عميل": ["customer", "client"],
    "عملاء": ["customer", "client"],
    "زبون": ["customer", "client"],
    "زباين": ["customer", "client"],
    "طلب": ["order"],
    "طلبات": ["order"],
    "اوردر": ["order"],
    "أوردر": ["order"],
    "منتج": ["product", "item"],
    "منتجات": ["product", "item"],
    "بضاعة": ["product", "item"],
    "موظف": ["employee", "staff"],
    "موظفين": ["employee", "staff"],
    "فاتورة": ["invoice", "bill"],
    "فواتير": ["invoice", "bill"],
    "فنان": ["artist"],
    "فنانين": ["artist"],
    "فنانون": ["artist"],
    "اغنية": ["track", "song"],
    "أغنية": ["track", "song"],
    "اغاني": ["track", "song"],
    "أغاني": ["track", "song"],
    "البوم": ["album"],
    "ألبوم": ["album"],
    "سعر": ["price", "unitprice"],
    "اسعار": ["price", "unitprice"],
    "أسعار": ["price", "unitprice"],
    "شحن": ["freight", "shipping"],
    "فئة": ["category"],
    "فئات": ["category"],
    "مورد": ["supplier", "vendor"],
    "موردين": ["supplier", "vendor"],
    "شركة شحن": ["shipper", "carrier"],
    "دولة": ["country"],
    "بلد": ["country"],
    "مدينة": ["city"],
    "قسم": ["department", "category", "region"],
    "منطقة": ["region", "territory"],
    "مبيعات": ["sales", "sale"],
    "ايراد": ["revenue", "total"],
    "إيراد": ["revenue", "total"],
    "الايرادات": ["revenue", "total"],
    "الإيرادات": ["revenue", "total"],
    "مخزون": ["stock", "inventory", "unitsinstock"],
    "كمية": ["quantity"],
    "تاريخ": ["date"],
}


def expand_with_arabic_terms(question_lower: str) -> str:
    """Return the question text with matching Arabic business nouns' English
    equivalents appended, so downstream literal substring matching (table/
    column name matching in the grounding engine) also catches them.

    No-op and cheap for non-Arabic questions (single dict-key scan).
    """
    extra_terms: list[str] = []
    for ar_term, en_terms in ARABIC_BUSINESS_TERMS.items():
        if ar_term in question_lower:
            for term in en_terms:
                extra_terms.append(term)
                # Table names are commonly stored pluralized (Orders,
                # Customers, Products...); the grounding engine's own
                # matcher already tries singular->plural for the TABLE
                # side, but not the other way around, so add the simple
                # plural here too rather than depend on that asymmetry.
                if not term.endswith("s"):
                    extra_terms.append(term + "s")
    if not extra_terms:
        return question_lower
    return question_lower + " " + " ".join(extra_terms)
