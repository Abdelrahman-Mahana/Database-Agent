"""7.4 Anomaly Detection Engine.

Deterministic, non-ML detection using:
- IQR (Interquartile Range fences: Q1 - 1.5*IQR, Q3 + 1.5*IQR)
- Z-score (Standard deviation deviations: |Z| >= 2.0 / 3.0)
- Percentage deviation (Deviation from moving baseline or median >= threshold %)
"""
import math
from typing import Any, Dict, List, Optional, Tuple


class AnomalyDetectionEngine:
    """Deterministic mathematical engine for anomaly and outlier detection."""

    @classmethod
    def _compute_percentile(cls, sorted_vals: List[float], p: float) -> float:
        """Compute the p-th percentile with linear interpolation."""
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
    def detect_anomalies_iqr(
        cls,
        data_points: List[Tuple[str, float]],
        multiplier: float = 1.5,
    ) -> Dict[str, Any]:
        """Detect outliers using Interquartile Range (IQR) fences."""
        if len(data_points) < 4:
            return {"method": "IQR", "anomalies": [], "q1": 0.0, "q3": 0.0, "iqr": 0.0}

        vals = sorted([p[1] for p in data_points])
        q1 = cls._compute_percentile(vals, 25.0)
        q3 = cls._compute_percentile(vals, 75.0)
        iqr = q3 - q1
        lower_fence = q1 - multiplier * iqr
        upper_fence = q3 + multiplier * iqr

        anomalies = []
        for label, v in data_points:
            if v < lower_fence:
                anomalies.append({
                    "label": label,
                    "value": round(v, 2),
                    "method": "IQR",
                    "type": "outlier_low",
                    "threshold": round(lower_fence, 2),
                    "description": f"Value {v:,.2f} is below lower fence {lower_fence:,.2f}",
                })
            elif v > upper_fence:
                anomalies.append({
                    "label": label,
                    "value": round(v, 2),
                    "method": "IQR",
                    "type": "outlier_high",
                    "threshold": round(upper_fence, 2),
                    "description": f"Value {v:,.2f} is above upper fence {upper_fence:,.2f}",
                })

        return {
            "method": "IQR",
            "q1": round(q1, 2),
            "q3": round(q3, 2),
            "iqr": round(iqr, 2),
            "lower_fence": round(lower_fence, 2),
            "upper_fence": round(upper_fence, 2),
            "anomalies": anomalies,
        }

    @classmethod
    def detect_anomalies_zscore(
        cls,
        data_points: List[Tuple[str, float]],
        z_threshold: float = 2.0,
    ) -> Dict[str, Any]:
        """Detect outliers using Z-score (standard deviations from mean)."""
        if len(data_points) < 3:
            return {"method": "Z-Score", "anomalies": [], "mean": 0.0, "std_dev": 0.0}

        values = [p[1] for p in data_points]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = math.sqrt(variance) if variance > 0 else 0.0

        anomalies = []
        if std_dev > 0:
            for label, v in data_points:
                z = (v - mean) / std_dev
                if abs(z) >= z_threshold:
                    anom_type = "extreme_spike" if z > 0 else "extreme_dip"
                    anomalies.append({
                        "label": label,
                        "value": round(v, 2),
                        "z_score": round(z, 2),
                        "method": "Z-Score",
                        "type": anom_type,
                        "description": f"Z-score {z:+.2f} exceeds threshold ±{z_threshold}",
                    })

        return {
            "method": "Z-Score",
            "mean": round(mean, 2),
            "std_dev": round(std_dev, 2),
            "z_threshold": z_threshold,
            "anomalies": anomalies,
        }

    @classmethod
    def detect_percentage_deviations(
        cls,
        data_points: List[Tuple[str, float]],
        pct_threshold: float = 30.0,
    ) -> Dict[str, Any]:
        """Detect sudden percentage spikes or drops relative to the baseline median."""
        if len(data_points) < 2:
            return {"method": "Percentage_Deviation", "anomalies": []}

        vals = sorted([p[1] for p in data_points])
        baseline = cls._compute_percentile(vals, 50.0)
        if baseline == 0:
            baseline = sum(vals) / len(vals) if vals else 1.0

        anomalies = []
        for label, v in data_points:
            diff_pct = ((v - baseline) / baseline * 100.0) if baseline != 0 else 0.0
            if abs(diff_pct) >= pct_threshold:
                anom_type = "percentage_spike" if diff_pct > 0 else "percentage_drop"
                anomalies.append({
                    "label": label,
                    "value": round(v, 2),
                    "baseline": round(baseline, 2),
                    "deviation_pct": round(diff_pct, 2),
                    "method": "Percentage_Deviation",
                    "type": anom_type,
                    "description": f"Deviated by {diff_pct:+.1f}% from baseline {baseline:,.2f}",
                })

        return {
            "method": "Percentage_Deviation",
            "baseline": round(baseline, 2),
            "threshold_pct": pct_threshold,
            "anomalies": anomalies,
        }

    @classmethod
    def detect_all(
        cls,
        rows: List[Dict[str, Any]],
        metric_col: str,
        label_col: Optional[str] = None,
        z_threshold: float = 2.0,
        iqr_multiplier: float = 1.5,
        pct_threshold: float = 30.0,
    ) -> Dict[str, Any]:
        """Run all 3 deterministic detection algorithms (IQR, Z-Score, Percentage Deviation)."""
        if not rows:
            return {"total_records": 0, "anomalies": []}

        data_points: List[Tuple[str, float]] = []
        for idx, r in enumerate(rows):
            try:
                val = float(r.get(metric_col, 0.0))
                lbl = str(r.get(label_col, f"Row_{idx + 1}")) if label_col else f"Row_{idx + 1}"
                data_points.append((lbl, val))
            except (ValueError, TypeError):
                pass

        iqr_res = cls.detect_anomalies_iqr(data_points, multiplier=iqr_multiplier)
        zscore_res = cls.detect_anomalies_zscore(data_points, z_threshold=z_threshold)
        pct_res = cls.detect_percentage_deviations(data_points, pct_threshold=pct_threshold)

        # Merge unique flagged items
        flagged_map: Dict[str, Dict[str, Any]] = {}
        for a in iqr_res["anomalies"] + zscore_res["anomalies"] + pct_res["anomalies"]:
            lbl = a["label"]
            if lbl not in flagged_map:
                flagged_map[lbl] = {
                    "label": lbl,
                    "value": a["value"],
                    "methods": [a["method"]],
                    "details": [a["description"]],
                }
            else:
                if a["method"] not in flagged_map[lbl]["methods"]:
                    flagged_map[lbl]["methods"].append(a["method"])
                    flagged_map[lbl]["details"].append(a["description"])

        anomalies_list = list(flagged_map.values())

        return {
            "column": metric_col,
            "total_records": len(data_points),
            "iqr_summary": iqr_res,
            "zscore_summary": zscore_res,
            "percentage_summary": pct_res,
            "anomalies": anomalies_list,
        }

    @classmethod
    def generate_findings(cls, anom_res: Dict[str, Any]) -> List[str]:
        """Generate human-readable analytical findings from anomaly detection."""
        findings = []
        anoms = anom_res.get("anomalies", [])
        if not anoms:
            findings.append("No statistical anomalies or outliers detected (all points within IQR, Z-Score, and variance thresholds).")
        else:
            findings.append(f"Detected {len(anoms)} statistical anomalies across {anom_res['total_records']} records:")
            for a in anoms:
                methods_str = ", ".join(a["methods"])
                findings.append(f"  - {a['label']}: value {a['value']:,.2f} flagged by [{methods_str}] ({'; '.join(a['details'])})")

        return findings
