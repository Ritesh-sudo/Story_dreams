#!/usr/bin/env python3
"""
judge_consistency.py — tests the README claim that the judge's overall score varies
by <= 0.5 points across identical inputs.

Picks 5 stories from an eval-run results file (fixed seed, so the choice is
reproducible and not cherry-picked), judges each one 5 times with the same
JudgeAgent call the revision loop uses, and reports the standard deviation and
max-min range of the overall score per story.

Usage:
    python evals/judge_consistency.py evals/results/eval_run_<ts>.json
Output:
    evals/results/judge_consistency_<UTC timestamp>.json
"""

import json
import os
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import run_evals
from run_evals import RUBRIC_DIMS, UsageMeter, DailyLimitReached, RESULTS_DIR
from agents.judge import JudgeAgent
from utils.openai_client import get_model

N_STORIES = 5
N_REPEATS = 5
MAX_EXTRA_ATTEMPTS = 3     # judge crashes are logged; up to this many extra tries per story
SEED = 0
CLAIM_RANGE = 0.5


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.")
        sys.exit(1)
    src = Path(sys.argv[1])
    run = json.loads(src.read_text())
    if run["meta"]["model"] != get_model():
        print(f"ERROR: results file used {run['meta']['model']!r}, current model is {get_model()!r}")
        sys.exit(1)

    ids = sorted(r["id"] for r in run["results"])
    chosen = sorted(random.Random(SEED).sample(ids, N_STORIES))
    by_id = {r["id"]: r for r in run["results"]}
    print(f"Stories (seed {SEED}): {chosen}")

    now = datetime.now(timezone.utc)
    out_path = RESULTS_DIR / f"judge_consistency_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    doc = {
        "meta": {
            "timestamp_utc": now.isoformat(),
            "model": get_model(),
            "source_results_file": src.name,
            "seed": SEED, "n_stories": N_STORIES, "n_repeats": N_REPEATS,
            "claim_max_range": CLAIM_RANGE,
            "extra_request_params": run_evals.EXTRA_REQUEST_PARAMS,
            "judged_text": "final_story (the version the revision loop returned)",
        },
        "stories": [],
    }

    meter = UsageMeter()
    meter.install()
    judge = JudgeAgent()
    try:
        for sid in chosen:
            r = by_id[sid]
            samples, errors = [], []
            attempts = 0
            while len(samples) < N_REPEATS and attempts < N_REPEATS + MAX_EXTRA_ATTEMPTS:
                attempts += 1
                try:
                    j = judge.evaluate(r["final_story"], r["prompt"])
                except DailyLimitReached:
                    raise
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                    print(f"   {sid} attempt {attempts}: ERROR {errors[-1][:80]}")
                    continue
                sc = j.get("scores", {})
                samples.append({
                    "overall": j["overall_score"],
                    "passed": bool(j["pass_threshold"]),
                    "dims": {d: sc.get(d, {}).get("score") for d in RUBRIC_DIMS},
                    "parse_error": str(j.get("reasoning", "")).startswith("Parse error"),
                })
            overall = [s["overall"] for s in samples]
            entry = {
                "id": sid, "prompt": r["prompt"], "samples": samples, "errors": errors,
                "attempts": attempts, "n": len(overall),
                "mean": statistics.mean(overall) if overall else None,
                "stdev": statistics.stdev(overall) if len(overall) > 1 else None,  # sample stdev
                "range": (max(overall) - min(overall)) if overall else None,
                "pass_count": sum(s["passed"] for s in samples),
                "loop_final_overall": r["final"]["overall_score"],
            }
            doc["stories"].append(entry)
            out_path.write_text(json.dumps(doc, indent=2))
            print(f"   {sid}: n={entry['n']} scores={overall} "
                  f"stdev={entry['stdev']:.3f} range={entry['range']:.2f} "
                  f"passes={entry['pass_count']}/{entry['n']}")
    except DailyLimitReached as exc:
        print(f"\nDAILY LIMIT REACHED: {str(exc)[:400]}\nPartial results saved to {out_path}")
        out_path.write_text(json.dumps(doc, indent=2))
        sys.exit(2)
    finally:
        meter.uninstall()

    ranges = [s["range"] for s in doc["stories"]]
    doc["summary"] = {
        "max_range": max(ranges),
        "stories_within_claim": sum(x <= CLAIM_RANGE for x in ranges),
        "claim_holds_for_all": all(x <= CLAIM_RANGE for x in ranges),
        "any_story_pass_fail_flips": any(0 < s["pass_count"] < s["n"] for s in doc["stories"]),
        **meter.snapshot(),
    }
    out_path.write_text(json.dumps(doc, indent=2))
    print(f"\nSaved {out_path}\n{json.dumps(doc['summary'], indent=2)}")


if __name__ == "__main__":
    main()
