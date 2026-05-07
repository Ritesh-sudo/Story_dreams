#!/usr/bin/env python3
"""
run_evals.py — runs all test prompts through the full pipeline and prints a
summary table of average rubric scores, pass rate, and average revision rounds.

Usage:
    python evals/run_evals.py

Output:
    - evals/results.json  (detailed per-prompt results)
    - Console summary table
"""

import json
import sys
import os
import time
from pathlib import Path

# Run from the project root so imports resolve correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.classifier import RequestClassifier
from agents.planner import StoryPlanner
from agents.storyteller import Storyteller
from agents.judge import JudgeAgent
from pipeline.revision_loop import RevisionLoop

PROMPTS_FILE = Path(__file__).parent / "test_prompts.json"
RESULTS_FILE = Path(__file__).parent / "results.json"

RUBRIC_DIMS = [
    "safety",
    "age_appropriateness",
    "narrative_arc_quality",
    "engagement",
    "language_level",
    "originality",
]


def run_single(prompt_entry: dict) -> dict:
    """Runs one eval prompt through the full pipeline and returns the result."""
    prompt   = prompt_entry["prompt"]
    eval_id  = prompt_entry["id"]

    print(f"\n  [{eval_id}] {prompt[:60]}…")

    classifier  = RequestClassifier()
    planner     = StoryPlanner()
    storyteller = Storyteller()
    judge       = JudgeAgent()
    r_loop      = RevisionLoop(storyteller, judge)

    t0 = time.time()

    classification = classifier.classify(prompt)
    category       = classification["category"]
    print(f"         Category  : {category}")

    outline = planner.plan(prompt, category)
    story   = storyteller.write(outline, category)

    result  = r_loop.run(story, prompt)
    judgment = result["judgment"]

    elapsed = round(time.time() - t0, 1)

    scores = judgment.get("scores", {})
    dim_scores = {dim: scores.get(dim, {}).get("score", 0) for dim in RUBRIC_DIMS}

    print(f"         Overall   : {judgment['overall_score']:.1f}/10  "
          f"({'PASS' if judgment['pass_threshold'] else 'FAIL'})  "
          f"rounds={result['rounds']}  ({elapsed}s)")

    return {
        "id":               eval_id,
        "prompt":           prompt,
        "expected_category":prompt_entry.get("expected_category", ""),
        "detected_category":category,
        "category_correct": category == prompt_entry.get("expected_category", ""),
        "overall_score":    judgment["overall_score"],
        "passed":           judgment["pass_threshold"],
        "revision_rounds":  result["rounds"],
        "used_fallback":    result["used_fallback"],
        "dim_scores":       dim_scores,
        "reasoning":        judgment.get("reasoning", ""),
        "revision_notes":   judgment.get("specific_revision_notes", []),
        "elapsed_s":        elapsed,
    }


def print_summary(results: list[dict]):
    """Prints a formatted summary table to stdout."""
    n = len(results)
    if n == 0:
        print("No results.")
        return

    pass_rate   = sum(1 for r in results if r["passed"]) / n * 100
    avg_score   = sum(r["overall_score"] for r in results) / n
    avg_rounds  = sum(r["revision_rounds"] for r in results) / n
    cat_correct = sum(1 for r in results if r["category_correct"]) / n * 100

    avg_dims = {
        dim: sum(r["dim_scores"].get(dim, 0) for r in results) / n
        for dim in RUBRIC_DIMS
    }

    sep = "─" * 56
    print(f"\n{'═' * 56}")
    print(f"  EVAL SUMMARY  ({n} prompts)")
    print(f"{'═' * 56}")
    print(f"  Pass rate          : {pass_rate:.0f}%  ({sum(r['passed'] for r in results)}/{n})")
    print(f"  Avg overall score  : {avg_score:.2f} / 10")
    print(f"  Avg revision rounds: {avg_rounds:.2f}")
    print(f"  Category accuracy  : {cat_correct:.0f}%")
    print(sep)
    print("  Avg scores by rubric dimension:")
    for dim, avg in sorted(avg_dims.items(), key=lambda x: -x[1]):
        bar = "█" * round(avg) + "░" * (10 - round(avg))
        print(f"    {dim:<25} {bar}  {avg:.2f}")
    print(sep)
    print("  Per-prompt results:")
    print(f"    {'ID':<10} {'Score':>6}  {'Pass':>5}  {'Rnds':>5}  Category")
    print(f"    {'─'*10} {'─'*6}  {'─'*5}  {'─'*5}  {'─'*20}")
    for r in results:
        ok  = "PASS" if r["passed"] else "FAIL"
        cat = r["detected_category"]
        print(f"    {r['id']:<10} {r['overall_score']:>5.1f}  {ok:>5}  "
              f"{r['revision_rounds']:>5}  {cat}")
    print(f"{'═' * 56}\n")


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.")
        sys.exit(1)

    prompts = json.loads(PROMPTS_FILE.read_text())
    print(f"Running {len(prompts)} eval prompts…")

    results = []
    failed  = []

    for entry in prompts:
        try:
            result = run_single(entry)
            results.append(result)
        except Exception as exc:
            print(f"  ERROR on {entry['id']}: {exc}")
            failed.append({"id": entry["id"], "error": str(exc)})

    # Save results
    output = {"results": results, "failures": failed}
    RESULTS_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nDetailed results saved to {RESULTS_FILE}")

    print_summary(results)

    if failed:
        print(f"  {len(failed)} eval(s) failed with errors:")
        for f in failed:
            print(f"    {f['id']}: {f['error']}")


if __name__ == "__main__":
    main()
