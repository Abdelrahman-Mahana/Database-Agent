"""Enterprise Business Metric Registry.

Bridges the semantic gap between natural language business concepts (e.g. "إيرادات",
"total revenue", "AOV", "profit margin", "عدد العملاء", "ARPU") and physical schema formulas (e.g. SUM(invoices.total)).
Decouples business metric logic from physical database column and table names.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Set
from loguru import logger

from app.agent.semantic.contract import MetricSpec, FormulaType


class BusinessMetricDefinition:
    """Enterprise definition for a business metric template."""

    def __init__(
        self,
        metric_id: str,
        display_name: str,
        display_name_ar: str,
        formula_type: FormulaType,
        aliases_en: List[str],
        aliases_ar: List[str],
        candidate_columns: List[str],
        candidate_tables: List[str],
        unit: Optional[str] = "currency",
        default_expression: str = "",
        description: str = "",
        is_composite: bool = False,
        composite_formula: Optional[str] = None,
        is_additive: bool = True,
        certified: bool = True,
    ):
        self.metric_id = metric_id
        self.display_name = display_name
        self.display_name_ar = display_name_ar
        self.formula_type = formula_type
        self.aliases_en = [a.lower() for a in aliases_en]
        self.aliases_ar = [a.lower() for a in aliases_ar]
        self.candidate_columns = [c.lower() for c in candidate_columns]
        self.candidate_tables = [t.lower() for t in candidate_tables]
        self.unit = unit
        self.default_expression = default_expression
        self.description = description
        self.is_composite = is_composite
        self.composite_formula = composite_formula
        self.is_additive = is_additive
        self.certified = certified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "display_name": self.display_name,
            "display_name_ar": self.display_name_ar,
            "formula_type": self.formula_type.value if hasattr(self.formula_type, "value") else str(self.formula_type),
            "aliases_en": self.aliases_en,
            "aliases_ar": self.aliases_ar,
            "candidate_columns": self.candidate_columns,
            "candidate_tables": self.candidate_tables,
            "unit": self.unit,
            "description": self.description,
            "is_composite": self.is_composite,
            "certified": self.certified,
        }


class BusinessMetricRegistry:
    """
    Central repository of enterprise business metrics.
    Resolves natural language metric requests into concrete MetricSpec instances
    grounded in the active database schema without hardcoding column names in caller logic.
    """

    def __init__(self):
        self._definitions: Dict[str, BusinessMetricDefinition] = {}
        self._custom_definitions: Dict[str, BusinessMetricDefinition] = {}
        self._register_default_metrics()

    def _register_default_metrics(self):
        """Register canonical enterprise metric templates."""
        # 1. Total Revenue / Gross Sales
        self.register(BusinessMetricDefinition(
            metric_id="revenue",
            display_name="Total Revenue",
            display_name_ar="إجمالي الإيرادات",
            formula_type=FormulaType.SUM,
            aliases_en=["revenue", "sales", "total sales", "turnover", "total revenue", "income", "sales amount", "gross sales", "total income"],
            aliases_ar=["إيراد", "إيرادات", "مبيعات", "إجمالي المبيعات", "دخل", "المبيعات", "الإيرادات", "مبلغ المبيعات", "حجم المبيعات", "المردود"],
            candidate_columns=["total", "amount", "amount_total", "price", "unitprice", "line_total", "subtotal", "gross_amount", "sale_price"],
            candidate_tables=["invoices", "invoice", "account_move", "orders", "order", "sales", "sale_order", "invoice_line", "invoiceline", "payments"],
            unit="currency",
            description="Total gross monetary value generated from sales/invoices.",
        ))

        # 2. Net Revenue / Net Sales
        self.register(BusinessMetricDefinition(
            metric_id="net_revenue",
            display_name="Net Revenue",
            display_name_ar="صافي الإيرادات",
            formula_type=FormulaType.SUM,
            aliases_en=["net revenue", "net sales", "net income", "net amount"],
            aliases_ar=["صافي الإيرادات", "صافي المبيعات", "صافي الدخل", "المبيعات الصافية"],
            candidate_columns=["net_amount", "subtotal", "amount_untaxed", "total", "amount"],
            candidate_tables=["invoices", "invoice", "orders", "order", "sales"],
            unit="currency",
            description="Total revenue after discounts and returns.",
        ))

        # 3. Average Order / Invoice Value (AOV)
        self.register(BusinessMetricDefinition(
            metric_id="average_order_value",
            display_name="Average Order Value",
            display_name_ar="متوسط قيمة الفاتورة",
            formula_type=FormulaType.AVG,
            aliases_en=["average order value", "aov", "average sale", "average invoice", "avg spend", "average transaction", "mean order value"],
            aliases_ar=["متوسط الفاتورة", "متوسط المبيعات", "متوسط الطلب", "معدل الشراء", "متوسط قيمة الطلب", "متوسط المعاملة"],
            candidate_columns=["total", "amount", "amount_total", "price"],
            candidate_tables=["invoices", "invoice", "account_move", "orders", "order", "sales"],
            unit="currency",
            description="Average monetary value per transaction or invoice.",
        ))

        # 4. Order / Transaction Count
        self.register(BusinessMetricDefinition(
            metric_id="order_count",
            display_name="Order Count",
            display_name_ar="عدد الفواتير / الطلبات",
            formula_type=FormulaType.COUNT,
            aliases_en=["order count", "orders count", "number of orders", "invoice count", "invoices count", "number of invoices", "transaction count", "total orders", "total invoices"],
            aliases_ar=["عدد الطلبات", "عدد الفواتير", "عدد المعاملات", "حجم الطلبات", "إجمالي الطلبات", "إجمالي الفواتير", "كمية الطلبات"],
            candidate_columns=["invoiceid", "invoice_id", "orderid", "order_id", "id", "move_id"],
            candidate_tables=["invoices", "invoice", "account_move", "orders", "order", "sales"],
            unit="count",
            description="Total number of discrete orders or invoices.",
        ))

        # 5. Customer Count (Unique / Distinct)
        self.register(BusinessMetricDefinition(
            metric_id="customer_count",
            display_name="Customer Count",
            display_name_ar="عدد العملاء",
            formula_type=FormulaType.COUNT_DISTINCT,
            aliases_en=["customer count", "number of customers", "unique customers", "client count", "clients count", "total customers", "distinct customers"],
            aliases_ar=["عدد العملاء", "العملاء الفريدين", "حجم العملاء", "عدد الزبائن", "إجمالي العملاء", "المستخدمين"],
            candidate_columns=["customerid", "customer_id", "partner_id", "client_id", "user_id", "id"],
            candidate_tables=["customers", "customer", "res_partner", "users", "clients", "invoices", "orders"],
            unit="count",
            description="Count of distinct customers or accounts.",
        ))

        # 6. Active Customers
        self.register(BusinessMetricDefinition(
            metric_id="active_customers",
            display_name="Active Customers",
            display_name_ar="عدد العملاء النشطين",
            formula_type=FormulaType.COUNT_DISTINCT,
            aliases_en=["active customers", "active clients", "active users", "current customers"],
            aliases_ar=["العملاء النشطين", "الزبائن النشطين", "المستخدمين النشطين", "العملاء الحاليين"],
            candidate_columns=["customerid", "customer_id", "partner_id", "id"],
            candidate_tables=["invoices", "orders", "customers"],
            unit="count",
            description="Number of distinct customers with transactions.",
        ))

        # 7. Quantity Sold / Volume
        self.register(BusinessMetricDefinition(
            metric_id="quantity_sold",
            display_name="Quantity Sold",
            display_name_ar="الكمية المباعة",
            formula_type=FormulaType.SUM,
            aliases_en=["quantity sold", "units sold", "quantity", "total quantity", "volume", "total units"],
            aliases_ar=["الكمية المباعة", "عدد الوحدات المباعة", "إجمالي الكمية", "الكميات", "حجم المبيعات بالوحدات", "عدد القطع"],
            candidate_columns=["quantity", "qty", "units", "count", "product_uom_qty"],
            candidate_tables=["invoiceline", "invoice_line", "order_items", "order_line", "sales_lines"],
            unit="units",
            description="Total number of product units sold.",
        ))

        # 8. Item / Product / Track Count
        self.register(BusinessMetricDefinition(
            metric_id="item_count",
            display_name="Item Count",
            display_name_ar="عدد الأصناف / المنتجات",
            formula_type=FormulaType.COUNT,
            aliases_en=["item count", "number of items", "product count", "track count", "number of tracks", "number of songs", "catalog size"],
            aliases_ar=["عدد المنتجات", "عدد الأصناف", "عدد الأغاني", "عدد المسارات", "إجمالي الأصناف"],
            candidate_columns=["trackid", "track_id", "product_id", "item_id", "id"],
            candidate_tables=["tracks", "track", "products", "product_product", "items", "catalog"],
            unit="count",
            description="Total count of catalog products or items.",
        ))

        # 9. Gross Profit Margin
        self.register(BusinessMetricDefinition(
            metric_id="profit_margin",
            display_name="Profit Margin",
            display_name_ar="هامش الربح",
            formula_type=FormulaType.PERCENTAGE,
            aliases_en=["profit margin", "gross margin", "margin percentage", "margin pct", "margin"],
            aliases_ar=["هامش الربح", "نسبة الربح", "هامش المبيعات", "معدل الهامش"],
            candidate_columns=["margin", "profit_margin", "profit", "total"],
            candidate_tables=["sales", "invoices", "orders"],
            unit="percentage",
            description="Profit margin expressed as a percentage.",
            is_composite=True,
        ))

        # 10. Average Revenue Per User (ARPU)
        self.register(BusinessMetricDefinition(
            metric_id="arpu",
            display_name="Average Revenue Per User",
            display_name_ar="متوسط العائد لكل عميل",
            formula_type=FormulaType.RATIO,
            aliases_en=["arpu", "average revenue per user", "revenue per customer", "customer spend"],
            aliases_ar=["متوسط العائد لكل عميل", "عائد العميل", "متوسط دخل العميل"],
            candidate_columns=["total", "amount"],
            candidate_tables=["invoices", "orders", "customers"],
            unit="currency",
            description="Total revenue divided by unique customers.",
            is_composite=True,
        ))

        # 11. Discount Amount
        self.register(BusinessMetricDefinition(
            metric_id="discount_amount",
            display_name="Total Discount",
            display_name_ar="إجمالي الخصومات",
            formula_type=FormulaType.SUM,
            aliases_en=["discount", "total discount", "discounts", "discount amount", "rebates"],
            aliases_ar=["الخصم", "إجمالي الخصم", "قيمة الخصومات", "الخصومات", "التخفيضات"],
            candidate_columns=["discount", "discount_amount", "rebate"],
            candidate_tables=["invoiceline", "invoice_line", "order_items", "orders", "invoices"],
            unit="currency",
            description="Total monetary value of discounts applied.",
        ))

    def register(self, definition: BusinessMetricDefinition):
        """Register or override a business metric definition."""
        self._definitions[definition.metric_id] = definition

    def register_custom_metric(
        self,
        metric_id: str,
        display_name: str,
        display_name_ar: str,
        formula_type: FormulaType,
        aliases_en: List[str],
        aliases_ar: List[str],
        candidate_columns: List[str],
        candidate_tables: List[str],
        unit: Optional[str] = "currency",
        description: str = "",
    ) -> BusinessMetricDefinition:
        """Dynamically register a domain-specific custom business metric."""
        metric_def = BusinessMetricDefinition(
            metric_id=metric_id,
            display_name=display_name,
            display_name_ar=display_name_ar,
            formula_type=formula_type,
            aliases_en=aliases_en,
            aliases_ar=aliases_ar,
            candidate_columns=candidate_columns,
            candidate_tables=candidate_tables,
            unit=unit,
            description=description,
            certified=True,
        )
        self._custom_definitions[metric_id] = metric_def
        self._definitions[metric_id] = metric_def
        logger.info("Registered custom business metric: %s (%s)", metric_id, display_name)
        return metric_def

    def get_all_metrics(self) -> List[BusinessMetricDefinition]:
        """Return all registered metric definitions."""
        return list(self._definitions.values())

    def resolve_metrics(
        self,
        text: str,
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
    ) -> List[MetricSpec]:
        """
        Extract and resolve ALL business metric concepts in natural language text (English/Arabic),
        grounding each against the active physical schema.
        """
        text_lower = (text or "").lower().strip()
        if not text_lower:
            return []

        resolved: List[MetricSpec] = []
        matched_ids: Set[str] = set()

        for mdef in self._definitions.values():
            if mdef.metric_id in matched_ids:
                continue

            # 1. Check exact word boundaries
            matched = False
            for alias in mdef.aliases_en:
                if re.search(rf"\b{re.escape(alias)}\b", text_lower):
                    matched = True
                    break

            if not matched:
                # 2. Check Arabic aliases and prefixed variants (e.g. "إجمالي الإيرادات", "كمية المبيعات")
                for alias in mdef.aliases_ar:
                    if alias in text_lower:
                        matched = True
                        break

            if matched:
                spec = self._ground_metric_definition(mdef, text, schema, candidate_tables)
                if spec:
                    resolved.append(spec)
                    matched_ids.add(mdef.metric_id)

        return resolved

    def resolve_metric(
        self,
        text: str,
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
    ) -> Optional[MetricSpec]:
        """Resolve the primary single business metric in a natural language phrase."""
        specs = self.resolve_metrics(text, schema, candidate_tables)
        return specs[0] if specs else None

    def _ground_metric_definition(
        self,
        mdef: BusinessMetricDefinition,
        text: str,
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> MetricSpec:
        """Ground the abstract metric definition to physical tables and columns in schema."""
        source_table, source_column = self._ground_to_schema(
            mdef, schema, candidate_tables
        )

        display_name = (
            mdef.display_name_ar
            if any("\u0600" <= c <= "\u06FF" for c in text)
            else mdef.display_name
        )

        # Build canonical SQL formula representation
        if source_table and source_column:
            qualified_target = f"{source_table}.{source_column}"
        else:
            qualified_target = source_column or mdef.metric_id

        if mdef.formula_type == FormulaType.SUM:
            expression = f"SUM({qualified_target})"
        elif mdef.formula_type == FormulaType.AVG:
            expression = f"AVG({qualified_target})"
        elif mdef.formula_type == FormulaType.COUNT_DISTINCT:
            expression = f"COUNT(DISTINCT {qualified_target})"
        elif mdef.formula_type == FormulaType.COUNT:
            expression = f"COUNT({qualified_target})"
        elif mdef.formula_type == FormulaType.MIN:
            expression = f"MIN({qualified_target})"
        elif mdef.formula_type == FormulaType.MAX:
            expression = f"MAX({qualified_target})"
        elif mdef.formula_type == FormulaType.PERCENTAGE:
            expression = f"SUM({qualified_target}) * 100.0"
        else:
            expression = qualified_target

        return MetricSpec(
            metric_id=mdef.metric_id,
            display_name=display_name,
            formula_type=mdef.formula_type,
            source_table=source_table,
            source_column=source_column,
            expression=expression,
            requires_distinct=(mdef.formula_type == FormulaType.COUNT_DISTINCT),
            unit=mdef.unit,
            aliases=mdef.aliases_en + mdef.aliases_ar,
        )

    def _ground_to_schema(
        self,
        mdef: BusinessMetricDefinition,
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Identify the best matching table and column in schema."""
        if not schema:
            t = candidate_tables[0] if candidate_tables else (mdef.candidate_tables[0] if mdef.candidate_tables else None)
            c = mdef.candidate_columns[0] if mdef.candidate_columns else None
            return t, c

        schema_tables = {t.lower(): t for t in schema.keys()}

        # 1. Prioritize candidate tables from caller / context
        search_tables = []
        if candidate_tables:
            for ct in candidate_tables:
                if ct.lower() in schema_tables:
                    search_tables.append(schema_tables[ct.lower()])

        # 2. Check candidate tables registered in metric definition
        for ct in mdef.candidate_tables:
            if ct in schema_tables and schema_tables[ct] not in search_tables:
                search_tables.append(schema_tables[ct])

        # 3. If none matched, check all tables in schema
        if not search_tables:
            search_tables = list(schema.values()) if isinstance(next(iter(schema.values()), None), str) else list(schema.keys())

        # 4. Look for candidate columns in prioritized tables
        for table_name in search_tables:
            table_info = schema.get(table_name) or {}
            columns = []
            if isinstance(table_info, dict):
                columns = [col.get("name") if isinstance(col, dict) else str(col) for col in table_info.get("columns", [])]
            elif isinstance(table_info, list):
                columns = [c.get("name") if isinstance(c, dict) else str(c) for c in table_info]

            col_map = {c.lower(): c for c in columns}
            for candidate_col in mdef.candidate_columns:
                if candidate_col in col_map:
                    return table_name, col_map[candidate_col]

        # 5. If table exists but column was not found in schema, return table with None column
        for ct in mdef.candidate_tables:
            if ct in schema_tables:
                return schema_tables[ct], None

        return None, None


# Global registry singleton
business_metric_registry = BusinessMetricRegistry()
