"""7.3 Distribution Engine.

Supports:
- mean (arithmetic average)
- median (50th percentile)
- percentiles (p10, p25/Q1, p50, p75/Q3, p90, p95, p99)
- frequency distributions (categorical or discrete counts & percentages)
- histogram-ready buckets (automatic equal-width or quantile binning)
"""
import math
from typing import Any, Dict, List, Optional, Tuple


class DistributionEngine:
    """Deterministic mathematical engine for distributions, percentiles, frequencies, and histogram bins."""

    @classmethod
    def _compute_percentile(cls, sorted_vals: List[float], p: float) -> float:
        """Compute the p-th percentile (0 <= p <= 100) using linear interpolation."""
        if not sorted_vals:
            return 0.0
        if len(sorted_vals) == 1:
            return sorted_vals[0]
        k = (len(sorted_vals) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        d0 = sorted_vals[int(f)] * (c - k)
        d1 = sorted_vals[int(c)] * (k - f)
        return d0 + d1

    @classmethod
    def compute_numeric_distribution(
        cls,
        rows: List[Dict[str, Any]],
        numeric_col: str,
        num_buckets: int = 5,
    ) -> Dict[str, Any]:
        """Compute mean, median, percentiles, and histogram-ready buckets for a numeric column."""
        if not rows:
            return {"count": 0, "mean": 0.0, "median": 0.0, "percentiles": {}, "buckets": []}

        vals = []
        for r in rows:
            try:
                v = r.get(numeric_col)
                if v is not None:
                    vals.append(float(v))
            except (ValueError, TypeError):
                pass

        if not vals:
            return {"count": 0, "mean": 0.0, "median": 0.0, "percentiles": {}, "buckets": []}

        n = len(vals)
        vals.sort()
        mean_val = sum(vals) / n
        median_val = cls._compute_percentile(vals, 50.0)

        # Percentiles
        percentiles = {
            "p10": round(cls._compute_percentile(vals, 10.0), 2),
            "p25": round(cls._compute_percentile(vals, 25.0), 2),
            "p50": round(median_val, 2),
            "p75": round(cls._compute_percentile(vals, 75.0), 2),
            "p90": round(cls._compute_percentile(vals, 90.0), 2),
            "p95": round(cls._compute_percentile(vals, 95.0), 2),
            "p99": round(cls._compute_percentile(vals, 99.0), 2),
        }

        min_val = vals[0]
        max_val = vals[-1]
        val_range = max_val - min_val

        # Histogram-ready buckets
        buckets = []
        if val_range > 0 and num_buckets > 0:
            step = val_range / num_buckets
            for b_idx in range(num_buckets):
                low = min_val + b_idx * step
                high = low + step if b_idx < num_buckets - 1 else max_val
                
                # Count values falling in this bucket [low, high) or [low, high] for last bucket
                if b_idx == num_buckets - 1:
                    b_count = sum(1 for v in vals if low <= v <= high)
                else:
                    b_count = sum(1 for v in vals if low <= v < high)

                b_pct = (b_count / n * 100.0) if n > 0 else 0.0
                buckets.append({
                    "bucket_id": b_idx + 1,
                    "lower_bound": round(low, 2),
                    "upper_bound": round(high, 2),
                    "label": f"{low:,.1f} - {high:,.1f}",
                    "count": b_count,
                    "percentage": round(b_pct, 2),
                })
        else:
            buckets.append({
                "bucket_id": 1,
                "lower_bound": round(min_val, 2),
                "upper_bound": round(max_val, 2),
                "label": f"{min_val:,.1f}",
                "count": n,
                "percentage": 100.0,
            })

        return {
            "column": numeric_col,
            "count": n,
            "min": round(min_val, 2),
            "max": round(max_val, 2),
            "mean": round(mean_val, 2),
            "median": round(median_val, 2),
            "iqr": round(percentiles["p75"] - percentiles["p25"], 2),
            "percentiles": percentiles,
            "buckets": buckets,
        }

    @classmethod
    def compute_categorical_frequency(
        cls,
        rows: List[Dict[str, Any]],
        categorical_col: str,
    ) -> Dict[str, Any]:
        """Compute frequency distribution and percentages for categorical columns."""
        if not rows:
            return {"total_count": 0, "categories": []}

        counts: Dict[str, int] = {}
        total = 0
        for r in rows:
            val = str(r.get(categorical_col, "Unknown")).strip()
            counts[val] = counts.get(val, 0) + 1
            total += 1

        categories = []
        for cat, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            pct = (cnt / total * 100.0) if total > 0 else 0.0
            categories.append({
                "category": cat,
                "count": cnt,
                "percentage": round(pct, 2),
            })

        return {
            "column": categorical_col,
            "total_count": total,
            "unique_categories": len(categories),
            "categories": categories,
        }

    @classmethod
    def generate_findings(cls, dist_res: Dict[str, Any]) -> List[str]:
        """Generate structured text findings from distribution evaluation."""
        findings = []
        col = dist_res.get("column", "metric")
        if "percentiles" in dist_res:
            p = dist_res["percentiles"]
            findings.append(
                f"{col} distribution (N={dist_res['count']}): Mean={dist_res['mean']:,.2f}, "
                f"Median={dist_res['median']:,.2f}, IQR={dist_res['iqr']:,.2f} "
                f"(P25={p['p25']:,.2f}, P75={p['p75']:,.2f}, P95={p['p95']:,.2f})."
            )
            # Find largest histogram bucket
            if dist_res.get("buckets"):
                largest_b = max(dist_res["buckets"], key=lambda x: x["count"])
                findings.append(f"Highest density bucket: {largest_b['label']} containing {largest_b['count']} records ({largest_b['percentage']:.1f}%).")
        elif "categories" in dist_res:
            cats = dist_res["categories"]
            findings.append(f"{col} category frequency across {dist_res['total_count']} records ({dist_res['unique_categories']} unique categories).")
            for c in cats[:3]:
                findings.append(f"  - {c['category']}: {c['count']} occurrences ({c['percentage']:.1f}%)")

        return findings
