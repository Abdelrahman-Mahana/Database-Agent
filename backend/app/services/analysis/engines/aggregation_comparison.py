"""7.1 Aggregation & Comparison Engine.

Calculates:
- average (mean)
- sum (total)
- count (record volume)
- min / max
- percentage (share of total)
- difference (absolute difference between compared groups)
- growth (percentage growth rate between compared groups)
"""
from typing import Any, Dict, List, Optional, Tuple


class AggregationComparisonEngine:
    """Deterministic mathematical engine for aggregations and cohort comparisons."""

    @classmethod
    def compute_aggregations(
        cls,
        rows: List[Dict[str, Any]],
        numeric_cols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Compute sum, average, count, min, max, and percentage shares for numeric columns."""
        if not rows:
            return {"row_count": 0, "columns": {}}

        if numeric_cols is None:
            numeric_cols = [
                k for k, v in rows[0].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]

        results: Dict[str, Any] = {
            "row_count": len(rows),
            "columns": {},
        }

        for col in numeric_cols:
            vals = [float(r[col]) for r in rows if r.get(col) is not None]
            if not vals:
                continue

            total_sum = sum(vals)
            count = len(vals)
            avg = total_sum / count if count > 0 else 0.0
            min_val = min(vals)
            max_val = max(vals)

            results["columns"][col] = {
                "count": count,
                "sum": round(total_sum, 2),
                "average": round(avg, 2),
                "min": round(min_val, 2),
                "max": round(max_val, 2),
            }

        return results

    @classmethod
    def compute_comparison(
        cls,
        rows: List[Dict[str, Any]],
        group_col: str,
        metric_col: str,
    ) -> Dict[str, Any]:
        """Compare groups calculating absolute difference, percentage growth, and total percentage shares."""
        if not rows:
            return {"groups": [], "comparisons": []}

        items: List[Tuple[str, float]] = []
        total_sum = 0.0
        for r in rows:
            try:
                lbl = str(r.get(group_col, "Unknown"))
                val = float(r.get(metric_col, 0.0))
                items.append((lbl, val))
                total_sum += val
            except (ValueError, TypeError):
                pass

        groups_summary = []
        for lbl, val in items:
            share = (val / total_sum * 100.0) if total_sum > 0 else 0.0
            groups_summary.append({
                "group": lbl,
                "value": round(val, 2),
                "percentage_share": round(share, 2),
            })

        comparisons = []
        if len(items) >= 2:
            for i in range(len(items) - 1):
                lbl_a, val_a = items[i]
                lbl_b, val_b = items[i + 1]
                diff = val_b - val_a
                growth = ((diff / val_a) * 100.0) if val_a != 0 else 0.0
                comparisons.append({
                    "from_group": lbl_a,
                    "to_group": lbl_b,
                    "from_value": round(val_a, 2),
                    "to_value": round(val_b, 2),
                    "difference": round(diff, 2),
                    "growth_pct": round(growth, 2),
                })

        winner = max(items, key=lambda x: x[1]) if items else None
        lowest = min(items, key=lambda x: x[1]) if items else None

        return {
            "total_sum": round(total_sum, 2),
            "groups": groups_summary,
            "comparisons": comparisons,
            "highest_group": {"group": winner[0], "value": round(winner[1], 2)} if winner else None,
            "lowest_group": {"group": lowest[0], "value": round(lowest[1], 2)} if lowest else None,
        }

    @classmethod
    def generate_findings(cls, comparison_res: Dict[str, Any]) -> List[str]:
        """Generate structured text findings from comparison result."""
        findings = []
        if comparison_res.get("highest_group") and comparison_res.get("lowest_group"):
            hi = comparison_res["highest_group"]
            lo = comparison_res["lowest_group"]
            findings.append(f"Highest performing group: {hi['group']} ({hi['value']:,.2f}), lowest: {lo['group']} ({lo['value']:,.2f}).")

        for c in comparison_res.get("comparisons", []):
            findings.append(
                f"{c['to_group']} vs {c['from_group']}: {c['to_value']:,.2f} vs {c['from_value']:,.2f} "
                f"(Diff: {c['difference']:+,.2f}, Growth: {c['growth_pct']:+.2f}%)."
            )

        return findings
