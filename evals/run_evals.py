#!/usr/bin/env python3
"""
run_evals.py — runs every test prompt through the full pipeline ONCE and records,
per prompt: the round-0 (initial draft) judgment, the final judgment, revision
rounds, classification result, latency, API calls and token usage.

The pipeline itself is untouched. Measurement is added by wrapping the judge
instance (to capture every judgment) and the OpenAI `create` call (to count
calls and tokens).

Usage:
    python evals/run_evals.py              # all prompts
    python evals/run_evals.py --limit 2    # smoke test on the first N prompts

Output:
    evals/results/eval_run_<UTC timestamp>.json
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Run from the project root so imports resolve correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import RateLimitError
from openai.resources.chat.completions import Completions

from agents.classifier import RequestClassifier
from agents.planner import StoryPlanner
from agents.storyteller import Storyteller
from agents.judge import (
    JudgeAgent, PASS_SCORE_THRESHOLD, SAFETY_THRESHOLD, RUBRIC_WEIGHTS,
)
from pipeline.revision_loop import RevisionLoop, MAX_REVISION_ROUNDS
from utils.openai_client import get_model

PROMPTS_FILE = Path(__file__).parent / "test_prompts.json"
RESULTS_DIR = Path(__file__).parent / "results"

# Optional extra request params for every chat call (e.g. '{"reasoning_effort": "low"}'
# for reasoning models). Recorded in the results metadata when used.
EXTRA_REQUEST_PARAMS: dict = json.loads(os.getenv("EVAL_EXTRA_PARAMS", "{}"))

RUBRIC_DIMS = [
    "safety",
    "age_appropriateness",
    "narrative_arc_quality",
    "engagement",
    "language_level",
    "originality",
]


# ── Measurement helpers ──────────────────────────────────────────────────────

class DailyLimitReached(Exception):
    """Provider's daily quota is exhausted; stop and resume later."""


MAX_RATE_WAITS = 8       # per-minute (TPM/RPM) 429s waited out per call before giving up


def _is_daily_limit(exc: Exception) -> bool:
    return "per day" in str(exc).lower()


def _retry_after_s(exc: RateLimitError) -> float:
    """Seconds to wait: Retry-After header, else 'try again in 1m2.5s' from the message."""
    try:
        ra = exc.response.headers.get("retry-after")
        if ra:
            return float(ra) + 1
    except Exception:
        pass
    m = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?", str(exc))
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + float(m.group(2) or 0) + 1
    return 20.0


class UsageMeter:
    """Counts chat-completion calls and tokens by wrapping Completions.create.

    Counts one entry per call made by our code. Automatic SDK-level retries on
    429/5xx happen below this wrapper and are not counted.

    Also waits out per-minute rate limits (time recorded in wait_s so it can be
    excluded from latency) and raises DailyLimitReached on a daily-quota 429.
    """

    def __init__(self):
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.wait_s = 0.0
        self._orig = None

    def install(self):
        self._orig = Completions.create
        meter = self

        def wrapped(self_, *args, **kwargs):
            for k, v in EXTRA_REQUEST_PARAMS.items():
                kwargs.setdefault(k, v)
            for attempt in range(MAX_RATE_WAITS + 1):
                try:
                    resp = meter._orig(self_, *args, **kwargs)
                    break
                except RateLimitError as exc:
                    if _is_daily_limit(exc):
                        raise DailyLimitReached(str(exc)) from exc
                    if attempt == MAX_RATE_WAITS:
                        raise
                    wait = min(_retry_after_s(exc), 120.0)
                    print(f"         (rate limited; waiting {wait:.0f}s)", flush=True)
                    time.sleep(wait)
                    meter.wait_s += wait
            meter.calls += 1
            usage = getattr(resp, "usage", None)
            if usage is not None:
                meter.prompt_tokens += usage.prompt_tokens or 0
                meter.completion_tokens += usage.completion_tokens or 0
            return resp

        Completions.create = wrapped

    def uninstall(self):
        if self._orig is not None:
            Completions.create = self._orig
            self._orig = None

    def snapshot(self) -> dict:
        return {
            "api_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
        }

    def reset(self):
        self.calls = self.prompt_tokens = self.completion_tokens = 0
        self.wait_s = 0.0


def _judgment_record(j: dict) -> dict:
    scores = j.get("scores", {})
    return {
        "overall_score": j["overall_score"],
        "passed": bool(j["pass_threshold"]),
        "dim_scores": {d: scores.get(d, {}).get("score") for d in RUBRIC_DIMS},
        # judge.py substitutes an all-5s judgment when the JSON can't be parsed
        "parse_error": str(j.get("reasoning", "")).startswith("Parse error"),
        # a dimension missing from the judge's JSON (e.g. output truncated) makes
        # judge.py average over fewer dimensions, so the overall score is unreliable
        "incomplete": any(scores.get(d, {}).get("score") is None for d in RUBRIC_DIMS),
        "revision_notes": j.get("specific_revision_notes", []),
    }


