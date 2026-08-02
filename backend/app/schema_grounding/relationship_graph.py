"""Relationship Graph for database schema traversal and minimal join path expansion."""
from collections import deque
from typing import Any, Dict, List, Set, Tuple
from app.schema_grounding.models import Relationship


class SchemaRelationshipGraph:
    """Builds an undirected graph of table relationships to discover minimal join paths."""

    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
        self.adj_list: Dict[str, List[Tuple[str, str, str]]] = {}  # table -> [(neighbor, src_col, tgt_col)]
        self.relationships: List[Relationship] = []
        self._build_graph()

    def _build_graph(self) -> None:
        for table_name, table_info in self.schema.items():
            if table_name not in self.adj_list:
                self.adj_list[table_name] = []

            for fk in table_info.get("foreign_keys", []):
                ref_table = fk.get("referred_table")
                constrained_cols = fk.get("constrained_columns", [])
                ref_cols = fk.get("referred_columns", [])

                if ref_table and constrained_cols and ref_cols:
                    src_col = constrained_cols[0]
                    tgt_col = ref_cols[0]

                    rel = Relationship(
                        source_table=table_name,
                        source_column=src_col,
                        target_table=ref_table,
                        target_column=tgt_col,
                    )
                    self.relationships.append(rel)

                    self.adj_list[table_name].append((ref_table, src_col, tgt_col))
                    if ref_table not in self.adj_list:
                        self.adj_list[ref_table] = []
                    self.adj_list[ref_table].append((table_name, tgt_col, src_col))

    def find_shortest_path(self, start_table: str, end_table: str) -> List[str]:
        """Find shortest table path between start_table and end_table using BFS."""
        if start_table == end_table:
            return [start_table]
        if start_table not in self.adj_list or end_table not in self.adj_list:
            return []

        queue = deque([[start_table]])
        visited = {start_table}

        while queue:
            path = queue.popleft()
            node = path[-1]

            if node == end_table:
                return path

            for neighbor, _, _ in self.adj_list.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)

        return []

    def get_minimal_connecting_tables(self, seed_tables: Set[str]) -> Set[str]:
        """
        Given a set of seed target tables, return the minimal set of tables
        including all intermediate junction tables required to connect them.
        """
        valid_seeds = {t for t in seed_tables if t in self.schema}
        if not valid_seeds:
            return set(self.schema.keys())

        if len(valid_seeds) == 1:
            return valid_seeds

        result_tables = set(valid_seeds)
        seed_list = list(valid_seeds)

        for i in range(len(seed_list)):
            for j in range(i + 1, len(seed_list)):
                path = self.find_shortest_path(seed_list[i], seed_list[j])
                if path:
                    result_tables.update(path)

        return result_tables

    def get_direct_neighbors(self, table: str) -> Set[str]:
        """Return the set of tables directly FK-connected to `table` (one hop).

        Used to widen seed tables for analysis types (COMPARISON, TREND,
        ROOT_CAUSE, MULTI_STEP) where the question's literal wording usually
        names only one side of the join that's actually needed — e.g.
        "compare sales performance between employees" names Employees, but
        computing "performance" requires the linked Orders/Invoice table too.
        """
        return {neighbor for neighbor, _, _ in self.adj_list.get(table, [])}

    def get_most_central_tables(self, limit: int = 15) -> Set[str]:
        """
        Return the top `limit` most central tables based on incoming + outgoing FK relationships.
        Used as a fallback for massive databases when no semantic seed tables are found.
        """
        degree = {t: 0 for t in self.schema.keys()}
        for t, neighbors in self.adj_list.items():
            degree[t] += len(neighbors)
        
        # Sort by degree descending
        sorted_tables = sorted(degree.keys(), key=lambda k: degree[k], reverse=True)
        return set(sorted_tables[:limit])
