"""Schema Pruner for building compact grounded schema text."""
from typing import Any, Dict, List, Set
from app.schema_grounding.models import GroundedSchema, Relationship


class SchemaPruner:
    """Prunes unselected tables from database schema and formats compact schema text."""

    def prune_and_format(
        self,
        schema: Dict[str, Any],
        selected_tables: Set[str],
        relationships: List[Relationship],
    ) -> GroundedSchema:
        """
        Build GroundedSchema containing only selected tables and their metadata.

        Args:
            schema: Full database schema dict.
            selected_tables: Set of table names to keep.
            relationships: Full list of FK relationships.

        Returns:
            GroundedSchema: Pruned schema representation.
        """
        if not selected_tables:
            selected_tables = set(schema.keys())

        pruned_tables = sorted(list(selected_tables))
        selected_columns: Dict[str, List[str]] = {}
        filtered_relationships: List[Relationship] = []

        # Filter relevant relationships
        for rel in relationships:
            if rel.source_table in selected_tables and rel.target_table in selected_tables:
                filtered_relationships.append(rel)

        lines = ["Database Schema (Grounded Subset):"]

        for table_name in pruned_tables:
            table_info = schema.get(table_name)
            if not table_info:
                continue

            col_names = [col["name"] for col in table_info.get("columns", [])]
            selected_columns[table_name] = col_names

            lines.append(f"\nTable: {table_name}")
            for col in table_info.get("columns", []):
                col_str = f"  - {col['name']} ({col['type']})"
                if col.get("samples"):
                    col_str += f" -- Sample values: {', '.join(repr(s) for s in col['samples'])}"
                if col.get("date_range"):
                    col_str += f" -- Data range: {col['date_range']}"
                lines.append(col_str)

            pk = table_info.get("primary_key", [])
            if pk:
                lines.append(f"  PK: {', '.join(pk)}")

            for fk in table_info.get("foreign_keys", []):
                ref_t = fk.get("referred_table")
                if ref_t in selected_tables:
                    lines.append(
                        f"  FK: {', '.join(fk.get('constrained_columns', []))} -> "
                        f"{ref_t}({', '.join(fk.get('referred_columns', []))})"
                    )

        schema_text = "\n".join(lines)

        return GroundedSchema(
            selected_tables=pruned_tables,
            selected_columns=selected_columns,
            required_relationships=filtered_relationships,
            schema_text=schema_text,
            pruned_table_count=len(pruned_tables),
            original_table_count=len(schema),
        )