# ── One prompt ───────────────────────────────────────────────────────────────

def run_single(prompt_entry: dict, meter: UsageMeter) -> dict:
    """Runs one eval prompt through the full pipeline and returns the result."""
    prompt = prompt_entry["prompt"]
    eval_id = prompt_entry["id"]
    expected = prompt_entry.get("expected_category")

    print(f"\n  [{eval_id}] {prompt[:60]}…")

    classifier = RequestClassifier()
    planner = StoryPlanner()
    storyteller = Storyteller()
    judge = JudgeAgent()

    # Capture every judgment (and the story it judged) without changing the loop.
    judged: list[tuple[str, dict]] = []
    orig_evaluate = judge.evaluate

    def recording_evaluate(story, *args, **kwargs):
        j = orig_evaluate(story, *args, **kwargs)
        judged.append((story, j))
        return j

    judge.evaluate = recording_evaluate
    r_loop = RevisionLoop(storyteller, judge)

    meter.reset()
    t0 = time.perf_counter()

    classification = classifier.classify(prompt)
    category = classification["category"]
    classifier_fallback = str(classification.get("reasoning", "")).startswith("Fallback")
    print(f"         Category  : {category}")

    outline = planner.plan(prompt, category)
    story = storyteller.write(outline, category)

    result = r_loop.run(story, prompt)

    wall = time.perf_counter() - t0
    waited = meter.wait_s
    elapsed = round(wall - waited, 2)   # active time, excluding rate-limit sleeps
    usage = meter.snapshot()

    initial_story, initial_j = judged[0]
    final_j = result["judgment"]
    initial = _judgment_record(initial_j)
    final = _judgment_record(final_j)

    print(f"         Initial   : {initial['overall_score']:.2f} "
          f"({'PASS' if initial['passed'] else 'FAIL'})")
    print(f"         Final     : {final['overall_score']:.2f} "
          f"({'PASS' if final['passed'] else 'FAIL'})  "
          f"rounds={result['rounds']}  calls={usage['api_calls']}  ({elapsed}s)")

    return {
        "id": eval_id,
        "prompt": prompt,
        "expected_category": expected,
        "detected_category": category,
        "category_correct": (category == expected) if expected else None,
        "classifier_fallback": classifier_fallback,
        "initial": initial,
        "final": final,
        "revision_rounds": result["rounds"],
        "used_fallback": result["used_fallback"],
        "judge_trace_overall": [j["overall_score"] for _, j in judged],
        "any_round_incomplete": any(_judgment_record(j)["incomplete"] for _, j in judged),
        "latency_s": elapsed,
        "rate_limit_wait_s": round(waited, 2),
        **usage,
        "initial_story": initial_story,
        "final_story": result["story"],
    }


# ── Aggregation / console summary ────────────────────────────────────────────

def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def summarize(results: list[dict]) -> dict:
    n = len(results)
    labeled = [r for r in results if r["category_correct"] is not None]
    return {
        "n": n,
        "first_try_pass_rate": sum(r["initial"]["passed"] for r in results) / n,
        "final_pass_rate": sum(r["final"]["passed"] for r in results) / n,
        "avg_overall_initial": mean(r["initial"]["overall_score"] for r in results),
        "avg_overall_final": mean(r["final"]["overall_score"] for r in results),
        "avg_dims_initial": {
            d: mean(r["initial"]["dim_scores"][d] for r in results) for d in RUBRIC_DIMS},
        "avg_dims_final": {
            d: mean(r["final"]["dim_scores"][d] for r in results) for d in RUBRIC_DIMS},
        "classification_accuracy": (
            sum(r["category_correct"] for r in labeled) / len(labeled) if labeled else None),
        "avg_revision_rounds": mean(r["revision_rounds"] for r in results),
        "avg_latency_s": mean(r["latency_s"] for r in results),
        "avg_api_calls": mean(r["api_calls"] for r in results),
        "total_prompt_tokens": sum(r["prompt_tokens"] for r in results),
        "total_completion_tokens": sum(r["completion_tokens"] for r in results),
        "parse_errors": sum(
            r["initial"]["parse_error"] or r["final"]["parse_error"] for r in results),
        "prompts_with_any_incomplete_round": sum(
            r["initial"]["incomplete"] or r["final"]["incomplete"] or r["any_round_incomplete"]
            for r in results),
    }


