"""Schema Pruner for building compact grounded schema text with adaptive join coverage."""
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from app.agent.schema_grounding.models import GroundedSchema, Relationship
from app.core.config.settings import settings
from app.core.security.privacy_policy import is_safe_semantic_sample_column, PIIValueSanitizer

# Hard ceiling on schema_text lines sent to the SQL generation LLM.
_MAX_SCHEMA_LINES = 2000
# Max sample values per column in the grounded schema text.
_MAX_SAMPLES_PER_COL = 1
# Max character length for a single sample value string.
_MAX_SAMPLE_CHARS = 20


class SchemaPruner:
    """Prunes unselected tables from database schema and formats compact schema text."""

    def _format_lines(
        self,
        tables_to_format: List[str],
        schema: Dict[str, Any],
        relationships: Optional[List[Relationship]] = None,
        referenced_columns: Optional[Dict[str, Set[str]]] = None,
        include_samples: bool = True,
        max_cols_override: Optional[int] = None,
        seed_tables: Optional[Set[str]] = None,
    ) -> List[str]:
        lines = [f"Database Schema (Grounded Subset - {len(tables_to_format)} Tables):"]

        # 1. Explicit Join Paths section
        if relationships:
            lines.append("")
            lines.append("Join Paths:")
            seen_joins = set()
            for rel in relationships:
                if rel.source_table in tables_to_format and rel.target_table in tables_to_format:
                    join_str = f"  - {rel.source_table}.{rel.source_column} = {rel.target_table}.{rel.target_column}"
                    if join_str not in seen_joins:
                        lines.append(join_str)
                        seen_joins.add(join_str)

        lines.append("")
        lines.append("Tables:")

        max_cols_per_table = max_cols_override or getattr(settings, "grounding_max_cols_per_table", 12)
        ref_cols_map = referenced_columns or {}

        for table_name in tables_to_format:
            table_info = schema.get(table_name)
            if not table_info:
                continue

            pk_set = set(table_info.get("primary_key", []))

            # Map column name to the table it references
            fk_map = {}
            for fk in table_info.get("foreign_keys", []):
                ref_t = fk.get("referred_table")
                if ref_t in tables_to_format:
                    for l_col, r_col in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                        fk_map[l_col] = f"{ref_t}.{r_col}"

            # Ensure all columns participating in active join paths between DIFFERENT tables are preserved
            join_cols = set()
            if relationships:
                for rel in relationships:
                    if rel.source_table == table_name and rel.target_table in tables_to_format and rel.source_table != rel.target_table:
                        join_cols.add(rel.source_column)
                    elif rel.target_table == table_name and rel.source_table in tables_to_format and rel.source_table != rel.target_table:
                        join_cols.add(rel.target_column)

            bare_name = table_name.split(".")[-1]
            active_refs = ref_cols_map.get(table_name, set()) | ref_cols_map.get(bare_name, set())
            all_columns = table_info.get("columns", [])
            col_strings = []

            # High value business column markers
            _CORE_DATE_NAMES = ("date", "invoice_date", "created_at", "create_date", "order_date", "transaction_date")
            _BUSINESS_METRIC_MARKERS = ("amount", "total", "price", "revenue", "cost", "salary", "tax", "balance", "subtotal", "qty", "quantity", "discount", "fee", "rate", "sum", "val", "value", "paid", "remainder", "share")
            _BUSINESS_DATE_MARKERS = ("date", "time", "year", "month", "day", "created", "timestamp", "period")
            _BUSINESS_STATUS_MARKERS = ("state", "status", "type", "name", "ref", "code", "title", "category", "active", "number", "email", "phone", "gender", "age")

            # Prioritize columns:
            # 1. PKs and active Inter-Table Join Path Keys
            # 2. Explicitly referenced query columns (active_refs)
            # 3. Core primary date columns (date, invoice_date, order_date)
            # 4. Numeric metric columns (amounts, prices, revenues, totals)
            # 5. Other temporal date/time columns
            # 6. Business status/name descriptors
            # 7. Relevant FKs
            # 8. Other columns
            pk_and_join_cols = []
            query_ref_cols = []
            core_date_cols = []
            metric_cols = []
            other_date_cols = []
            status_cols = []
            fk_cols = []
            other_cols = []

            for col in all_columns:
                c_name = col["name"]
                name_l = c_name.lower()
                is_noisy_id = name_l.endswith("_uid") or name_l in ("sequence_number", "secure_sequence_number", "message_main_attachment_id", "inalterable_hash", "access_token", "totp_secret", "password")

                if c_name in pk_set or c_name in join_cols:
                    pk_and_join_cols.append(col)
                elif c_name in active_refs:
                    query_ref_cols.append(col)
                elif not is_noisy_id and (name_l in _CORE_DATE_NAMES or name_l == "date" or name_l == "invoice_date"):
                    core_date_cols.append(col)
                elif not is_noisy_id and any(m in name_l for m in _BUSINESS_METRIC_MARKERS):
                    metric_cols.append(col)
                elif not is_noisy_id and any(m in name_l for m in _BUSINESS_DATE_MARKERS):
                    other_date_cols.append(col)
                elif not is_noisy_id and any(m in name_l for m in _BUSINESS_STATUS_MARKERS):
                    status_cols.append(col)
                elif c_name in fk_map and not is_noisy_id:
                    fk_cols.append(col)
                else:
                    other_cols.append(col)

            seen_col_names = set()
            essential = []
            for col in (pk_and_join_cols + query_ref_cols):
                if col["name"] not in seen_col_names:
                    seen_col_names.add(col["name"])
                    essential.append(col)

            # Cap total columns per table (focused queries with <= 3 tables or seed tables get generous headroom)
            is_seed_or_focused = (seed_tables and (table_name in seed_tables or bare_name in seed_tables)) or len(tables_to_format) <= 3
            default_cap = 20 if is_seed_or_focused else max_cols_per_table
            table_cap = max(len(essential), max_cols_override or default_cap)
            
            selected_cols = list(essential)
            for col_group in (core_date_cols, metric_cols, other_date_cols, status_cols, fk_cols, other_cols):
                for col in col_group:
                    if col["name"] not in seen_col_names and len(selected_cols) < table_cap:
                        seen_col_names.add(col["name"])
                        selected_cols.append(col)

            omitted_count = len(all_columns) - len(selected_cols)

            for col in selected_cols:
                c_name = col['name']
                c_type = str(col['type']).upper()
                c_str = f"{c_name}:{c_type}"

                if c_name in pk_set:
                    c_str += " PK"
                if c_name in fk_map:
                    c_str += f" FK->{fk_map[c_name]}"

                is_textual = any(t in c_type for t in ("VARCHAR", "TEXT", "CHAR", "STRING", "ENUM"))
                allow_samples = (
                    include_samples
                    and getattr(settings, "enable_schema_samples", True)
                    and not getattr(settings, "strict_privacy_mode", False)
                )
                if allow_samples and is_textual and col.get("samples") and is_safe_semantic_sample_column(c_name):
                    clean_samples = PIIValueSanitizer.sanitize_samples(
                        col["samples"],
                        max_samples=_MAX_SAMPLES_PER_COL,
                        max_len=_MAX_SAMPLE_CHARS,
                    )
                    if clean_samples:
                        formatted = [repr(s) for s in clean_samples]
                        c_str += f" e.g.{','.join(formatted)}"

                col_strings.append(c_str)

            if omitted_count > 0:
                col_strings.append(f"... (+{omitted_count} columns omitted)")

            lines.append(f"  - {table_name}({', '.join(col_strings)})")

        return lines

    def prune_and_format(
        self,
        schema: Dict[str, Any],
        selected_tables: Set[str],
        relationships: List[Relationship],
        seed_tables: Optional[Set[str]] = None,
        query_understanding: Optional[Any] = None,
    ) -> GroundedSchema:
        """
        Build GroundedSchema with adaptive join coverage preservation.
        Ensures intermediate bridge tables connecting seeds are strictly preserved.
        """
        if not selected_tables:
            selected_tables = set(schema.keys())

        max_final_tables = getattr(settings, "grounding_max_final_tables", 15)
        seeds = seed_tables if seed_tables else set()

        # Calculate active join degree within selected_tables
        table_degree = {t: 0 for t in selected_tables}
        if relationships:
            for rel in relationships:
                if rel.source_table in selected_tables and rel.target_table in selected_tables:
                    table_degree[rel.source_table] += 1
                    table_degree[rel.target_table] += 1

        # If selected_tables exceeds adaptive capacity, prioritize seeds and bridge hubs
        if len(selected_tables) > max_final_tables:
            ranked_tables = sorted(
                selected_tables,
                key=lambda t: (
                    t in seeds,                   # 1. Seed tables directly asked for
                    table_degree.get(t, 0) >= 2,  # 2. Bridge / Junction hubs connecting the seeds
                    table_degree.get(t, 0),       # 3. Higher connection degree
                ),
                reverse=True,
            )
            selected_tables = set(ranked_tables[:max_final_tables])

        pruned_tables = sorted(list(selected_tables))

        # Extract referenced columns from QueryUnderstanding if provided
        referenced_columns: Dict[str, Set[str]] = {}
        if query_understanding:
            for ref in getattr(query_understanding, "metrics", []) + getattr(query_understanding, "dimensions", []):
                if "." in ref:
                    t_part, c_part = ref.split(".", 1)
                    referenced_columns.setdefault(t_part, set()).add(c_part)
            for f in getattr(query_understanding, "filters", []):
                col_ref = getattr(f, "column", "") or ""
                if "." in col_ref:
                    t_part, c_part = col_ref.split(".", 1)
                    referenced_columns.setdefault(t_part, set()).add(c_part)

        # Build consistent relationships matching currently selected tables
        filtered_relationships = [
            rel for rel in relationships
            if rel.source_table in selected_tables and rel.target_table in selected_tables
        ]

        # Stage 0: Initial format
        lines = self._format_lines(
            pruned_tables,
            schema,
            relationships=filtered_relationships,
            referenced_columns=referenced_columns,
            include_samples=True,
            seed_tables=seeds,
        )
        schema_text = "\n".join(lines)
        est_tokens = len(schema_text) // 4
        max_tokens = getattr(settings, "max_schema_tokens", 4000)

        # Hierarchical Token Budget Optimization
        if est_tokens > max_tokens:
            logger.warning(
                "Schema text estimated tokens (%d) exceeds max_schema_tokens (%d). Applying adaptive budget optimization...",
                est_tokens,
                max_tokens,
            )
            # Stage 1: Strip column sample values
            lines = self._format_lines(
                pruned_tables,
                schema,
                relationships=filtered_relationships,
                referenced_columns=referenced_columns,
                include_samples=False,
                seed_tables=seeds,
            )
            schema_text = "\n".join(lines)
            est_tokens = len(schema_text) // 4

            # Stage 2: Column compaction (reduce non-essential columns to 6, then 3 slots)
            if est_tokens > max_tokens:
                for col_slot in (6, 3):
                    lines = self._format_lines(
                        pruned_tables,
                        schema,
                        relationships=filtered_relationships,
                        referenced_columns=referenced_columns,
                        include_samples=False,
                        max_cols_override=col_slot,
                        seed_tables=seeds,
                    )
                    schema_text = "\n".join(lines)
                    est_tokens = len(schema_text) // 4
                    if est_tokens <= max_tokens:
                        break

            # Stage 3: Drop ONLY non-seed, non-bridge leaf tables (degree <= 1) if still over budget
            if est_tokens > max_tokens and len(pruned_tables) > 1:
                # Calculate active degrees
                cur_deg = {t: 0 for t in pruned_tables}
                for rel in filtered_relationships:
                    if rel.source_table in pruned_tables and rel.target_table in pruned_tables:
                        cur_deg[rel.source_table] += 1
                        cur_deg[rel.target_table] += 1

                # Drop candidates: only non-seed leaf tables (degree <= 1)
                drop_candidates = [
                    t for t in pruned_tables
                    if t not in seeds and cur_deg.get(t, 0) <= 1
                ]
                while drop_candidates and (len(schema_text) // 4) > max_tokens and len(pruned_tables) > 1:
                    dropped = drop_candidates.pop()
                    if dropped in pruned_tables:
                        pruned_tables.remove(dropped)
                    # Recompute relationships
                    filtered_relationships = [
                        rel for rel in relationships
                        if rel.source_table in pruned_tables and rel.target_table in pruned_tables
                    ]
                    lines = self._format_lines(
                        pruned_tables,
                        schema,
                        relationships=filtered_relationships,
                        referenced_columns=referenced_columns,
                        include_samples=False,
                        max_cols_override=3,
                    )
                    schema_text = "\n".join(lines)

        # Final dynamic sync of relationships and selected_columns with pruned_tables
        final_relationships = [
            rel for rel in relationships
            if rel.source_table in pruned_tables and rel.target_table in pruned_tables
        ]
        selected_columns = {
            t: [col["name"] for col in schema[t].get("columns", [])]
            for t in pruned_tables if t in schema
        }

        logger.debug(
            "Schema pruner: %d tables, %d lines in schema_text, %d relationships",
            len(pruned_tables), len(lines), len(final_relationships),
        )

        return GroundedSchema(
            selected_tables=pruned_tables,
            selected_columns={t: cols for t, cols in selected_columns.items() if t in pruned_tables},
            required_relationships=final_relationships,
            schema_text=schema_text,
            pruned_table_count=len(pruned_tables),
            original_table_count=len(schema),
        )
