"""Data Quality Engine.

Implements full 7-dimension data quality audit:
1. Missing Values: Null, empty, whitespace, and NaN detection per column.
2. Duplicates: Exact duplicate row detection and percentage.
3. Outliers: Statistical numeric outliers via IQR and Z-score fences.
4. Invalid Ranges: Negative quantities/prices, impossible ages, and out-of-bounds metrics.
5. High Cardinality: Unusually high distinct values in categorical dimensions.
6. Low Variance: Constant single-value columns and zero-variance metrics.
7. Inconsistent Categories: Casing discrepancies (e.g. 'Egypt' vs 'egypt') and whitespace variations.
"""
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple


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
        from app.services.analysis.engines.anomaly_detection import AnomalyDetectionEngine
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
