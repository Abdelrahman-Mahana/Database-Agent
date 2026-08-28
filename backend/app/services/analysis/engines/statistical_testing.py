"""Statistical Testing Engine.

Implements deterministic hypothesis testing:
1. Two-sample Welch's t-test (comparing means of 2 numeric groups, e.g., Cairo vs Alexandria).
2. Mann-Whitney U test (non-parametric rank comparison for skewed distributions).
3. One-way ANOVA F-test (comparing means across 3+ groups).
4. Chi-Square Test of Independence (comparing association between 2 categorical variables).
"""
import math
from typing import Any, Dict, List, Optional, Tuple


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
