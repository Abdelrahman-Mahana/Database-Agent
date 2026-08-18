"""Schema Pruner for building compact grounded schema text."""
from typing import Any, Dict, List, Optional, Set


from loguru import logger

from app.schema_grounding.models import GroundedSchema, Relationship
from app.config.settings import settings

# Hard ceiling on schema_text lines sent to the SQL generation LLM.
# ~2000 lines ≈ ~8-10k tokens — comfortably within even the smallest
# context windows while carrying enough detail for accurate SQL.
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

        max_cols_per_table = getattr(settings, "grounding_max_cols_per_table", 12)
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

            # Ensure all columns participating in active join paths are preserved
            join_cols = set()
            if relationships:
                for rel in relationships:
                    if rel.source_table == table_name and rel.target_table in tables_to_format:
                        join_cols.add(rel.source_column)
                    elif rel.target_table == table_name and rel.source_table in tables_to_format:
                        join_cols.add(rel.target_column)

            active_refs = ref_cols_map.get(table_name, set())
            all_columns = table_info.get("columns", [])
            col_strings = []

            # Prioritize columns: PKs, FKs, Join Path Keys, and explicitly referenced query columns
            essential_cols = []
            other_cols = []
            for col in all_columns:
                c_name = col["name"]
                if c_name in pk_set or c_name in fk_map or c_name in active_refs or c_name in join_cols:
                    essential_cols.append(col)
                else:
                    other_cols.append(col)

            # Cap total columns per table if table is very wide
            total_allowed = max(len(essential_cols), max_cols_per_table)
            remaining_slots = max(0, total_allowed - len(essential_cols))
            selected_cols = essential_cols + other_cols[:remaining_slots]
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
                if include_samples and is_textual and col.get("samples"):
                    samples = col["samples"][:_MAX_SAMPLES_PER_COL]
                    truncated = [
                        (repr(s)[:_MAX_SAMPLE_CHARS] + "…'" if len(repr(s)) > _MAX_SAMPLE_CHARS else repr(s))
                        for s in samples
                    ]
                    c_str += f" e.g.{','.join(truncated)}"

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
        Build GroundedSchema containing only 3-8 selected tables, explicit join paths, and required columns.
        Ensures intermediate bridge tables connecting seeds are strictly preserved.
        """
        if not selected_tables:
            selected_tables = set(schema.keys())

        # Enforce strict 3-8 table cap on final context sent to LLM while protecting bridge tables
        max_final_tables = getattr(settings, "grounding_max_final_tables", 8)
        if len(selected_tables) > max_final_tables:
            seeds = seed_tables if seed_tables else set()

            # Calculate active join degree within selected_tables
            table_degree = {t: 0 for t in selected_tables}
            if relationships:
                for rel in relationships:
                    if rel.source_table in selected_tables and rel.target_table in selected_tables:
                        table_degree[rel.source_table] += 1
                        table_degree[rel.target_table] += 1

            # Prioritize seeds first, then bridge tables (degree >= 2), then higher degree
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

        selected_columns: Dict[str, List[str]] = {
            t: [col["name"] for col in schema[t].get("columns", [])]
            for t in pruned_tables if t in schema
        }
        filtered_relationships: List[Relationship] = [
            rel for rel in relationships
            if rel.source_table in selected_tables and rel.target_table in selected_tables
        ]

        lines = self._format_lines(
            pruned_tables,
            schema,
            relationships=filtered_relationships,
            referenced_columns=referenced_columns,
            include_samples=True,
        )
        schema_text = "\n".join(lines)
        est_tokens = len(schema_text) // 4
        max_tokens = getattr(settings, "max_schema_tokens", 4000)

        if est_tokens > max_tokens:
            logger.warning(
                "Schema text estimated tokens (%d) exceeds max_schema_tokens (%d). Applying budget optimization...",
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
            )
            schema_text = "\n".join(lines)
            est_tokens = len(schema_text) // 4

            # Stage 2: If still over budget, drop non-seed intermediate tables
            if est_tokens > max_tokens and len(pruned_tables) > 1:
                seeds = seed_tables if seed_tables else set()
                drop_candidates = sorted(pruned_tables, key=lambda t: (t in seeds, t))
                while len(pruned_tables) > 1 and (len(schema_text) // 4) > max_tokens:
                    dropped_table = drop_candidates.pop()
                    if dropped_table in pruned_tables:
                        pruned_tables.remove(dropped_table)
                    lines = self._format_lines(
                        pruned_tables,
                        schema,
                        relationships=filtered_relationships,
                        referenced_columns=referenced_columns,
                        include_samples=False,
                    )
                    schema_text = "\n".join(lines)
                lines.append("\n... (additional tables omitted for token budget)")
                schema_text = "\n".join(lines)

        logger.debug(
            "Schema pruner: %d tables, %d lines in schema_text",
            len(pruned_tables), len(lines),
        )

        return GroundedSchema(
            selected_tables=pruned_tables,
            selected_columns={t: cols for t, cols in selected_columns.items() if t in pruned_tables},
            required_relationships=filtered_relationships,
            schema_text=schema_text,
            pruned_table_count=len(pruned_tables),
            original_table_count=len(schema),
        )



