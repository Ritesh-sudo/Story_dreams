#!/usr/bin/env python3
"""
write_report.py — builds evals/RESULTS.md and the README "Eval Results" section
from the raw JSON files. Every number is computed here from the saved data.

Usage:
    python evals/write_report.py evals/results/eval_run_<ts>.json \
                                 evals/results/judge_consistency_<ts>.json
"""

import json
import math
import re
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIMS = ["safety", "age_appropriateness", "narrative_arc_quality",
        "engagement", "language_level", "originality"]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs)


def pct(k, n):
    return f"{k}/{n} ({k / n:.0%})"


def main():
    run = json.loads(Path(sys.argv[1]).read_text())
    cons = json.loads(Path(sys.argv[2]).read_text())
    meta, R = run["meta"], run["results"]
    n = len(R)
    hist = run.get("failure_history", [])

    first_pass = sum(r["initial"]["passed"] for r in R)
    final_pass = sum(r["final"]["passed"] for r in R)
    o_i = mean(r["initial"]["overall_score"] for r in R)
    o_f = mean(r["final"]["overall_score"] for r in R)
    diffs = [r["final"]["overall_score"] - r["initial"]["overall_score"] for r in R]
    revised = [r for r in R if r["revision_rounds"] > 0]
    last_round = [r["judge_trace_overall"][-1] for r in R]
    dim_i = {d: mean(r["initial"]["dim_scores"][d] for r in R) for d in DIMS}
    dim_f = {d: mean(r["final"]["dim_scores"][d] for r in R) for d in DIMS}
    cat_ok = sum(r["category_correct"] for r in R)
    misses = [r for r in R if not r["category_correct"]]
    rounds = defaultdict(int)
    for r in R:
        rounds[r["revision_rounds"]] += 1
    lat = mean(r["latency_s"] for r in R)
    calls = mean(r["api_calls"] for r in R)
    tok_in = sum(r["prompt_tokens"] for r in R)
    tok_out = sum(r["completion_tokens"] for r in R)
    words = mean(len(r["final_story"].split()) for r in R)
    by_cat = defaultdict(list)
    for r in R:
        by_cat[r["expected_category"]].append(r)

    C = cons["stories"]
    pooled_sd = math.sqrt(mean([s["stdev"] ** 2 for s in C]))
    n_within = sum(s["range"] <= cons["meta"]["claim_max_range"] for s in C)
    max_rng = max(s["range"] for s in C)
    flips = [s for s in C if 0 < s["pass_count"] < s["n"]]
    cons_errs = sum(len(s["errors"]) for s in C)
    cons_calls = sum(s["attempts"] for s in C)

    started = datetime.fromisoformat(meta["sessions_utc"][0]).strftime("%Y-%m-%d")
    resumed = datetime.fromisoformat(meta["sessions_utc"][-1]).strftime("%Y-%m-%d")
    model_line = f"`{meta['model']}` via Groq's OpenAI-compatible API"
    if meta.get("extra_request_params"):
        model_line += f" with `{json.dumps(meta['extra_request_params'])}`"

    L = []
    w = L.append
    w("# Eval Results (measured)\n")
    w(f"All numbers below are computed from the raw files in `evals/results/` "
      f"(`{Path(sys.argv[1]).name}`, `{Path(sys.argv[2]).name}`). Nothing is estimated or rounded up.\n")
    w("## Setup\n")
    w(f"- **Date:** {started}" + (f" (prompts eval_07, eval_19, eval_22, eval_26, eval_30 finished {resumed} "
                                  "after the provider's daily quota ran out)" if resumed != started else ""))
    w(f"- **Model (all agents: classifier, planner, storyteller, judge):** {model_line}")
    w("- **This is not `gpt-3.5-turbo`.** The project's default model is gpt-3.5-turbo; these numbers were "
      "measured on a different model and should not be quoted as gpt-3.5-turbo results.")
    w(f"- **Prompts:** {n} (5 per category × 6 categories), each run through the full pipeline once, age 7.")
    w(f"- **Pass rule:** overall ≥ {meta['pass_score_threshold']} and safety ≥ {meta['safety_threshold']}; "
      f"max {meta['max_revision_rounds']} revision rounds.")
    w("- **Baseline method:** the round-0 judgment of the initial draft is the \"no revision\" baseline; "
      "no separate run was needed.\n")

    w("## Results\n")
    w("| Metric | Initial draft (round 0) | Final (after loop) |")
    w("|---|---|---|")
    w(f"| Pass rate | {pct(first_pass, n)} | {pct(final_pass, n)} |")
    w(f"| Average overall score | {o_i:.2f} | {o_f:.2f} |")
    w(f"| Average safety score | {dim_i['safety']:.2f} | {dim_f['safety']:.2f} |")
    w("")
    w("**Average score per dimension**\n")
    w("| Dimension | Initial | Final |")
    w("|---|---|---|")
    for d in DIMS:
        w(f"| {d} | {dim_i[d]:.2f} | {dim_f[d]:.2f} |")
    w("")
    w("| Other metric | Value |")
    w("|---|---|")
    w(f"| Classification accuracy | {pct(cat_ok, n)} |")
    w(f"| Average revision rounds | {mean(r['revision_rounds'] for r in R):.2f} "
      f"(0 rounds: {rounds[0]}, 1 round: {rounds[1]}, 2 rounds: {rounds[2]}) |")
    w(f"| Stories that fell back to best-of (never passed) | {sum(r['used_fallback'] for r in R)} |")
    w(f"| Average latency per story | {lat:.1f}s (see caveat below) |")
    w(f"| Average API calls per story | {calls:.1f} |")
    w(f"| Total tokens | {tok_in + tok_out:,} ({tok_in:,} prompt + {tok_out:,} completion) |")
    w(f"| Average final story length | {words:.0f} words (prompt asks for 600-800) |")
    w("")
    if misses:
        w("Misclassified: " + "; ".join(
            f"{r['id']} (labeled `{r['expected_category']}`, got `{r['detected_category']}`)" for r in misses) + ".\n")

    w("### How much did the revision loop help?\n")
    w(f"- Stories that needed revision: {len(revised)} of {n}. "
      f"Mean overall gain over all {n} stories: {mean(diffs):+.2f}.")
    if revised:
        w(f"- Among the {len(revised)} revised stories: " + ", ".join(
            f"{r['id']} {r['initial']['overall_score']:.2f}→{r['final']['overall_score']:.2f}"
            for r in revised) + ".")
    gmin, gmax = min(r["final"]["overall_score"] - r["initial"]["overall_score"] for r in revised), \
        max(r["final"]["overall_score"] - r["initial"]["overall_score"] for r in revised)
    fallbacks = sum(r["used_fallback"] for r in R)
    w(f"- Gains on the revised stories range from {gmin:+.2f} to {gmax:+.2f}. For scale, the judge's own std dev on "
      f"unchanged text is about {pooled_sd:.2f} (see consistency check).")
    w(f"- The loop stops at the first passing judgment. With a noisy judge, that alone raises the pass rate: a "
      f"story that scores just under {meta['pass_score_threshold']} gets another draw. All {len(revised)} revised "
      f"stories started between {min(r['initial']['overall_score'] for r in revised):.2f} and "
      f"{max(r['initial']['overall_score'] for r in revised):.2f}, i.e. just under the threshold, and all "
      f"{len(revised)} passed after one revision. This run cannot tell how much of that is the revision and how "
      "much is re-judging.")
    w(f"- Stories that fell back to best-of-3 in this run: {fallbacks}, so the final score equals the last judged "
      f"round (mean {mean(last_round):.2f}).\n")

    w("### By category (final scores)\n")
    w("| Category | n | Avg initial | Avg final | Final pass |")
    w("|---|---|---|---|---|")
    for c in sorted(by_cat):
        rs = by_cat[c]
        w(f"| {c} | {len(rs)} | {mean(r['initial']['overall_score'] for r in rs):.2f} | "
          f"{mean(r['final']['overall_score'] for r in rs):.2f} | "
          f"{sum(r['final']['passed'] for r in rs)}/{len(rs)} |")
    w("")

    w("## Judge consistency check\n")
    w(f"README claim: scores vary by ≤ {cons['meta']['claim_max_range']} points across identical inputs. "
      f"Test: {len(C)} stories (seed {cons['meta']['seed']}, sampled from this run's final stories), "
      f"each judged {cons['meta']['n_repeats']} times.\n")
    w("| Story | Overall scores (5 runs) | Std dev | Max−min | Pass/fail across runs |")
    w("|---|---|---|---|---|")
    for s in C:
        w(f"| {s['id']} | {', '.join(f'{x['overall']:.2f}' for x in s['samples'])} | "
          f"{s['stdev']:.2f} | {s['range']:.2f} | {s['pass_count']} pass / {s['n'] - s['pass_count']} fail |")
    w("")
    w(f"**The claim does not hold.** Only {n_within} of {len(C)} stories had a range within 0.5; the largest range "
      f"was {max_rng:.2f}. Pooled std dev ≈ {pooled_sd:.2f}. {len(flips)} of {len(C)} stories flipped between "
      f"pass and fail across identical judgments, so a single judgment near the {meta['pass_score_threshold']} "
      "threshold is close to a coin flip.\n")
    w(f"The mean gain from revision ({mean(diffs):+.2f}) is much smaller than one judge standard deviation "
      f"({pooled_sd:.2f}). Individual revised-story gains ({gmin:+.2f} to {gmax:+.2f}) are within about "
      f"{gmax / pooled_sd:.1f} standard deviations, and the judge's max-min range on unchanged text reached "
      f"{max_rng:.2f}. This measurement cannot separate a real improvement from re-rolling the judge.\n")

    w("## Reliability issues found\n")
    w(f"- **Judge crash:** `JudgeAgent._weighted_score` raises `TypeError: can't multiply sequence by non-int of "
      f"type 'float'` when the model returns a score as a string. It is not caught by the judge's error handling, "
      f"so it would fail a user request. During the main run it crashed on {len(hist)} of {n + len(hist)} prompt "
      f"attempts ({', '.join(h['id'] for h in hist)}); all succeeded when retried, and only the successful retries "
      f"are in the averages. In the consistency check {cons_errs} of {cons_calls} judge calls crashed the same way. "
      "The pipeline code was not modified.")
    w("- **Story length:** average final story length is below the prompt's 600-800 word target.\n")

    w("## Limitations\n")
    w("- **Same judge drives and measures.** The judge decides which stories get revised and also scores the "
      "improvement, so the gain is judge-measured, not human-validated. There is no human or independent-model check.")
    w(f"- **Sample size:** {n} prompts, {len(revised)} of which were revised. Per-category cells have 5 prompts. "
      "Percentages move by 3.3 points per prompt; differences of a few points are not meaningful.")
    w(f"- **Judge noise:** pooled std dev ≈ {pooled_sd:.2f} on a threshold-based pass rule (see above). The "
      f"consistency check used only {len(C)} stories × 5 runs.")
    w("- **Stop-at-first-pass** in the loop inflates the pass rate when the judge is noisy (see above).")
    w("- **Model:** results are for the model named above, run with reduced reasoning effort so its hidden "
      "reasoning fit the pipeline's token limits. They do not transfer to gpt-3.5-turbo.")
    w("- **Test set:** prompts and their category labels were written by the project author (and an AI assistant "
      "for eval_11-eval_30) before any run and were not changed afterward. They may be cleaner than real user "
      "input, and some labels are arguable (e.g. eval_01). Story age was fixed at 7.")
    w("- **Latency:** measured on a hosted free-tier API with rate limits. Waits the harness could see were excluded; "
      "backoff inside the OpenAI SDK's own retries is not visible and is included. Treat it as an upper bound, "
      "not as the pipeline's inherent speed. It excludes the input guard and narrator-cue steps the real app also runs.")
    w("- **API calls/tokens** count calls made by the pipeline; SDK-internal retries are not counted.")
    w("- The judge and the storyteller are the same model, so shared blind spots are possible.\n")

    (ROOT / "evals" / "RESULTS.md").write_text("\n".join(L))

    # ── README section ────────────────────────────────────────────────────────
    readme = (ROOT / "README.md").read_text()
    section = f"""## Eval Results

Measured on {n} test prompts (5 per category), one full-pipeline run each, on
{model_line} (**not** the default gpt-3.5-turbo). Run date: {started}.
Details, caveats and raw-data pointers are in [`evals/RESULTS.md`](evals/RESULTS.md).
Reproduce with `python evals/run_evals.py`.

| Metric | Initial draft | After judge + revision loop |
|---|---|---|
| Pass rate | {pct(first_pass, n)} | {pct(final_pass, n)} |
| Avg overall score | {o_i:.2f} | {o_f:.2f} |
| Avg safety score | {dim_i['safety']:.2f} | {dim_f['safety']:.2f} |

| Other metric | Value |
|---|---|
| Category classification accuracy | {pct(cat_ok, n)} |
| Avg revision rounds | {mean(r['revision_rounds'] for r in R):.2f} |
| Avg latency per story | {lat:.1f}s (upper bound; hosted free tier) |
| Judge score spread on identical input | std dev ≈ {pooled_sd:.2f}, max−min up to {max_rng:.2f} (5 stories × 5 runs) |

**Caveats:** the same judge drives revisions and measures the improvement, so the
gain is judge-measured, not human-validated. The judge's own noise (max−min up to
{max_rng:.2f}) is larger than the average gain ({mean(diffs):+.2f}), and the earlier
"≤ 0.5 points" consistency claim did not hold (corrected in *Why temperature 0.85 … 0.2 for the Judge*). Sample size is small ({n} prompts).

---
"""
    new = re.sub(r"## Eval Results\n.*?(?=\n## Project Structure)", section, readme, flags=re.S)
    assert new != readme, "README section not replaced"
    (ROOT / "README.md").write_text(new)

    print(f"n={n}  pass {first_pass}->{final_pass}  overall {o_i:.3f}->{o_f:.3f}  gain {mean(diffs):+.3f}  "
          f"last-round mean {mean(last_round):.3f}")
    print(f"cat acc {cat_ok}/{n}  rounds {dict(rounds)}  lat {lat:.1f}s  calls {calls:.2f}  tokens {tok_in + tok_out:,}")
    print(f"consistency: pooled sd {pooled_sd:.3f} max range {max_rng:.2f} within-claim {n_within}/{len(C)} flips {len(flips)}")
    print("dims initial:", {d: round(v, 2) for d, v in dim_i.items()})
    print("dims final:  ", {d: round(v, 2) for d, v in dim_f.items()})


if __name__ == "__main__":
    main()
