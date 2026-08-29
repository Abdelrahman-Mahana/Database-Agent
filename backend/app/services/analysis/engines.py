from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Any, Dict, List, Optional, Tuple
import math
import re

# --- From aggregation_comparison.py ---
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


# --- From anomaly_detection.py ---
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


# --- From correlation.py ---
class CorrelationEngine:
    """Deterministic mathematical engine for bivariate correlation, direction, strength, and limitations."""

    @classmethod
    def compute_correlation(
        cls,
        rows: List[Dict[str, Any]],
        col_x: Optional[str] = None,
        col_y: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute Pearson r, determination R², direction, strength, and methodological limitations."""
        if not rows:
            return {
                "sample_size": 0,
                "pearson_r": 0.0,
                "r_squared": 0.0,
                "direction": "neutral",
                "strength": "none",
                "limitations": ["No data rows available to compute correlation."],
            }

        # Auto-detect numeric columns if not explicitly provided
        if not col_x or not col_y:
            num_cols = [
                k for k, v in rows[0].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            if len(num_cols) < 2:
                # Try parsing numeric values from string columns
                for k in rows[0].keys():
                    if k not in num_cols:
                        try:
                            float(rows[0][k])
                            num_cols.append(k)
                        except (ValueError, TypeError):
                            pass

            if len(num_cols) >= 2:
                col_x, col_y = num_cols[0], num_cols[1]
            else:
                return {
                    "sample_size": 0,
                    "pearson_r": 0.0,
                    "r_squared": 0.0,
                    "direction": "neutral",
                    "strength": "none",
                    "limitations": ["At least two numeric variables are required to evaluate correlation."],
                }

        # Step 1 & 2: Retrieve and pair variable values
        paired: List[Tuple[float, float]] = []
        for r in rows:
            try:
                vx = float(r.get(col_x, 0.0))
                vy = float(r.get(col_y, 0.0))
                paired.append((vx, vy))
            except (ValueError, TypeError):
                pass

        n = len(paired)
        if n < 3:
            return {
                "col_x": col_x,
                "col_y": col_y,
                "sample_size": n,
                "pearson_r": 0.0,
                "r_squared": 0.0,
                "direction": "neutral",
                "strength": "insufficient_data",
                "limitations": [f"Insufficient data points (N={n}, minimum 3 required) to compute correlation."],
            }

        # Step 3: Calculate Pearson correlation (r)
        xs = [p[0] for p in paired]
        ys = [p[1] for p in paired]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        cov = sum((x - mean_x) * (y - mean_y) for x, y in paired)
        var_x = sum((x - mean_x) ** 2 for x in xs)
        var_y = sum((y - mean_y) ** 2 for y in ys)
        denominator = math.sqrt(var_x * var_y)

        if denominator > 0:
            raw_r = cov / denominator
            # Clamp to [-1.0, 1.0] to guard against floating-point precision issues
            r = max(-1.0, min(1.0, raw_r))
        else:
            r = 0.0

        r_squared = r ** 2

        # Step 4: Determine direction
        if r > 0.05:
            direction = "positive"
            direction_desc = "طردية (إيجابية)"
        elif r < -0.05:
            direction = "negative"
            direction_desc = "عكسية (سلبية)"
        else:
            direction = "neutral"
            direction_desc = "شبه منعدمة / محايدة"

        # Step 5: Determine strength
        abs_r = abs(r)
        if abs_r >= 0.8:
            strength = "very_strong"
            strength_desc = "قوية جداً"
        elif abs_r >= 0.6:
            strength = "strong"
            strength_desc = "قوية"
        elif abs_r >= 0.4:
            strength = "moderate"
            strength_desc = "متوسطة"
        elif abs_r >= 0.2:
            strength = "weak"
            strength_desc = "ضعيفة"
        else:
            strength = "negligible"
            strength_desc = "ضعيفة جداً أو شبه منعدمة"

        # Step 6: Methodological limitations
        limitations = [
            "الارتباط الإحصائي لا يعني السببية (Correlation does not imply causation): وجود ارتباط بين المتغيرين لا يثبت أن أحدهما يسبب الآخر مباشرة، فقد توجد عوامل وسيطة أو خارجية.",
            f"معامل بيرسون يقيس العلاقات الخطية فقط (Linear Association): قد توجد علاقة غير خطية (مثل علاقة منحنية أو أسية) لا تنعكس في قيمة r.",
        ]
        if n < 30:
            limitations.append(f"حجم العينة صغير نسبياً (N={n})، مما قد يؤثر على الدقة الإحصائية.")

        return {
            "col_x": col_x,
            "col_y": col_y,
            "sample_size": n,
            "mean_x": round(mean_x, 2),
            "mean_y": round(mean_y, 2),
            "pearson_r": round(r, 4),
            "r_squared": round(r_squared, 4),
            "variance_explained_pct": round(r_squared * 100.0, 2),
            "direction": direction,
            "direction_desc": direction_desc,
            "strength": strength,
            "strength_desc": strength_desc,
            "limitations": limitations,
        }

    @classmethod
    def generate_findings(cls, corr_res: Dict[str, Any]) -> List[str]:
        """Generate structured analytical findings ready for LLM explanation."""
        if corr_res.get("sample_size", 0) < 3:
            return corr_res.get("limitations", ["Insufficient data for correlation."])

        col_x = corr_res.get("col_x", "X")
        col_y = corr_res.get("col_y", "Y")
        r = corr_res.get("pearson_r", 0.0)
        r2_pct = corr_res.get("variance_explained_pct", 0.0)
        str_desc = corr_res.get("strength_desc", "")
        dir_desc = corr_res.get("direction_desc", "")
        n = corr_res.get("sample_size", 0)

        findings = [
            f"معامل ارتباط بيرسون بين {col_x} و {col_y} هو r = {r:+.3f} (عينة N = {n}).",
            f"طبيعة العلاقة: علاقة {dir_desc} بدرجة {str_desc}.",
            f"معامل التحديد (R² = {corr_res.get('r_squared', 0.0):.3f}): المتغير {col_x} يفسر حوالي {r2_pct:.1f}% من التباين في {col_y}.",
            "القيود المنهجية:",
        ]
        for lim in corr_res.get("limitations", []):
            findings.append(f"  • {lim}")

        return findings


# --- From data_quality.py ---
class DataQualityEngine:
    """Deterministic mathematical and integrity engine for dataset quality auditing."""

    @classmethod
    def check_missing_values(cls, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Audit null, empty strings, 'None', 'NULL', and whitespace values across all columns."""
        if not rows:
            return {"total_rows": 0, "total_missing_cells": 0, "columns": {}}

        total_rows = len(rows)
        col_missing: Dict[str, int] = {}
        all_cols = list(rows[0].keys())

        for c in all_cols:
            col_missing[c] = 0

        for r in rows:
            for c in all_cols:
                v = r.get(c)
                if v is None or (isinstance(v, str) and (v.strip() == "" or v.strip().lower() in ("null", "none", "nan", "n/a"))):
                    col_missing[c] += 1

        col_reports = {}
        total_missing = sum(col_missing.values())
        for c, count in col_missing.items():
            pct = (count / total_rows * 100.0) if total_rows > 0 else 0.0
            severity = "critical" if pct >= 50.0 else ("warning" if pct >= 10.0 else ("info" if pct > 0 else "clean"))
            col_reports[c] = {
                "missing_count": count,
                "missing_pct": round(pct, 2),
                "severity": severity,
            }

        return {
            "total_rows": total_rows,
            "total_columns": len(all_cols),
            "total_cells": total_rows * len(all_cols),
            "total_missing_cells": total_missing,
            "overall_completeness_pct": round(((total_rows * len(all_cols) - total_missing) / (total_rows * len(all_cols)) * 100.0), 2) if total_rows * len(all_cols) > 0 else 100.0,
            "columns": col_reports,
        }

    @classmethod
    def check_duplicate_rows(cls, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect exact duplicate rows across all fields."""
        if not rows:
            return {"duplicate_count": 0, "duplicate_pct": 0.0, "unique_rows": 0}

        seen = set()
        duplicate_count = 0
        for r in rows:
            # Create immutable representation of row dict
            row_key = tuple(sorted((k, str(v)) for k, v in r.items()))
            if row_key in seen:
                duplicate_count += 1
            else:
                seen.add(row_key)

        total_rows = len(rows)
        pct = (duplicate_count / total_rows * 100.0) if total_rows > 0 else 0.0
        return {
            "total_rows": total_rows,
            "duplicate_count": duplicate_count,
            "duplicate_pct": round(pct, 2),
            "unique_rows": len(seen),
            "severity": "critical" if pct > 20.0 else ("warning" if duplicate_count > 0 else "clean"),
        }

    @classmethod
    def check_invalid_ranges(
        cls,
        rows: List[Dict[str, Any]],
        numeric_cols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Detect invalid ranges such as negative prices/amounts or impossible values."""
        if not rows:
            return {"invalid_count": 0, "violations": []}

        if numeric_cols is None:
            numeric_cols = [
                k for k, v in rows[0].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]

        violations = []
        for col in numeric_cols:
            col_lower = col.lower()
            # Rules: price, quantity, amount, total, cost, count, age should not be negative
            should_be_non_negative = any(
                term in col_lower for term in ("price", "quantity", "qty", "amount", "total", "cost", "count", "age", "fee", "sales", "revenue")
            )
            negative_count = 0
            for idx, r in enumerate(rows):
                try:
                    v = float(r.get(col, 0))
                    if should_be_non_negative and v < 0:
                        negative_count += 1
                except (ValueError, TypeError):
                    pass

            if negative_count > 0:
                pct = (negative_count / len(rows) * 100.0)
                violations.append({
                    "column": col,
                    "issue": "negative_values_in_strictly_positive_field",
                    "invalid_count": negative_count,
                    "invalid_pct": round(pct, 2),
                    "description": f"Column '{col}' has {negative_count} negative values ({pct:.1f}%), which violates expected non-negative constraints.",
                })

        return {
            "total_violations": len(violations),
            "violations": violations,
        }

    @classmethod
    def check_high_cardinality(
        cls,
        rows: List[Dict[str, Any]],
        categorical_cols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Detect columns with unusually high distinct cardinality (>80% distinct on non-ID columns)."""
        if not rows:
            return {"high_cardinality_columns": []}

        total_rows = len(rows)
        if total_rows < 5:
            return {"high_cardinality_columns": []}

        if categorical_cols is None:
            categorical_cols = [
                k for k, v in rows[0].items()
                if not (isinstance(v, (int, float)) and not isinstance(v, bool))
            ]

        high_card_cols = []
        for col in categorical_cols:
            if col.lower().endswith(("_id", "id", "uuid", "guid", "code")):
                continue
            distinct_vals = {str(r.get(col, "")) for r in rows}
            cardinality_ratio = len(distinct_vals) / total_rows
            if cardinality_ratio > 0.8:
                high_card_cols.append({
                    "column": col,
                    "distinct_count": len(distinct_vals),
                    "total_rows": total_rows,
                    "cardinality_ratio": round(cardinality_ratio, 2),
                    "description": f"Column '{col}' has near-unique cardinality ({len(distinct_vals)}/{total_rows} distinct, {cardinality_ratio*100:.1f}%), indicating possible identifier status or free text.",
                })

        return {"high_cardinality_columns": high_card_cols}

    @classmethod
    def check_low_variance(
        cls,
        rows: List[Dict[str, Any]],
        numeric_cols: Optional[List[str]] = None,
        categorical_cols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Detect zero or near-zero variance columns (single constant value across all rows)."""
        if not rows:
            return {"low_variance_columns": []}

        total_rows = len(rows)
        low_var_cols = []

        # Check categorical single values
        if categorical_cols is None:
            categorical_cols = [
                k for k, v in rows[0].items()
                if not (isinstance(v, (int, float)) and not isinstance(v, bool))
            ]
        for col in categorical_cols:
            distinct_vals = {str(r.get(col, "")) for r in rows}
            if len(distinct_vals) == 1 and total_rows > 1:
                low_var_cols.append({
                    "column": col,
                    "type": "constant_categorical",
                    "constant_value": list(distinct_vals)[0],
                    "description": f"Column '{col}' is constant across all {total_rows} rows with value '{list(distinct_vals)[0]}'.",
                })

        # Check numeric zero variance
        if numeric_cols is None:
            numeric_cols = [
                k for k, v in rows[0].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
        for col in numeric_cols:
            vals = [float(r[col]) for r in rows if r.get(col) is not None]
            if len(vals) > 1:
                distinct_num = set(vals)
                if len(distinct_num) == 1:
                    low_var_cols.append({
                        "column": col,
                        "type": "constant_numeric",
                        "constant_value": vals[0],
                        "description": f"Column '{col}' has zero variance (constant numeric value {vals[0]}).",
                    })

        return {"low_variance_columns": low_var_cols}

    @classmethod
    def check_inconsistent_categories(
        cls,
        rows: List[Dict[str, Any]],
        categorical_cols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Detect casing discrepancies ('Egypt' vs 'egypt') and leading/trailing whitespace variations."""
        if not rows:
            return {"inconsistencies": []}

        if categorical_cols is None:
            categorical_cols = [
                k for k, v in rows[0].items()
                if not (isinstance(v, (int, float)) and not isinstance(v, bool))
            ]

        inconsistencies = []
        for col in categorical_cols:
            raw_values = [str(r.get(col, "")) for r in rows if r.get(col) is not None]
            casing_map: Dict[str, Set[str]] = {}
            whitespace_issues = 0

            for v in raw_values:
                if v != v.strip():
                    whitespace_issues += 1
                norm = v.strip().lower()
                if norm not in casing_map:
                    casing_map[norm] = set()
                casing_map[norm].add(v.strip())

            # Find normalized keys that map to multiple distinct surface spellings
            multi_casing = {k: list(v_set) for k, v_set in casing_map.items() if len(v_set) > 1}

            if multi_casing or whitespace_issues > 0:
                inconsistencies.append({
                    "column": col,
                    "casing_conflicts": multi_casing,
                    "whitespace_issues_count": whitespace_issues,
                    "description": f"Column '{col}' has {len(multi_casing)} casing conflicts (e.g., {list(multi_casing.values())[:2]}) and {whitespace_issues} whitespace inconsistencies.",
                })

        return {"inconsistencies": inconsistencies}

    @classmethod
    def audit_dataset(
        cls,
        rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Run complete 7-dimension data quality audit and calculate overall quality score (0-100%)."""
        if not rows:
            return {
                "overall_quality_score": 0.0,
                "total_rows": 0,
                "missing_summary": {},
                "duplicate_summary": {},
                "outlier_summary": {},
                "invalid_ranges_summary": {},
                "high_cardinality_summary": {},
                "low_variance_summary": {},
                "inconsistency_summary": {},
                "critical_warnings": ["Dataset is empty (0 rows)."],
            }

        # 1. Missing Values
        missing = cls.check_missing_values(rows)

        # 2. Duplicates
        duplicates = cls.check_duplicate_rows(rows)

        # 3. Numeric Outliers via Anomaly Engine
        from app.services.analysis.engines import AnomalyDetectionEngine
        numeric_cols = [
            k for k, v in rows[0].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        outliers_report = {}
        for num_col in numeric_cols:
            out_res = AnomalyDetectionEngine.detect_all(rows, metric_col=num_col)
            if out_res.get("anomalies"):
                outliers_report[num_col] = {
                    "count": len(out_res["anomalies"]),
                    "anomalies": out_res["anomalies"][:3],
                }

        # 4. Invalid Ranges
        invalid_ranges = cls.check_invalid_ranges(rows, numeric_cols=numeric_cols)

        # 5. High Cardinality
        high_card = cls.check_high_cardinality(rows)

        # 6. Low Variance
        low_var = cls.check_low_variance(rows, numeric_cols=numeric_cols)

        # 7. Inconsistent Categories
        inconsistencies = cls.check_inconsistent_categories(rows)

        # Compute Quality Score (0 to 100)
        score = 100.0
        critical_warnings = []

        # Deduct for missingness
        comp_pct = missing.get("overall_completeness_pct", 100.0)
        score -= (100.0 - comp_pct) * 0.4

        # Deduct for duplicates
        dup_pct = duplicates.get("duplicate_pct", 0.0)
        score -= dup_pct * 0.3
        if dup_pct > 10.0:
            critical_warnings.append(f"High duplicate rate: {dup_pct:.1f}% duplicate rows detected.")

        # Deduct for invalid ranges
        if invalid_ranges.get("total_violations", 0) > 0:
            score -= min(15.0, invalid_ranges["total_violations"] * 5.0)
            critical_warnings.append(f"Invalid range violations detected in {invalid_ranges['total_violations']} columns.")

        # Deduct for casing inconsistencies
        if inconsistencies.get("inconsistencies"):
            score -= min(10.0, len(inconsistencies["inconsistencies"]) * 3.0)

        final_score = max(0.0, min(100.0, round(score, 1)))

        return {
            "overall_quality_score": final_score,
            "total_rows": len(rows),
            "missing_summary": missing,
            "duplicate_summary": duplicates,
            "outlier_summary": outliers_report,
            "invalid_ranges_summary": invalid_ranges,
            "high_cardinality_summary": high_card,
            "low_variance_summary": low_var,
            "inconsistency_summary": inconsistencies,
            "critical_warnings": critical_warnings,
        }

    @classmethod
    def generate_findings(cls, audit: Dict[str, Any]) -> List[str]:
        """Generate structured text report from data quality audit."""
        findings = []
        score = audit.get("overall_quality_score", 100.0)
        n = audit.get("total_rows", 0)
        findings.append(f"تقرير جودة واكتمال البيانات (Data Quality Score: {score:.1f}/100 عبر {n} سجل):")

        # Missing values
        comp = audit.get("missing_summary", {}).get("overall_completeness_pct", 100.0)
        findings.append(f"• نسبة الاكتمال الكلية: {comp:.1f}% ({audit.get('missing_summary', {}).get('total_missing_cells', 0)} خلية فارغة).")

        # Duplicates
        dup = audit.get("duplicate_summary", {})
        if dup.get("duplicate_count", 0) > 0:
            findings.append(f"• السجلات المكررة: تم رصد {dup['duplicate_count']} صف مكرر ({dup['duplicate_pct']:.1f}%).")
        else:
            findings.append("• السجلات المكررة: لا توجد صفوف مكررة (0%).")

        # Invalid ranges
        inv = audit.get("invalid_ranges_summary", {})
        for v in inv.get("violations", []):
            findings.append(f"• قيم خارج النطاق المنطقي: {v['description']}")

        # Low variance
        low = audit.get("low_variance_summary", {})
        for lv in low.get("low_variance_columns", []):
            findings.append(f"• أعمدة أحادية القيمة / عديمة التباين: {lv['description']}")

        # Inconsistent categories
        inc = audit.get("inconsistency_summary", {})
        for in_item in inc.get("inconsistencies", []):
            findings.append(f"• تباين في تنسيق الفئات: {in_item['description']}")

        # Outliers
        out = audit.get("outlier_summary", {})
        for c, out_info in out.items():
            findings.append(f"• قيم شاذة إحصائياً في '{c}': تم رصد {out_info['count']} قيمة متطرفة.")

        return findings


# --- From distribution.py ---
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


# --- From forecasting.py ---
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


# --- From root_cause.py ---
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


# --- From statistical_testing.py ---
class StatisticalTestingEngine:
    """Deterministic mathematical engine for hypothesis testing and statistical significance."""

    @classmethod
    def _approx_p_value_from_z(cls, z: float) -> float:
        """Approximate two-tailed p-value from standard normal Z score using error function."""
        return max(0.0001, min(1.0, 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))))

    @classmethod
    def _approx_p_value_from_t(cls, t: float, df: float) -> float:
        """Approximate two-tailed p-value for Student's t distribution."""
        if df <= 0:
            return 1.0
        # For moderate-to-large df, t-distribution converges to standard normal
        # Apply Hill's approximation correction for smaller df
        z = abs(t) * (1.0 - 1.0 / (4.0 * df))
        return cls._approx_p_value_from_z(z)

    @classmethod
    def _approx_p_value_from_f(cls, f_stat: float, df1: float, df2: float) -> float:
        """Approximate p-value for F-distribution (ANOVA)."""
        if f_stat <= 0 or df1 <= 0 or df2 <= 0:
            return 1.0
        # Paulson's approximation transform F to standard normal
        term1 = (1.0 - 2.0 / (9.0 * df2)) * (f_stat ** (1.0 / 3.0))
        term2 = 1.0 - 2.0 / (9.0 * df1)
        denom = math.sqrt((2.0 / (9.0 * df2)) * (f_stat ** (2.0 / 3.0)) + (2.0 / (9.0 * df1)))
        if denom > 0:
            z = (term1 - term2) / denom
            return max(0.0001, min(1.0, 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))
        return 0.5

    @classmethod
    def two_sample_t_test(
        cls,
        group_a: List[float],
        group_b: List[float],
        name_a: str = "Group A",
        name_b: str = "Group B",
    ) -> Dict[str, Any]:
        """Perform Welch's two-sample t-test for unequal variances."""
        n1, n2 = len(group_a), len(group_b)
        if n1 < 2 or n2 < 2:
            return {
                "test": "Welch's t-test",
                "is_significant": False,
                "p_value": 1.0,
                "error": "Minimum 2 data points required per group.",
            }

        mean1 = sum(group_a) / n1
        mean2 = sum(group_b) / n2

        var1 = sum((x - mean1) ** 2 for x in group_a) / (n1 - 1)
        var2 = sum((x - mean2) ** 2 for x in group_b) / (n2 - 1)

        se1 = var1 / n1
        se2 = var2 / n2
        se_diff = math.sqrt(se1 + se2)

        if se_diff == 0:
            t_stat = 0.0
            p_val = 1.0
            df = n1 + n2 - 2
        else:
            t_stat = (mean1 - mean2) / se_diff
            # Welch-Satterthwaite equation for degrees of freedom
            df_num = (se1 + se2) ** 2
            df_den = (se1 ** 2 / (n1 - 1)) + (se2 ** 2 / (n2 - 1))
            df = df_num / df_den if df_den > 0 else (n1 + n2 - 2)
            p_val = cls._approx_p_value_from_t(t_stat, df)

        is_sig = p_val < 0.05

        return {
            "test": "Welch's Two-Sample t-test",
            "group_a": {"name": name_a, "sample_size": n1, "mean": round(mean1, 2), "std_dev": round(math.sqrt(var1), 2)},
            "group_b": {"name": name_b, "sample_size": n2, "mean": round(mean2, 2), "std_dev": round(math.sqrt(var2), 2)},
            "mean_difference": round(mean1 - mean2, 2),
            "t_statistic": round(t_stat, 3),
            "degrees_of_freedom": round(df, 1),
            "p_value": round(p_val, 4),
            "is_significant": is_sig,
            "significance_level": 0.05,
        }

    @classmethod
    def mann_whitney_u_test(
        cls,
        group_a: List[float],
        group_b: List[float],
        name_a: str = "Group A",
        name_b: str = "Group B",
    ) -> Dict[str, Any]:
        """Perform non-parametric Mann-Whitney U test."""
        n1, n2 = len(group_a), len(group_b)
        if n1 < 2 or n2 < 2:
            return {"test": "Mann-Whitney U", "is_significant": False, "p_value": 1.0}

        # Combine and rank data points
        combined = [(v, 0) for v in group_a] + [(v, 1) for v in group_b]
        combined.sort(key=lambda x: x[0])

        ranks = [0.0] * len(combined)
        i = 0
        while i < len(combined):
            j = i
            while j < len(combined) and combined[j][0] == combined[i][0]:
                j += 1
            avg_rank = (i + 1 + j) / 2.0
            for k in range(i, j):
                ranks[k] = avg_rank
            i = j

        rank_sum_a = sum(ranks[k] for k in range(len(combined)) if combined[k][1] == 0)
        u1 = rank_sum_a - (n1 * (n1 + 1)) / 2.0
        u2 = n1 * n2 - u1
        u_stat = min(u1, u2)

        # Normal approximation
        mu_u = (n1 * n2) / 2.0
        sigma_u = math.sqrt((n1 * n2 * (n1 + n2 + 1)) / 12.0)
        z = (u_stat - mu_u) / sigma_u if sigma_u > 0 else 0.0
        p_val = cls._approx_p_value_from_z(z)

        return {
            "test": "Mann-Whitney U Test (Non-Parametric)",
            "group_a": {"name": name_a, "sample_size": n1, "rank_sum": round(rank_sum_a, 1)},
            "group_b": {"name": name_b, "sample_size": n2},
            "u_statistic": round(u_stat, 2),
            "z_score": round(z, 3),
            "p_value": round(p_val, 4),
            "is_significant": p_val < 0.05,
        }

    @classmethod
    def one_way_anova(
        cls,
        groups: Dict[str, List[float]],
    ) -> Dict[str, Any]:
        """Perform One-Way ANOVA across 3 or more groups."""
        valid_groups = {k: v for k, v in groups.items() if len(v) >= 2}
        k = len(valid_groups)
        if k < 2:
            return {"test": "One-Way ANOVA", "is_significant": False, "p_value": 1.0}

        total_n = sum(len(v) for v in valid_groups.values())
        grand_sum = sum(sum(v) for v in valid_groups.values())
        grand_mean = grand_sum / total_n

        # Between-group sum of squares
        ss_between = sum(len(v) * ((sum(v) / len(v)) - grand_mean) ** 2 for v in valid_groups.values())
        df_between = k - 1
        ms_between = ss_between / df_between if df_between > 0 else 0.0

        # Within-group sum of squares
        ss_within = sum(sum((x - (sum(v) / len(v))) ** 2 for x in v) for v in valid_groups.values())
        df_within = total_n - k
        ms_within = ss_within / df_within if df_within > 0 else 0.0

        f_stat = ms_between / ms_within if ms_within > 0 else 0.0
        p_val = cls._approx_p_value_from_f(f_stat, df_between, df_within)

        group_summaries = {
            name: {"count": len(vals), "mean": round(sum(vals) / len(vals), 2)}
            for name, vals in valid_groups.items()
        }

        return {
            "test": "One-Way ANOVA",
            "group_count": k,
            "total_observations": total_n,
            "f_statistic": round(f_stat, 3),
            "df_between": df_between,
            "df_within": df_within,
            "p_value": round(p_val, 4),
            "is_significant": p_val < 0.05,
            "group_summaries": group_summaries,
        }

    @classmethod
    def chi_square_test(
        cls,
        rows: List[Dict[str, Any]],
        col_a: str,
        col_b: str,
    ) -> Dict[str, Any]:
        """Perform Pearson Chi-Square Test of Independence for two categorical columns."""
        if not rows:
            return {"test": "Chi-Square", "is_significant": False, "p_value": 1.0}

        # Build contingency table
        table: Dict[str, Dict[str, int]] = {}
        for r in rows:
            va = str(r.get(col_a, "Unknown")).strip()
            vb = str(r.get(col_b, "Unknown")).strip()
            if va not in table:
                table[va] = {}
            table[va][vb] = table[va].get(vb, 0) + 1

        row_labels = list(table.keys())
        col_labels = list({vb for va in table.values() for vb in va.keys()})

        r_len = len(row_labels)
        c_len = len(col_labels)
        if r_len < 2 or c_len < 2:
            return {"test": "Chi-Square", "is_significant": False, "p_value": 1.0}

        total_n = len(rows)
        row_totals = {va: sum(table[va].get(vb, 0) for vb in col_labels) for va in row_labels}
        col_totals = {vb: sum(table.get(va, {}).get(vb, 0) for va in row_labels) for vb in col_labels}

        chi2 = 0.0
        for va in row_labels:
            for vb in col_labels:
                observed = table[va].get(vb, 0)
                expected = (row_totals[va] * col_totals[vb]) / total_n
                if expected > 0:
                    chi2 += ((observed - expected) ** 2) / expected

        df = (r_len - 1) * (c_len - 1)
        # Approximate p-value from Chi-square distribution using Wilson-Hilferty transformation
        z = math.sqrt(2.0 * chi2) - math.sqrt(2.0 * df - 1.0) if df > 1 else math.sqrt(chi2)
        p_val = cls._approx_p_value_from_z(z)

        return {
            "test": "Chi-Square Test of Independence",
            "col_a": col_a,
            "col_b": col_b,
            "chi2_statistic": round(chi2, 3),
            "degrees_of_freedom": df,
            "p_value": round(p_val, 4),
            "is_significant": p_val < 0.05,
        }

    @classmethod
    def auto_test(
        cls,
        rows: List[Dict[str, Any]],
        metric_col: Optional[str] = None,
        group_col: Optional[str] = None,
        second_cat_col: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Automatically select and execute the appropriate statistical test based on available variables."""
        if not rows:
            return {"test": "none", "is_significant": False}

        # Case 1: Two categorical variables -> Chi-Square
        if second_cat_col and group_col:
            return cls.chi_square_test(rows, col_a=group_col, col_b=second_cat_col)

        # Case 2: Numeric metric + Grouping dimension
        if metric_col and group_col:
            groups: Dict[str, List[float]] = {}
            for r in rows:
                g = str(r.get(group_col, "Unknown"))
                try:
                    v = float(r.get(metric_col, 0.0))
                    if g not in groups:
                        groups[g] = []
                    groups[g].append(v)
                except (ValueError, TypeError):
                    pass

            distinct_groups = list(groups.keys())
            if len(distinct_groups) == 2:
                g1, g2 = distinct_groups[0], distinct_groups[1]
                return cls.two_sample_t_test(groups[g1], groups[g2], name_a=g1, name_b=g2)
            elif len(distinct_groups) >= 3:
                return cls.one_way_anova(groups)

        # Fallback: Single sample descriptive test
        vals = [float(r[metric_col]) for r in rows if r.get(metric_col) is not None] if metric_col else []
        return {
            "test": "Descriptive Sample Variance",
            "sample_size": len(vals),
            "mean": round(sum(vals) / len(vals), 2) if vals else 0.0,
            "is_significant": False,
        }

    @classmethod
    def generate_findings(cls, test_res: Dict[str, Any]) -> List[str]:
        """Generate human-readable statistical conclusions."""
        test_name = test_res.get("test", "Statistical Test")
        p_val = test_res.get("p_value", 1.0)
        is_sig = test_res.get("is_significant", False)
        sig_str = "يوجد فرق ذو دلالة إحصائية (Statistically Significant)" if is_sig else "لا يوجد فرق ذو دلالة إحصائية (Not Significant)"

        findings = [
            f"نتائج الاختبار الإحصائي ({test_name}):",
            f"• الحكم الإحصائي: {sig_str} عند مستوى دلالة α = 0.05 (p-value = {p_val:.4f}).",
        ]

        if "group_a" in test_res and "group_b" in test_res:
            ga = test_res["group_a"]
            gb = test_res["group_b"]
            findings.append(
                f"• مقارنة المجموعتين: {ga['name']} (متوسط: {ga.get('mean', 'N/A')}) مقابل "
                f"{gb['name']} (متوسط: {gb.get('mean', 'N/A')}) — فرق المتوسطين: {test_res.get('mean_difference', 0):+,.2f} "
                f"(t = {test_res.get('t_statistic', 0):.2f}, df = {test_res.get('degrees_of_freedom', 0)})."
            )
        elif "group_summaries" in test_res:
            findings.append(f"• اختبار ANOVA للمقارنة بين {test_res.get('group_count')} مجموعات (F = {test_res.get('f_statistic', 0):.2f}).")

        return findings


# --- From trend.py ---
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
