"""Root Cause Analysis (RCA) Engine.

Implements the multi-stage Root Cause Investigation Pipeline:
1. Overall Decline: Quantify total metric drop and baseline vs current period.
2. Find Affected Time Period: Isolate when the decline occurred.
3. Compare Dimensions: Decompose across available business dimensions (region, product, segment, etc.).
4. Find Largest Contributors: Calculate absolute and percentage change for each slice.
5. Find Negative Changes: Isolate specific sub-segments experiencing contraction.
6. Rank Contributors: Rank negative drivers by impact and contribution share (Waterfall decomposition).
7. Generate Evidence: Produce verified mathematical proof for LLM explanation without hallucinating causes.
"""
from typing import Any, Dict, List, Optional, Tuple


class RootCauseEngine:
    """Deterministic mathematical engine for multi-dimensional root cause and driver decomposition."""

    @classmethod
    def quantify_overall_decline(
        cls,
        rows: List[Dict[str, Any]],
        metric_col: str,
        time_col: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Quantify overall metric decline, comparing start/baseline period to end/current period."""
        if not rows:
            return {"has_decline": False, "total_change": 0.0, "growth_pct": 0.0}

        if time_col and len(rows) >= 2:
            sorted_rows = sorted(rows, key=lambda x: str(x.get(time_col, "")))
            prior_period = str(sorted_rows[0].get(time_col, "Prior"))
            current_period = str(sorted_rows[-1].get(time_col, "Current"))
            prior_val = float(sorted_rows[0].get(metric_col, 0.0))
            current_val = float(sorted_rows[-1].get(metric_col, 0.0))
        else:
            prior_period = "Baseline"
            current_period = "Current"
            vals = [float(r.get(metric_col, 0.0)) for r in rows if r.get(metric_col) is not None]
            if len(vals) >= 2:
                prior_val = vals[0]
                current_val = vals[-1]
            elif vals:
                prior_val = vals[0]
                current_val = vals[0]
            else:
                prior_val = 0.0
                current_val = 0.0

        total_change = current_val - prior_val
        growth_pct = ((total_change / prior_val) * 100.0) if prior_val != 0 else 0.0
        has_decline = total_change < 0

        return {
            "has_decline": has_decline,
            "metric": metric_col,
            "prior_period": prior_period,
            "current_period": current_period,
            "prior_value": round(prior_val, 2),
            "current_value": round(current_val, 2),
            "total_change": round(total_change, 2),
            "growth_pct": round(growth_pct, 2),
        }

    @classmethod
    def decompose_dimension(
        cls,
        rows: List[Dict[str, Any]],
        dimension_col: str,
        metric_col: str,
        time_col: Optional[str] = None,
        total_decline: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Decompose metric changes by dimension, calculating contribution share to total decline."""
        if not rows:
            return {"dimension": dimension_col, "negative_contributors": [], "positive_contributors": []}

        # Case A: rows contain time_col + dimension_col (multi-period breakdown per category)
        if time_col and any(time_col in r for r in rows):
            time_periods = sorted(list({str(r.get(time_col, "")) for r in rows if r.get(time_col)}))
            if len(time_periods) >= 2:
                prior_p, curr_p = time_periods[0], time_periods[-1]
                cat_prior: Dict[str, float] = {}
                cat_curr: Dict[str, float] = {}

                for r in rows:
                    cat = str(r.get(dimension_col, "Unknown"))
                    val = float(r.get(metric_col, 0.0))
                    p = str(r.get(time_col, ""))
                    if p == prior_p:
                        cat_prior[cat] = cat_prior.get(cat, 0.0) + val
                    elif p == curr_p:
                        cat_curr[cat] = cat_curr.get(cat, 0.0) + val

                all_cats = set(cat_prior.keys()).union(set(cat_curr.keys()))
                records = []
                for cat in all_cats:
                    v0 = cat_prior.get(cat, 0.0)
                    v1 = cat_curr.get(cat, 0.0)
                    delta = v1 - v0
                    pct = ((delta / v0) * 100.0) if v0 != 0 else 0.0
                    records.append({
                        "category": cat,
                        "prior_value": round(v0, 2),
                        "current_value": round(v1, 2),
                        "delta": round(delta, 2),
                        "growth_pct": round(pct, 2),
                    })
            else:
                records = cls._group_single_period(rows, dimension_col, metric_col)
        else:
            records = cls._group_single_period(rows, dimension_col, metric_col)

        # Calculate total drop among all negative categories
        calc_total_decline = total_decline if (total_decline and total_decline < 0) else sum(
            r["delta"] for r in records if r.get("delta", 0) < 0
        )

        negative_contributors = []
        positive_contributors = []

        for r in records:
            delta = r.get("delta", 0.0)
            if delta < 0:
                share = (delta / calc_total_decline * 100.0) if calc_total_decline < 0 else 0.0
                negative_contributors.append({
                    "category": r["category"],
                    "prior_value": r.get("prior_value", 0.0),
                    "current_value": r.get("current_value", 0.0),
                    "delta": r["delta"],
                    "growth_pct": r.get("growth_pct", 0.0),
                    "contribution_to_decline_pct": round(share, 2),
                })
            else:
                positive_contributors.append(r)

        # Rank negative contributors by largest absolute drop (Pareto ranking)
        negative_contributors.sort(key=lambda x: abs(x["delta"]), reverse=True)
        positive_contributors.sort(key=lambda x: x.get("delta", 0.0), reverse=True)

        # Cumulative contribution share
        cum_pct = 0.0
        for item in negative_contributors:
            cum_pct += item["contribution_to_decline_pct"]
            item["cumulative_contribution_pct"] = round(cum_pct, 2)

        return {
            "dimension": dimension_col,
            "total_negative_delta": round(sum(n["delta"] for n in negative_contributors), 2),
            "negative_contributors": negative_contributors,
            "positive_contributors": positive_contributors,
        }

    @classmethod
    def _group_single_period(
        cls,
        rows: List[Dict[str, Any]],
        dimension_col: str,
        metric_col: str,
    ) -> List[Dict[str, Any]]:
        """Fallback for pre-aggregated delta or ranking tables."""
        records = []
        for r in rows:
            cat = str(r.get(dimension_col, "Unknown"))
            val = float(r.get(metric_col, 0.0))
            records.append({
                "category": cat,
                "prior_value": 0.0,
                "current_value": round(val, 2),
                "delta": round(val, 2) if val < 0 else -round(val, 2),
                "growth_pct": -100.0 if val > 0 else 0.0,
            })
        return records

    @classmethod
    def run_investigation(
        cls,
        rows: List[Dict[str, Any]],
        metric_col: str,
        dimension_cols: List[str],
        time_col: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run complete investigation pipeline across all available dimensions."""
        overall = cls.quantify_overall_decline(rows, metric_col=metric_col, time_col=time_col)
        total_drop = overall["total_change"] if overall["has_decline"] else None

        dimensions_analysis = []
        for dim in dimension_cols:
            dim_res = cls.decompose_dimension(
                rows,
                dimension_col=dim,
                metric_col=metric_col,
                time_col=time_col,
                total_decline=total_drop,
            )
            if dim_res["negative_contributors"]:
                dimensions_analysis.append(dim_res)

        return {
            "overall": overall,
            "dimensions_investigated": dimensions_analysis,
        }

    @classmethod
    def generate_findings(cls, investigation: Dict[str, Any]) -> List[str]:
        """Generate verified mathematical proof for LLM report synthesis."""
        findings = []
        overall = investigation.get("overall", {})

        if overall.get("has_decline"):
            findings.append(
                f"التراجع الإجمالي: انخفض {overall['metric']} من {overall['prior_value']:,.2f} إلى "
                f"{overall['current_value']:,.2f} (تراجع بمقدار {overall['total_change']:+,.2f} أي بنسبة {overall['growth_pct']:+.2f}%) "
                f"بين {overall['prior_period']} و {overall['current_period']}."
            )
        else:
            findings.append(
                f"التقييم الإجمالي للمتغير {overall.get('metric', '')}: التغير العام هو {overall.get('total_change', 0):+,.2f} "
                f"({overall.get('growth_pct', 0):+.2f}%)."
            )

        dims = investigation.get("dimensions_investigated", [])
        if dims:
            findings.append("تحليل المساهمين في التراجع (Dimensional Root Cause Contribution):")
            for dim_res in dims:
                dim_name = dim_res["dimension"]
                negs = dim_res["negative_contributors"]
                if negs:
                    findings.append(f"• حسب البُعد '{dim_name}':")
                    for n in negs[:4]:  # Top 4 negative contributors
                        findings.append(
                            f"   - {n['category']}: انخفض بمقدار {n['delta']:+,.2f} ({n['growth_pct']:+.1f}%) "
                            f"وساهم بنسبة {n['contribution_to_decline_pct']:.1f}% من إجمالي التراجع."
                        )

        return findings
