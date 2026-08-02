"""Module for offline database schema exploration queries."""
import re
from typing import Any
from app.services.sql_service import SchemaService


class SchemaExplorer:
    """Detects and resolves database schema queries directly from metadata without LLM calls."""

    def __init__(self):
        self.schema_service = SchemaService()

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

    def handle_schema_exploration(self, question: str) -> dict[str, Any] | None:
        """Parse schema query, look up details in SchemaService, and return response dict."""
        q = question.lower().strip()
        schema = self.schema_service.get_schema()
        is_arabic = bool(re.search(r"[\u0600-\u06FF]", question))
        
        # 1. Ask for all tables list
        if any(x in q for x in ("list tables", "show tables", "what tables", "database tables", "all tables", "جداول", "الجدول", "اعرض الجداول", "ما هي الجداول", "هيكلية")):
            tables = sorted(list(schema.keys()))
            if is_arabic:
                report = "# نظرة عامة على هيكل قاعدة البيانات\n\nتحتوي قاعدة البيانات على الجداول التالية:\n\n"
                for t in tables:
                    col_count = len(schema[t]["columns"])
                    pk = ", ".join(schema[t].get("primary_key", []))
                    report += f"- **{t}** ({col_count} أعمدة، المفتاح الأساسي: `{pk}`)\n"
            else:
                report = "# Database Schema Overview\n\nThe database contains the following tables:\n\n"
                for t in tables:
                    col_count = len(schema[t]["columns"])
                    pk = ", ".join(schema[t].get("primary_key", []))
                    report += f"- **{t}** ({col_count} columns, Primary Key: `{pk}`)\n"
            
            return {
                "question": question,
                "sql": "-- Schema Exploration (No SQL Executed)",
                "results": [{"table_name": t} for t in tables],
                "report": report,
                "chart_suggestion": {"should_chart": False},
                "success": True,
                "error": None,
                "attempted_sql": "",
                "error_type": None,
                "suggestions": []
            }

        # 2. Ask about a specific table or table columns/relationships
        target_table = None
        for table_name in schema.keys():
            if re.search(rf"\b{table_name.lower()}\b", q):
                target_table = table_name
                break

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
                    "sql": f"-- Relationship Schema Exploration for {target_table}",
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
                cols = table_info["columns"]
                pks = table_info.get("primary_key", [])
                results_list = []
                if is_arabic:
                    report = f"# أعمدة الجدول: {target_table}\n\n"
                    for col in cols:
                        name = col["name"]
                        ctype = col["type"]
                        nullable = col.get("nullable", True)
                        is_pk = name in pks
                        pk_str = "🔑 مفتاح أساسي (PK)" if is_pk else ""
                        null_str = "يقبل NULL" if nullable else "لا يقبل الفراغ (NOT NULL)"
                        report += f"- **{name}** (`{ctype}`) {pk_str} {null_str}\n"
                        results_list.append({"column": name, "type": ctype, "is_pk": is_pk, "nullable": nullable})
                else:
                    report = f"# Table Columns: {target_table}\n\n"
                    for col in cols:
                        name = col["name"]
                        ctype = col["type"]
                        nullable = col.get("nullable", True)
                        is_pk = name in pks
                        pk_str = "🔑 PK" if is_pk else ""
                        null_str = "NULL" if nullable else "NOT NULL"
                        report += f"- **{name}** (`{ctype}`) {pk_str} {null_str}\n"
                        results_list.append({"column": name, "type": ctype, "is_pk": is_pk, "nullable": nullable})

                return {
                    "question": question,
                    "sql": f"-- Column Schema Exploration for {target_table}",
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
