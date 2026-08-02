"""Phase 8 — regression comparison for CI.

Usage:
    python -m eval.run_baseline --save /tmp/before.json     # on main branch
    # ... make your change ...
    python -m eval.run_baseline --save /tmp/after.json      # on your branch
    python -m eval.compare_baseline /tmp/before.json /tmp/after.json

Exits non-zero (fails the CI step) if type accuracy or grounding recall
dropped on either database — the whole point of Phase 0's baseline is that
a change to prompts/models/grounding logic should never be able to quietly
regress accuracy; this makes that a hard CI gate instead of something that
only gets noticed if someone happens to eyeball the eval output.

Token-reduction changes are reported but never fail the build — a
regression in efficiency is worth knowing about, but shouldn't block a
merge the way an accuracy regression should.
"""
import argparse
import json
import sys


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare(before_path: str, after_path: str) -> bool:
    before = {r["label"]: r for r in _load(before_path)["results"]}
    after = {r["label"]: r for r in _load(after_path)["results"]}

    ok = True
    print(f"{'Database':<12} {'Metric':<20} {'Before':>10} {'After':>10} {'Delta':>10}")
    print("-" * 64)
    for label in after:
        if label not in before:
            print(f"{label:<12} (new — no baseline to compare)")
            continue
        b, a = before[label], after[label]
        for metric, fmt, is_pct, fail_on_drop in [
            ("type_accuracy", "{:.0%}", True, True),
            ("grounding_recall", "{:.0%}", True, True),
            ("reduction_pct", "{:.0f}%", False, False),
        ]:
            b_val, a_val = b[metric], a[metric]
            delta = a_val - b_val
            flag = ""
            if fail_on_drop and delta < -0.001:
                flag = "  <-- REGRESSION"
                ok = False
            delta_str = f"{delta:+.0%}" if is_pct else f"{delta:+.0f}pp"
            print(f"{label:<12} {metric:<20} {fmt.format(b_val):>10} {fmt.format(a_val):>10} {delta_str:>10}{flag}")

    print()
    print("RESULT: " + ("PASS — no accuracy regressions" if ok else "FAIL — accuracy regression detected"))
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    passed = compare(args.before, args.after)
    sys.exit(0 if passed else 1)
