"""7.2 Trend Engine.

Supports:
- Temporal granularity detection (monthly, weekly, daily, yearly)
- MoM (Month-over-Month sequential growth rate)
- YoY (Year-over-Year growth comparison across same periods in consecutive years)
- Overall growth rate and trend slope
- Peak & Trough period identification
"""
import re
from typing import Any, Dict, List, Optional, Tuple


class TrendEngine:
    """Deterministic mathematical engine for time-series, growth rates, MoM, and YoY trends."""

    @classmethod
    def detect_granularity(cls, periods: List[str]) -> str:
        """Detect if period strings are daily (YYYY-MM-DD), weekly (YYYY-Www), monthly (YYYY-MM), or yearly (YYYY)."""
        if not periods:
            return "unknown"
        sample = periods[0].strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", sample):
            return "daily"
        if re.match(r"^\d{4}-W\d{2}", sample, re.IGNORECASE):
            return "weekly"
        if re.match(r"^\d{4}-\d{2}", sample) or re.match(r"^[A-Za-z]{3,9}\s+\d{4}", sample):
            return "monthly"
        if re.match(r"^\d{4}$", sample):
            return "yearly"
        return "periodic"

    @classmethod
    def compute_trend(
        cls,
        rows: List[Dict[str, Any]],
        date_col: str,
        metric_col: str,
    ) -> Dict[str, Any]:
        """Compute chronological trajectory, MoM, YoY, growth rates, and peaks/troughs."""
        if not rows:
            return {"granularity": "unknown", "overall_growth_pct": 0.0, "series": []}

        # Extract and sort time-series points
        points: List[Tuple[str, float]] = []
        for r in rows:
            try:
                period_str = str(r.get(date_col, ""))
                val = float(r.get(metric_col, 0.0))
                if period_str:
                    points.append((period_str, val))
            except (ValueError, TypeError):
                pass

        if not points:
            return {"granularity": "unknown", "overall_growth_pct": 0.0, "series": []}

        # Sort chronologically by period string
        points.sort(key=lambda x: x[0])
        granularity = cls.detect_granularity([p[0] for p in points])

        # 1. Overall Growth Rate
        first_period, first_val = points[0]
        last_period, last_val = points[-1]
        overall_growth = ((last_val - first_val) / first_val * 100.0) if first_val != 0 else 0.0

        # 2. Sequential Period-over-Period (MoM / WoW / DoD) Rates
        mom_rates = []
        for i in range(1, len(points)):
            prev_p, prev_v = points[i - 1]
            curr_p, curr_v = points[i]
            diff = curr_v - prev_v
            growth = ((diff / prev_v) * 100.0) if prev_v != 0 else 0.0
            mom_rates.append({
                "period": curr_p,
                "previous_period": prev_p,
                "value": round(curr_v, 2),
                "change": round(diff, 2),
                "growth_pct": round(growth, 2),
            })

        # 3. Year-over-Year (YoY) Rates (matching periods 12 steps apart or same month in previous year)
        yoy_rates = []
        period_map = {p: v for p, v in points}
        for curr_p, curr_v in points:
            # Check for YYYY-MM pattern
            match = re.match(r"^(\d{4})-(\d{2})", curr_p)
            if match:
                curr_year, curr_month = int(match.group(1)), match.group(2)
                prev_year_period = f"{curr_year - 1}-{curr_month}"
                if prev_year_period in period_map:
                    prev_v = period_map[prev_year_period]
                    diff = curr_v - prev_v
                    yoy_growth = ((diff / prev_v) * 100.0) if prev_v != 0 else 0.0
                    yoy_rates.append({
                        "period": curr_p,
                        "comparison_period": prev_year_period,
                        "value": round(curr_v, 2),
                        "previous_year_value": round(prev_v, 2),
                        "yoy_growth_pct": round(yoy_growth, 2),
                    })

        # 4. Peaks and Troughs
        peak_item = max(points, key=lambda x: x[1])
        trough_item = min(points, key=lambda x: x[1])

        # 5. Linear Slope & Direction
        n = len(points)
        slope = 0.0
        if n >= 2:
            xs = list(range(n))
            ys = [p[1] for p in points]
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
            den = sum((x - mean_x) ** 2 for x in xs)
            slope = num / den if den > 0 else 0.0

        trend_direction = "upward" if slope > 0.01 else ("downward" if slope < -0.01 else "stable")

        return {
            "granularity": granularity,
            "period_count": n,
            "first_period": first_period,
            "last_period": last_period,
            "overall_growth_pct": round(overall_growth, 2),
            "trend_direction": trend_direction,
            "linear_slope": round(slope, 2),
            "peak": {"period": peak_item[0], "value": round(peak_item[1], 2)},
            "trough": {"period": trough_item[0], "value": round(trough_item[1], 2)},
            "mom_rates": mom_rates,
            "yoy_rates": yoy_rates,
        }

    @classmethod
    def generate_findings(cls, trend_res: Dict[str, Any]) -> List[str]:
        """Generate human-readable analytical findings from trend evaluation."""
        findings = []
        if trend_res.get("period_count", 0) < 2:
            return ["Insufficient time periods for trend analysis."]

        gran = trend_res.get("granularity", "period")
        p_label = "MoM" if gran == "monthly" else ("DoD" if gran == "daily" else "period-over-period")
        
        findings.append(
            f"Overall {gran} trajectory is {trend_res['trend_direction']} from {trend_res['first_period']} to {trend_res['last_period']} "
            f"({trend_res['overall_growth_pct']:+.2f}% total change)."
        )

        pk = trend_res.get("peak")
        tr = trend_res.get("trough")
        if pk and tr:
            findings.append(f"Highest {gran} peak was in {pk['period']} ({pk['value']:,.2f}), lowest trough in {tr['period']} ({tr['value']:,.2f}).")

        # Mention recent YoY if available
        if trend_res.get("yoy_rates"):
            latest_yoy = trend_res["yoy_rates"][-1]
            findings.append(
                f"Latest YoY comparison for {latest_yoy['period']}: {latest_yoy['yoy_growth_pct']:+.2f}% "
                f"vs {latest_yoy['comparison_period']} ({latest_yoy['value']:,.2f} vs {latest_yoy['previous_year_value']:,.2f})."
            )

        return findings
