"""Correlation Engine.

Implements full 6-step deterministic correlation evaluation:
1. Retrieve Variable X (e.g., price)
2. Retrieve Variable Y (e.g., quantity)
3. Calculate Pearson correlation (r) & coefficient of determination (R²)
4. Determine relationship direction (positive, negative/inverse, neutral)
5. Determine relationship strength (very strong, strong, moderate, weak, negligible)
6. Explain analytical limitations (causation disclaimer, non-linear caveats, sample size)
"""
import math
from typing import Any, Dict, List, Optional, Tuple


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
