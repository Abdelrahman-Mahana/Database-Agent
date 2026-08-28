"""Relationship Graph for database schema traversal and minimal join path expansion."""
from collections import deque
from typing import Any, Dict, List, Set, Tuple
from app.agent.schema_grounding.models import Relationship


class SchemaRelationshipGraph:
    """Builds an undirected graph of table relationships to discover minimal join paths."""

    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
        self.adj_list: Dict[str, List[Tuple[str, str, str]]] = {}  # table -> [(neighbor, src_col, tgt_col)]
        self.relationships: List[Relationship] = []
        self._path_cache: Dict[Tuple[str, str], List[str]] = {}  # (u, v) -> shortest path
        self._build_graph()

    def _build_graph(self) -> None:
        table_lookup = {t.split(".")[-1]: t for t in self.schema.keys()}
        table_lookup.update({t: t for t in self.schema.keys()})

        for table_name, table_info in self.schema.items():
            if table_name not in self.adj_list:
                self.adj_list[table_name] = []

            for fk in table_info.get("foreign_keys", []):
                ref_raw = fk.get("referred_table")
                ref_table = table_lookup.get(ref_raw, ref_raw)
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
        """Find shortest table path between start_table and end_table using memoized BFS."""
        if start_table == end_table:
            return [start_table]
        if start_table not in self.adj_list or end_table not in self.adj_list:
            return []

        # 1. Check in-memory path cache
        cache_key = (min(start_table, end_table), max(start_table, end_table))
        if cache_key in self._path_cache:
            cached_path = self._path_cache[cache_key]
            return cached_path if cached_path[0] == start_table else list(reversed(cached_path))

        # 2. Check 1-hop direct neighbor (O(1))
        for neighbor, _, _ in self.adj_list[start_table]:
            if neighbor == end_table:
                path = [start_table, end_table]
                self._path_cache[cache_key] = path
                return path

        # 3. BFS search
        queue = deque([start_table])
        parent: Dict[str, Optional[str]] = {start_table: None}

        found = False
        while queue:
            curr = queue.popleft()
            if curr == end_table:
                found = True
                break

            for neighbor, _, _ in self.adj_list.get(curr, []):
                if neighbor not in parent:
                    parent[neighbor] = curr
                    queue.append(neighbor)

        if not found:
            self._path_cache[cache_key] = []
            return []

        # Reconstruct path
        path = []
        node: Optional[str] = end_table
        while node is not None:
            path.append(node)
            node = parent[node]
        path.reverse()

        self._path_cache[cache_key] = path
        return path

    def get_minimal_connecting_tables(self, seed_tables: Set[str]) -> Set[str]:
        """
        Given a set of seed target tables, return the minimal set of tables
        including all intermediate junction tables required to connect them.

        Optimized with Multi-Source Steiner-Tree Growth:
        Runs at most (N-1) multi-source BFS expansions instead of O(N^2) pairwise BFS.
        """
        valid_seeds = {t for t in seed_tables if t in self.schema}
        if not valid_seeds:
            return set(self.schema.keys())

        if len(valid_seeds) == 1:
            return valid_seeds

        # 1. Pick root seed (prefer most connected hub table)
        root = max(valid_seeds, key=lambda t: len(self.adj_list.get(t, [])))
        connected_tree: Set[str] = {root}
        unconnected_seeds: Set[str] = valid_seeds - {root}

        # 2. Iteratively expand tree to reach closest unconnected seed (Multi-Source BFS)
        while unconnected_seeds:
            # Multi-source BFS starting simultaneously from all nodes in connected_tree
            queue = deque(connected_tree)
            parent: Dict[str, Optional[str]] = {node: None for node in connected_tree}

            target_found: Optional[str] = None

            while queue:
                curr = queue.popleft()
                if curr in unconnected_seeds:
                    target_found = curr
                    break

                for neighbor, _, _ in self.adj_list.get(curr, []):
                    if neighbor not in parent:
                        parent[neighbor] = curr
                        queue.append(neighbor)

            if target_found is None:
                # Remaining unconnected seeds are in separate disconnected graph components
                # Add them directly to ensure all reachable components are represented
                connected_tree.update(unconnected_seeds)
                break

            # Reconstruct shortest path from the tree to the found target
            path = []
            node: Optional[str] = target_found
            while node is not None:
                path.append(node)
                # If node was already in tree, stop backtrace
                if node in connected_tree:
                    break
                node = parent[node]

            # Add intermediate junction nodes to connected_tree
            connected_tree.update(path)
            unconnected_seeds.remove(target_found)

        return connected_tree

    def get_adaptive_connecting_tables(
        self,
        seed_tables: Set[str],
        max_budget: int = 15,
        preserve_bridges: bool = True,
    ) -> Set[str]:
        """
        Adaptively expands join paths connecting seed tables while ensuring
        that vital Steiner tree bridge tables are never severed.
        """
        valid_seeds = {t for t in seed_tables if t in self.schema}
        if not valid_seeds:
            return set(self.schema.keys())

        # 1. Compute Steiner tree containing all connecting paths
        connected_tree = self.get_minimal_connecting_tables(valid_seeds)

        if len(connected_tree) <= max_budget:
            return connected_tree

        if not preserve_bridges:
            # Simple degree ranking if bridge preservation disabled
            m_degree = {t: sum(1 for n, _, _ in self.adj_list.get(t, []) if n in connected_tree) for t in connected_tree}
            ranked = sorted(connected_tree, key=lambda t: (t in valid_seeds, m_degree.get(t, 0)), reverse=True)
            return set(ranked[:max_budget])

        # 2. Identify essential bridge tables on shortest paths between any pair of seeds
        essential_bridges: Set[str] = set()
        seed_list = list(valid_seeds)
        for i in range(len(seed_list)):
            for j in range(i + 1, len(seed_list)):
                path = self.find_shortest_path(seed_list[i], seed_list[j])
                essential_bridges.update(path)

        essential_tables = valid_seeds | essential_bridges
        if len(essential_tables) >= max_budget:
            # Keep all essential connectors even if slightly over budget to guarantee valid joins
            return essential_tables

        # Fill remaining budget with highest degree non-essential tables in connected_tree
        m_degree = {t: sum(1 for n, _, _ in self.adj_list.get(t, []) if n in connected_tree) for t in connected_tree}
        remaining = [t for t in connected_tree if t not in essential_tables]
        remaining.sort(key=lambda t: m_degree.get(t, 0), reverse=True)

        slots = max_budget - len(essential_tables)
        return essential_tables | set(remaining[:slots])

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
            degree[t] = degree.get(t, 0) + len(neighbors)
        
        # Sort by degree descending
        sorted_tables = sorted(degree.keys(), key=lambda k: degree[k], reverse=True)
        return set(sorted_tables[:limit])
