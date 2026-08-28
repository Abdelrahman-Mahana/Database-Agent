"""Forecasting Engine.

Implements deterministic time-series forecasting:
1. Baseline: Naive last-observed value and historical mean baseline.
2. Moving Average: Simple Moving Average (SMA) and Weighted Moving Average (WMA).
3. Linear Trend: Ordinary Least Squares (OLS) regression slope, intercept, and prediction intervals (95% CI).
"""
import math
from typing import Any, Dict, List, Optional, Tuple


class ForecastingEngine:
    """Deterministic mathematical engine for time-series forecasting and trend projection."""

    @classmethod
    def forecast_linear_trend(
        cls,
        series: List[Tuple[str, float]],
        periods_ahead: int = 3,
    ) -> Dict[str, Any]:
        """Compute OLS linear regression forecast with 95% prediction intervals."""
        n = len(series)
        if n < 2:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0, "projections": []}

        xs = list(range(n))
        ys = [p[1] for p in series]

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)

        slope = num / den if den > 0 else 0.0
        intercept = mean_y - slope * mean_x

        # Calculate R² and Standard Error of the Estimate
        y_preds = [slope * x + intercept for x in xs]
        ss_res = sum((y - y_hat) ** 2 for y, y_hat in zip(ys, y_preds))
        ss_tot = sum((y - mean_y) ** 2 for y in ys)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        std_err = math.sqrt(ss_res / (n - 2)) if n > 2 and ss_res >= 0 else 0.0

        projections = []
        for h in range(1, periods_ahead + 1):
            future_x = n - 1 + h
            pred_y = max(0.0, slope * future_x + intercept)
            margin = 1.96 * std_err if std_err > 0 else (pred_y * 0.1)
            lower_bound = max(0.0, pred_y - margin)
            upper_bound = pred_y + margin

            projections.append({
                "period_offset": h,
                "projected_value": round(pred_y, 2),
                "lower_bound_95": round(lower_bound, 2),
                "upper_bound_95": round(upper_bound, 2),
            })

        trend_direction = "upward" if slope > 0.01 else ("downward" if slope < -0.01 else "stable")

        return {
            "slope": round(slope, 2),
            "intercept": round(intercept, 2),
            "r_squared": round(max(0.0, r_squared), 3),
            "trend_direction": trend_direction,
            "std_error": round(std_err, 2),
            "projections": projections,
        }

    @classmethod
    def forecast_moving_average(
        cls,
        series: List[Tuple[str, float]],
        window: int = 3,
        periods_ahead: int = 3,
    ) -> Dict[str, Any]:
        """Compute Simple (SMA) and Weighted Moving Average (WMA) forecasts."""
        n = len(series)
        if n == 0:
            return {"sma_value": 0.0, "wma_value": 0.0, "projections": []}

        effective_window = min(n, max(1, window))
        recent_vals = [p[1] for p in series[-effective_window:]]

        # Simple Moving Average
        sma = sum(recent_vals) / len(recent_vals)

        # Weighted Moving Average (giving higher weight to more recent points)
        weights = list(range(1, len(recent_vals) + 1))
        w_sum = sum(weights)
        wma = sum(v * w for v, w in zip(recent_vals, weights)) / w_sum

        projections = []
        for h in range(1, periods_ahead + 1):
            projections.append({
                "period_offset": h,
                "sma_projected": round(sma, 2),
                "wma_projected": round(wma, 2),
            })

        return {
            "window_size": effective_window,
            "sma_baseline": round(sma, 2),
            "wma_baseline": round(wma, 2),
            "projections": projections,
        }

    @classmethod
    def forecast_all(
        cls,
        rows: List[Dict[str, Any]],
        metric_col: str,
        date_col: Optional[str] = None,
        periods_ahead: int = 3,
    ) -> Dict[str, Any]:
        """Generate comprehensive deterministic forecasts across Linear Trend, Moving Average, and Baseline."""
        if not rows:
            return {"metric": metric_col, "data_points": 0, "projections": []}

        series: List[Tuple[str, float]] = []
        for idx, r in enumerate(rows):
            try:
                val = float(r.get(metric_col, 0.0))
                lbl = str(r.get(date_col, f"T_{idx + 1}")) if date_col else f"T_{idx + 1}"
                series.append((lbl, val))
            except (ValueError, TypeError):
                pass

        if not series:
            return {"metric": metric_col, "data_points": 0, "projections": []}

        # 1. Linear Trend
        linear_res = cls.forecast_linear_trend(series, periods_ahead=periods_ahead)

        # 2. Moving Average
        ma_res = cls.forecast_moving_average(series, window=3, periods_ahead=periods_ahead)

        # 3. Naive Baseline
        last_observed = series[-1][1]
        historical_mean = sum(p[1] for p in series) / len(series)

        # Combined composite recommendation
        recommended_next = (
            linear_res["projections"][0]["projected_value"]
            if linear_res["projections"]
            else ma_res["wma_baseline"]
        )

        return {
            "metric": metric_col,
            "data_points_count": len(series),
            "last_observed_value": round(last_observed, 2),
            "historical_mean": round(historical_mean, 2),
            "recommended_next_period_value": round(recommended_next, 2),
            "linear_trend_model": linear_res,
            "moving_average_model": ma_res,
        }

    @classmethod
    def generate_findings(cls, forecast_res: Dict[str, Any]) -> List[str]:
        """Generate verified forecast facts ready for LLM explanation."""
        n = forecast_res.get("data_points_count", 0)
        if n < 2:
            return ["Insufficient historical data points to generate reliable forecasts."]

        metric = forecast_res.get("metric", "القيمة")
        last_val = forecast_res.get("last_observed_value", 0.0)
        rec_next = forecast_res.get("recommended_next_period_value", 0.0)
        linear = forecast_res.get("linear_trend_model", {})
        dir_arabic = "تصاعدي (نمو)" if linear.get("trend_direction") == "upward" else ("تنازلي (انكماش)" if linear.get("trend_direction") == "downward" else "مستقر")

        findings = [
            f"التوقع المستقبلي لـ '{metric}' (استناداً إلى {n} فترة تاريخية سابقة):",
            f"• آخر قيمة فعلية مسجلة: {last_val:,.2f}.",
            f"• القيمة المتوقعة للفترة القادمة: {rec_next:,.2f} (مسار {dir_arabic}، معدل التغير {linear.get('slope', 0):+,.2f}/فترة).",
        ]

        if linear.get("projections"):
            p1 = linear["projections"][0]
            findings.append(f"• نطاق الثقة (95% Confidence Interval): بين {p1['lower_bound_95']:,.2f} و {p1['upper_bound_95']:,.2f}.")

        return findings