def print_summary(results: list[dict]):
    if not results:
        print("No results.")
        return
    s = summarize(results)
    print(f"\n{'═' * 60}\n  EVAL SUMMARY  ({s['n']} prompts)\n{'═' * 60}")
    print(f"  Pass rate  first try / final : {s['first_try_pass_rate']:.0%} / {s['final_pass_rate']:.0%}")
    print(f"  Avg overall initial / final  : {s['avg_overall_initial']:.2f} / {s['avg_overall_final']:.2f}")
    print(f"  Avg revision rounds          : {s['avg_revision_rounds']:.2f}")
    if s["classification_accuracy"] is not None:
        print(f"  Category accuracy            : {s['classification_accuracy']:.0%}")
    print(f"  Avg latency / API calls      : {s['avg_latency_s']:.1f}s / {s['avg_api_calls']:.1f}")
    print(f"  Judge parse errors           : {s['parse_errors']}")
    print(f"  Prompts w/ incomplete judgment: {s['prompts_with_any_incomplete_round']}")
    print(f"{'═' * 60}\n")


def _save(path: Path, doc: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(path)   # atomic: an interrupted run never leaves a corrupt file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only run the first N prompts")
    ap.add_argument("--prompts", type=Path, default=PROMPTS_FILE)
    ap.add_argument("--resume", type=Path, default=None,
                    help="existing results file: skip prompts already completed in it")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.")
        sys.exit(1)

    prompts = json.loads(args.prompts.read_text())
    if args.limit:
        prompts = prompts[: args.limit]

    now = datetime.now(timezone.utc)
    RESULTS_DIR.mkdir(exist_ok=True)
    this_meta = {
        "model": get_model(),
        "extra_request_params": EXTRA_REQUEST_PARAMS,
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "pass_score_threshold": PASS_SCORE_THRESHOLD,
        "safety_threshold": SAFETY_THRESHOLD,
        "max_revision_rounds": MAX_REVISION_ROUNDS,
    }

    if args.resume:
        out_path = args.resume
        doc = json.loads(out_path.read_text())
        # never mix results from different models/settings in one run
        for k, v in this_meta.items():
            if doc["meta"].get(k) != v:
                print(f"ERROR: cannot resume — '{k}' differs: file has {doc['meta'].get(k)!r}, "
                      f"current is {v!r}")
                sys.exit(1)
        doc["meta"].setdefault("sessions_utc", []).append(now.isoformat())
    else:
        out_path = RESULTS_DIR / f"eval_run_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        doc = {
            "meta": {
                "timestamp_utc": now.isoformat(),
                "sessions_utc": [now.isoformat()],
                **this_meta,
                "rubric_weights": RUBRIC_WEIGHTS,
                "story_age": 7,
                "n_prompts_total": len(prompts),
            },
            "results": [],
            "failures": [],
        }
    results, failed = doc["results"], doc["failures"]
    done = {r["id"] for r in results}
    todo = [e for e in prompts if e["id"] not in done]
    print(f"{len(done)} already done, running {len(todo)} of {len(prompts)} prompts…"
          f"\nresults file: {out_path}")

    stopped_early = None
    meter = UsageMeter()
    meter.install()
    try:
        for entry in todo:
            try:
                results.append(run_single(entry, meter))
                # a success supersedes an earlier failure of this prompt, but the
                # failure stays on record so a crash is never silently retried away
                for f in [f for f in failed if f["id"] == entry["id"]]:
                    doc.setdefault("failure_history", []).append({**f, "later_succeeded": True})
                failed[:] = [f for f in failed if f["id"] != entry["id"]]
            except DailyLimitReached as exc:
                stopped_early = str(exc)
                print(f"  Provider message: {stopped_early[:400]}")
                print(f"\n  DAILY LIMIT REACHED while running {entry['id']} — stopping. "
                      f"That prompt's partial work is discarded and it will re-run on resume.")
                break
            except Exception as exc:
                print(f"  ERROR on {entry['id']}: {type(exc).__name__}: {exc}")
                for f in [f for f in failed if f["id"] == entry["id"]]:
                    doc.setdefault("failure_history", []).append({**f, "later_succeeded": False})
                failed[:] = [f for f in failed if f["id"] != entry["id"]]
                failed.append({"id": entry["id"], "error": f"{type(exc).__name__}: {exc}"})
            _save(out_path, doc)   # checkpoint after every prompt
    finally:
        meter.uninstall()
        _save(out_path, doc)

    print(f"\nRaw results saved to {out_path}")
    print_summary(results)
    remaining = [e["id"] for e in prompts if e["id"] not in {r["id"] for r in results}]
    if failed:
        print(f"  {len(failed)} prompt(s) failed with errors:")
        for f in failed:
            print(f"    {f['id']}: {f['error']}")
    if remaining:
        print(f"  {len(remaining)} prompt(s) not completed: {', '.join(remaining)}")
        print(f"  Resume with: python evals/run_evals.py --resume {out_path}")
    if stopped_early:
        sys.exit(2)


if __name__ == "__main__":
    main()
