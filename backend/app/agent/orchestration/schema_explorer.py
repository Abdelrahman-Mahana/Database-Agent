"""Module for database schema exploration queries — LLM-powered overview + offline detail lookups."""
import re
from typing import Any, Optional
from loguru import logger
from app.services.sql_service import SchemaService
from app.agent.llm.prompts import DATABASE_OVERVIEW_PROMPT


class SchemaExplorer:
    """Detects and resolves database schema queries.
    
    Overview requests use the LLM for intelligent, adaptive analysis.
    Detail lookups (specific table, relationships, comparisons) remain offline.
    """

    def __init__(self, llm=None):
        self.schema_service = SchemaService()
        self._llm = llm  # LangChain BaseChatModel (fast tier)

    def is_schema_query(self, question: str) -> bool:
        """Rule-based check if the question is asking about the schema/structure of the DB."""
        q = question.lower().strip()
        keywords = [
            "schema", "database structure", "tables in", "list tables", 
            "show tables", "columns in", "describe table", "what tables",
            "primary key", "foreign key", "how is * related", "relationships",
            "table details", "relation between",
            "جداول", "الجدول", "اعرض الجداول", "ما هي الجداول", "هيكلية",
            "قاعدة البيانات", "أعمدة", "اعمدة", "المفتاح الأساسي", "المفتاح الأجنبي", "علاقة", "علاقات"
        ]
        if any(k in q for k in keywords):
            return True
        if re.search(r"\b(table|column|schema|field|keys)\b", q):
            return True
        return False

    async def handle_schema_exploration(self, question: str) -> dict[str, Any] | None:
        """Parse schema query, look up details in SchemaService, and return response dict.
        
        Overview requests are routed to the LLM for intelligent analysis.
        Detail lookups (specific table, relationships) remain offline/deterministic.
        """
        q = question.lower().strip()
        schema = self.schema_service.get_schema()
        is_arabic = bool(re.search(r"[\u0600-\u06FF]", question))

        def _match_table(t_name: str, query_text: str) -> bool:
            t_clean = t_name.lower().strip()
            bare = t_clean.split(".")[-1].strip('"')
            return bool(
                re.search(rf"\b{re.escape(t_clean)}\b", query_text)
                or re.search(rf"\b{re.escape(bare)}\b", query_text)
            )

        # 1. Database/schema overview — metadata only, no SQL.
        overview_terms = (
            "list tables", "show tables", "what tables", "database tables", "all tables",
            "database overview", "describe database", "database structure", "schema overview",
            "what data do you have", "what is this database", "explain the data",
            "explain database", "explore database",
            "اشرحلي قواعد البيانات", "اشرح قواعد البيانات", "اشرحلي قاعدة البيانات",
            "اشرح قاعدة البيانات", "اوصفلي قواعد البيانات", "اوصف قواعد البيانات",
            "اوصفلي قاعدة البيانات", "وصف قواعد البيانات", "وصف قاعدة البيانات",
            "اشرحلي الجداول", "اشرح لي الجداول", "اشرح الجداول", "اشرح الجدول",
            "الجداول المتصلة", "الجداول دي", "البيانات المتصلة", "الجداول كلها",
            "فهمني الجداول", "وريني الجداول", "عرفني بالجداول", "كلمني عن الجداول",
            "ما هي الجداول", "ماهي الجداول", "اعرض الجداول", "هيكلية", "هيكل البيانات",
            "الجداول الموجودة", "الجداول المتاحة", "قواعد البيانات الموجودة",
            "اشرحلي البيانات", "اشرح لي البيانات", "اشرح البيانات",
            "اشرحلي الداتا", "اشرح لي الداتا", "اشرح الداتا",
            "البيانات دي", "الداتا دي", "متصل بيها", "متصل بها",
            "عندك ايه", "عندك إيه", "ايه اللي عندك", "إيه اللي عندك",
            "فهمني البيانات", "فهمني الداتا", "وريني البيانات", "وريني الداتا",
            "عرفني بالبيانات", "كلمني عن البيانات", "كلمني عن الداتا",
        )
        if any(x in q for x in overview_terms) and not any(_match_table(t, q) for t in schema.keys()):
            tables = sorted(list(schema.keys()))
            total_tables_count = len(schema)

            # --- LLM-Powered Intelligent Overview ---
            if self._llm is not None:
                try:
                    schema_summary = self._build_schema_summary(schema)
                    prompt_text = DATABASE_OVERVIEW_PROMPT.format(
                        schema_summary=schema_summary,
                        total_tables=total_tables_count,
                        question=question,
                    )
                    from langchain_core.messages import HumanMessage
                    llm_response = await self._llm.ainvoke([HumanMessage(content=prompt_text)])
                    report = llm_response.content.strip()
                    logger.info("LLM-powered schema overview generated successfully (%d chars).", len(report))
                except Exception as llm_err:
                    logger.warning("LLM schema overview failed, falling back to static: %s", llm_err)
                    report = self._build_static_overview(schema, tables, total_tables_count, is_arabic)
            else:
                report = self._build_static_overview(schema, tables, total_tables_count, is_arabic)

            return {
                "question": question,
                "sql": "",
                "results": [{"table_name": t} for t in tables],
                "report": report,
                "chart_suggestion": {"should_chart": False},
                "success": True,
                "error": None,
                "attempted_sql": "",
                "error_type": None,
                "suggestions": []
            }

        # 2. Compare/explain two specific tables using metadata & domain relationship
        comparison_terms = (
            "difference between", "compare table", "الفرق بين", "الفرق", "قارن بين",
            "ايه الفرق", "إيه الفرق", "بينه وبين", "بينها وبين", "vs"
        )
        matched_tables = []
        for table_name in schema.keys():
            if _match_table(table_name, q):
                if table_name not in matched_tables:
                    matched_tables.append(table_name)

        if len(matched_tables) >= 2 and any(term in q for term in comparison_terms):
            a, b = matched_tables[:2]
            a_clean = a.split(".")[-1]
            b_clean = b.split(".")[-1]
            a_cols = {str(c.get("name")) for c in schema[a].get("columns", [])}
            b_cols = {str(c.get("name")) for c in schema[b].get("columns", [])}
            common = sorted(a_cols & b_cols)
            a_only = sorted(a_cols - b_cols)
            b_only = sorted(b_cols - a_cols)

            # Check if there is an explicit foreign key between them
            fk_link = ""
            for fk in schema[b].get("foreign_keys", []):
                ref_tbl = fk.get("referred_table", "").split(".")[-1]
                if ref_tbl == a_clean:
                    col = fk.get("constrained_columns", [""])[0]
                    ref_col = fk.get("referred_columns", ["id"])[0]
                    fk_link = f"يرتبط بـ **{a_clean}** عبر المفتاح `{col} ➔ {ref_col}`"
            for fk in schema[a].get("foreign_keys", []):
                ref_tbl = fk.get("referred_table", "").split(".")[-1]
                if ref_tbl == b_clean:
                    col = fk.get("constrained_columns", [""])[0]
                    ref_col = fk.get("referred_columns", ["id"])[0]
                    fk_link = f"يرتبط بـ **{b_clean}** عبر المفتاح `{col} ➔ {ref_col}`"

            if is_arabic:
                report = (
                    f"الخلاصة: جدول **{a_clean}** هو الجدول الرئيسي (Header/Parent) ويحتوي على {len(a_cols)} عموداً، بينما جدول **{b_clean}** هو جدول البنود والتفاصيل (Lines/Child) ويحتوي على {len(b_cols)} عموداً.\n\n"
                    f"أهم الفروق والعلاقة بينهما:\n"
                    f"- **{a_clean}**: يمثل رأس المستند (مثل رقم الفاتورة، تاريخ الفاتورة، العميل، الإجمالي الكلي للحركة، وحالة الاعتماد).\n"
                    f"- **{b_clean}**: يمثل سطور وبنود المستند (مثل كل منتج أو خدمة تم شراؤها، الحساب المدين/الدائن، الكمية، وسعر البند).\n"
                )
                if fk_link:
                    report += f"- **طبيعة الربط**: العلاقة هي One-to-Many؛ كل سجل في `{a_clean}` يقابله عدة بنود في `{b_clean}`، و{fk_link}.\n"
                if common:
                    report += f"- **أعمدة مشتركة**: `{', '.join(common[:8])}`.\n"
            else:
                report = (
                    f"Summary: **{a_clean}** is the header/parent table ({len(a_cols)} columns), while **{b_clean}** is the line-item/child details table ({len(b_cols)} columns).\n\n"
                    f"Key differences & relationship:\n"
                    f"- **{a_clean}**: Represents the main document header (e.g. invoice reference, date, customer, total amount, state).\n"
                    f"- **{b_clean}**: Represents the granular transaction lines (e.g. products, debit/credit entries, quantities, and line amounts).\n"
                )
                if fk_link:
                    report += f"- **Relationship**: One-to-Many join where each `{a_clean}` record contains multiple items in `{b_clean}`.\n"

            return {
                "question": question,
                "sql": "",
                "results": [{"table": a, "columns_count": len(a_cols)}, {"table": b, "columns_count": len(b_cols)}],
                "report": report,
                "chart_suggestion": {"should_chart": False},
                "success": True,
                "error": None,
                "attempted_sql": "",
                "error_type": None,
                "suggestions": []
            }

        # 3. Ask about a specific table or table columns/relationships
        target_table = matched_tables[0] if matched_tables else None

        if target_table:
            is_relation_query = any(x in q for x in ("relation", "foreign key", "link", "connect", "join", "علاقة", "علاقات", "مرتبطة", "المفتاح الأجنبي"))
            table_info = schema[target_table]

            if is_relation_query:
                links = []
                fks = table_info.get("foreign_keys", [])
                if is_arabic:
                    report = f"# العلاقات المرتبطة بالجدول: {target_table}\n\n"
                    if fks:
                        report += "### المفاتيح الأجنبية الصادرة:\n"
                        for fk in fks:
                            report += f"- العمود `{fk['constrained_columns'][0]}` يُشير إلى **{fk['referred_table']}** (`{fk['referred_columns'][0]}`)\n"
                            links.append({"from": target_table, "to": fk["referred_table"], "key": fk["constrained_columns"][0]})

                    incoming = []
                    for other_table, other_info in schema.items():
                        if other_table == target_table:
                            continue
                        for fk in other_info.get("foreign_keys", []):
                            if fk["referred_table"] == target_table:
                                incoming.append((other_table, fk["constrained_columns"][0], fk["referred_columns"][0]))

                    if incoming:
                        report += "\n### المفاتيح الأجنبية الواردة:\n"
                        for other, local_col, ref_col in incoming:
                            report += f"- **{other}** (`{local_col}`) يُشير إلى عمود `{ref_col}` في هذا الجدول\n"
                            links.append({"from": other, "to": target_table, "key": local_col})

                    if not fks and not incoming:
                        report += "لم يتم العثور على علاقات أو مفاتيح أجنبية صريحة لهذا الجدول.\n"
                else:
                    report = f"# Relationships for table: {target_table}\n\n"
                    if fks:
                        report += "### Outgoing Foreign Keys:\n"
                        for fk in fks:
                            report += f"- `{fk['constrained_columns'][0]}` points to **{fk['referred_table']}** (`{fk['referred_columns'][0]}`)\n"
                            links.append({"from": target_table, "to": fk["referred_table"], "key": fk["constrained_columns"][0]})

                    incoming = []
                    for other_table, other_info in schema.items():
                        if other_table == target_table:
                            continue
                        for fk in other_info.get("foreign_keys", []):
                            if fk["referred_table"] == target_table:
                                incoming.append((other_table, fk["constrained_columns"][0], fk["referred_columns"][0]))

                    if incoming:
                        report += "\n### Incoming Foreign Keys:\n"
                        for other, local_col, ref_col in incoming:
                            report += f"- **{other}** (`{local_col}`) points to this table's `{ref_col}`\n"
                            links.append({"from": other, "to": target_table, "key": local_col})

                    if not fks and not incoming:
                        report += "No explicit relationships/foreign keys found for this table.\n"

                return {
                    "question": question,
                    "sql": "",
                    "results": links,
                    "report": report,
                    "chart_suggestion": {"should_chart": False},
                    "success": True,
                    "error": None,
                    "attempted_sql": "",
                    "error_type": None,
                    "suggestions": []
                }
            else:
                cols = table_info.get("columns", [])
                pks = table_info.get("primary_key", [])
                fks = table_info.get("foreign_keys", [])
                results_list = []
                t_clean = target_table.split(".")[-1]
                
                key_cols = []
                date_cols = []
                amount_cols = []
                other_cols = []
                
                for col in cols:
                    name = col["name"]
                    ctype = col["type"]
                    nullable = col.get("nullable", True)
                    is_pk = name in pks
                    c_lower = name.lower()
                    
                    if is_pk:
                        key_cols.append(f"`{name}`")
                    elif "date" in c_lower or "time" in c_lower:
                        date_cols.append(f"`{name}`")
                    elif any(x in c_lower for x in ("amount", "total", "price", "balance", "debit", "credit", "subtotal", "tax")):
                        amount_cols.append(f"`{name}`")
                    else:
                        other_cols.append(name)
                        
                    results_list.append({"column": name, "type": ctype, "is_pk": is_pk, "nullable": nullable})

                if is_arabic:
                    report = f"الخلاصة: جدول **{t_clean}** يحتوي على **{len(cols)} عموداً** و **{len(fks)} علاقة ربط (Foreign Keys)**.\n\n"
                    report += f"أهم تفاصيل ومكونات الجدول:\n"
                    if key_cols:
                        report += f"- **المفتاح الأساسي**: {', '.join(key_cols)}.\n"
                    if date_cols:
                        report += f"- **أعمدة التواريخ**: {', '.join(date_cols[:5])}.\n"
                    if amount_cols:
                        report += f"- **الأعمدة المالية والكميات**: {', '.join(amount_cols[:6])}.\n"
                    if fks:
                        fk_targets = list({fk['referred_table'].split('.')[-1] for fk in fks})
                        report += f"- **جداول مرتبطة**: يرتبط بـ `{', '.join(fk_targets[:6])}`.\n"
                    if other_cols:
                        report += f"- **أعمدة إضافية**: `{', '.join(other_cols[:8])}` ...\n"
                else:
                    report = f"Summary: Table **{t_clean}** contains **{len(cols)} columns** and **{len(fks)} foreign keys**.\n\n"
                    report += f"Key Schema Highlights:\n"
                    if key_cols:
                        report += f"- **Primary Key**: {', '.join(key_cols)}.\n"
                    if date_cols:
                        report += f"- **Date Fields**: {', '.join(date_cols[:5])}.\n"
                    if amount_cols:
                        report += f"- **Financial & Metric Fields**: {', '.join(amount_cols[:6])}.\n"
                    if fks:
                        fk_targets = list({fk['referred_table'].split('.')[-1] for fk in fks})
                        report += f"- **Related Tables**: Links to `{', '.join(fk_targets[:6])}`.\n"

                return {
                    "question": question,
                    "sql": "",
                    "results": results_list,
                    "report": report,
                    "chart_suggestion": {"should_chart": False},
                    "success": True,
                    "error": None,
                    "attempted_sql": "",
                    "error_type": None,
                    "suggestions": []
                }

        return None

    # ─── Helper Methods ───────────────────────────────────────────────────

    def _build_schema_summary(self, schema: dict, max_detailed_tables: int = 15, max_other_tables: int = 20) -> str:
        """Build a compact, informative schema summary for the LLM.
        
        Strategy:
        - Include ALL table names (just names, lightweight)
        - Include column details for the top N tables (sorted by column count descending,
          since tables with more columns are usually core business tables)
        - Include all foreign key relationships
        """
        lines: list[str] = []
        
        # Sort tables by column count (most columns first = most important)
        tables_by_importance = sorted(
            schema.items(),
            key=lambda item: len(item[1].get("columns", [])),
            reverse=True,
        )
        
        # Section 1: Detailed tables (top N by column count)
        detailed_tables = tables_by_importance[:max_detailed_tables]
        lines.append("=== KEY TABLES (with columns) ===")
        for table_name, table_info in detailed_tables:
            clean_name = table_name.split(".")[-1]
            cols = table_info.get("columns", [])
            col_names = [str(c.get("name", "")) for c in cols[:10]] # limit to 10 cols max per table
            if len(cols) > 10:
                col_names.append("...")
            lines.append(f"\n[{clean_name}] ({len(cols)} columns)")
            lines.append(f"  Columns: {', '.join(col_names)}")
            
            # Include foreign keys for this table
            fks = table_info.get("foreign_keys", [])
            if fks:
                fk_strs = []
                for fk in fks[:5]: # limit to 5 FKs max
                    ref_table = fk.get("referred_table", "").split(".")[-1]
                    constrained = fk.get("constrained_columns", ["?"])[0]
                    referred = fk.get("referred_columns", ["?"])[0]
                    fk_strs.append(f"{constrained} → {ref_table}.{referred}")
                if len(fks) > 5:
                    fk_strs.append("...")
                lines.append(f"  Foreign Keys: {'; '.join(fk_strs)}")
        
        # Section 2: Remaining table names (just names)
        remaining = tables_by_importance[max_detailed_tables:max_detailed_tables+max_other_tables]
        if remaining:
            lines.append(f"\n=== OTHER TABLES (sample of {len(remaining)} additional out of {len(schema)-max_detailed_tables}) ===")
            remaining_names = [t[0].split(".")[-1] for t in remaining]
            lines.append(", ".join(remaining_names))
        
        return "\n".join(lines)

    @staticmethod
    def _build_static_overview(
        schema: dict, tables: list[str], total_tables_count: int, is_arabic: bool
    ) -> str:
        """Fallback static overview when LLM is unavailable."""
        if is_arabic:
            report = (
                f"### 🗄️ نظرة شاملة على قاعدة البيانات المتصلة\n\n"
                f"قاعدة البيانات تحتوي على **{total_tables_count} جدول**. "
                f"إليك أهم الجداول:\n\n"
            )
            for t in tables[:15]:
                cols = schema[t].get("columns", [])
                col_names = [str(c.get("name")) for c in cols[:5]]
                more = "..." if len(cols) > 5 else ""
                report += f"- **{t.split('.')[-1]}** ({len(cols)} عمود): `{', '.join(col_names)}{more}`\n"
            if len(tables) > 15:
                report += f"\n*و {len(tables) - 15} جدول إضافي...*\n"
            report += (
                "\n💡 **اسألني عن أي جدول بالتحديد أو ابدأ بسؤال تحليلي مباشرة!**"
            )
        else:
            report = (
                f"### 🗄️ Database Overview\n\n"
                f"The database contains **{total_tables_count} tables**. "
                f"Here are the key ones:\n\n"
            )
            for t in tables[:15]:
                cols = schema[t].get("columns", [])
                col_names = [str(c.get("name")) for c in cols[:6]]
                more = "..." if len(cols) > 6 else ""
                report += f"- **{t.split('.')[-1]}** ({len(cols)} columns): `{', '.join(col_names)}{more}`\n"
            if len(tables) > 15:
                report += f"\n*... and {len(tables) - 15} more tables.*\n"
            report += (
                "\n💡 **Ask about any specific table or start with an analytical question!**"
            )
        return report
