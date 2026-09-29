# Eval Results (measured)

All numbers below are computed from the raw files in `evals/results/` (`eval_run_20260928T201149Z.json`, `judge_consistency_20260929T155614Z.json`). Nothing is estimated or rounded up.

## Setup

- **Date:** 2026-09-28 (prompts eval_07, eval_19, eval_22, eval_26, eval_30 finished 2026-09-29 after the provider's daily quota ran out)
- **Model (all agents: classifier, planner, storyteller, judge):** `openai/gpt-oss-120b` via Groq's OpenAI-compatible API with `{"reasoning_effort": "low"}`
- **This is not `gpt-3.5-turbo`.** The project's default model is gpt-3.5-turbo; these numbers were measured on a different model and should not be quoted as gpt-3.5-turbo results.
- **Prompts:** 30 (5 per category × 6 categories), each run through the full pipeline once, age 7.
- **Pass rule:** overall ≥ 7.5 and safety ≥ 9.0; max 2 revision rounds.
- **Baseline method:** the round-0 judgment of the initial draft is the "no revision" baseline; no separate run was needed.

## Results

| Metric | Initial draft (round 0) | Final (after loop) |
|---|---|---|
| Pass rate | 24/30 (80%) | 30/30 (100%) |
| Average overall score | 7.69 | 7.74 |
| Average safety score | 9.50 | 9.50 |

**Average score per dimension**

| Dimension | Initial | Final |
|---|---|---|
| safety | 9.50 | 9.50 |
| age_appropriateness | 7.80 | 7.97 |
| narrative_arc_quality | 7.80 | 7.83 |
| engagement | 7.07 | 7.03 |
| language_level | 5.67 | 5.77 |
| originality | 6.77 | 6.80 |

| Other metric | Value |
|---|---|
| Classification accuracy | 29/30 (97%) |
| Average revision rounds | 0.20 (0 rounds: 24, 1 round: 6, 2 rounds: 0) |
| Stories that fell back to best-of (never passed) | 0 |
| Average latency per story | 40.0s (see caveat below) |
| Average API calls per story | 4.4 |
| Total tokens | 188,909 (131,508 prompt + 57,401 completion) |
| Average final story length | 545 words (prompt asks for 600-800) |

Misclassified: eval_01 (labeled `adventure`, got `bedtime_calm`).

### How much did the revision loop help?

- Stories that needed revision: 6 of 30. Mean overall gain over all 30 stories: +0.05.
- Among the 6 revised stories: eval_05 7.45→7.55, eval_10 7.30→7.55, eval_12 7.45→7.60, eval_16 7.40→7.85, eval_22 7.45→7.60, eval_26 7.25→7.70.
- Gains on the revised stories range from +0.10 to +0.45. For scale, the judge's own std dev on unchanged text is about 0.28 (see consistency check).
- The loop stops at the first passing judgment. With a noisy judge, that alone raises the pass rate: a story that scores just under 7.5 gets another draw. All 6 revised stories started between 7.25 and 7.45, i.e. just under the threshold, and all 6 passed after one revision. This run cannot tell how much of that is the revision and how much is re-judging.
- Stories that fell back to best-of-3 in this run: 0, so the final score equals the last judged round (mean 7.74).

### By category (final scores)

| Category | n | Avg initial | Avg final | Final pass |
|---|---|---|---|---|
| adventure | 5 | 7.66 | 7.69 | 5/5 |
| animal_tale | 5 | 7.80 | 7.83 | 5/5 |
| bedtime_calm | 5 | 7.67 | 7.74 | 5/5 |
| educational | 5 | 7.69 | 7.78 | 5/5 |
| fantasy | 5 | 7.64 | 7.73 | 5/5 |
| friendship | 5 | 7.69 | 7.69 | 5/5 |

## Judge consistency check

README claim: scores vary by ≤ 0.5 points across identical inputs. Test: 5 stories (seed 0, sampled from this run's final stories), each judged 5 times.

| Story | Overall scores (5 runs) | Std dev | Max−min | Pass/fail across runs |
|---|---|---|---|---|
| eval_13 | 7.95, 7.60, 7.45, 7.95, 7.25 | 0.31 | 0.70 | 3 pass / 2 fail |
| eval_14 | 7.70, 7.45, 7.85, 7.85, 8.25 | 0.29 | 0.80 | 4 pass / 1 fail |
| eval_25 | 8.25, 7.65, 7.35, 7.35, 7.45 | 0.38 | 0.90 | 2 pass / 3 fail |
| eval_28 | 7.95, 7.80, 7.80, 7.80, 7.75 | 0.08 | 0.20 | 5 pass / 0 fail |
| eval_29 | 7.55, 7.80, 7.25, 7.45, 7.80 | 0.24 | 0.55 | 3 pass / 2 fail |

**The claim does not hold.** Only 1 of 5 stories had a range within 0.5; the largest range was 0.90. Pooled std dev ≈ 0.28. 4 of 5 stories flipped between pass and fail across identical judgments, so a single judgment near the 7.5 threshold is close to a coin flip.

The mean gain from revision (+0.05) is much smaller than one judge standard deviation (0.28). Individual revised-story gains (+0.10 to +0.45) are within about 1.6 standard deviations, and the judge's max-min range on unchanged text reached 0.90. This measurement cannot separate a real improvement from re-rolling the judge.

## Reliability issues found

- **Judge crash:** `JudgeAgent._weighted_score` raises `TypeError: can't multiply sequence by non-int of type 'float'` when the model returns a score as a string. It is not caught by the judge's error handling, so it would fail a user request. During the main run it crashed on 4 of 34 prompt attempts (eval_07, eval_19, eval_22, eval_26); all succeeded when retried, and only the successful retries are in the averages. In the consistency check 5 of 30 judge calls crashed the same way. The pipeline code was not modified.
- **Story length:** average final story length is below the prompt's 600-800 word target.

## Limitations

- **Same judge drives and measures.** The judge decides which stories get revised and also scores the improvement, so the gain is judge-measured, not human-validated. There is no human or independent-model check.
- **Sample size:** 30 prompts, 6 of which were revised. Per-category cells have 5 prompts. Percentages move by 3.3 points per prompt; differences of a few points are not meaningful.
- **Judge noise:** pooled std dev ≈ 0.28 on a threshold-based pass rule (see above). The consistency check used only 5 stories × 5 runs.
- **Stop-at-first-pass** in the loop inflates the pass rate when the judge is noisy (see above).
- **Model:** results are for the model named above, run with reduced reasoning effort so its hidden reasoning fit the pipeline's token limits. They do not transfer to gpt-3.5-turbo.
- **Test set:** prompts and their category labels were written by the project author (and an AI assistant for eval_11-eval_30) before any run and were not changed afterward. They may be cleaner than real user input, and some labels are arguable (e.g. eval_01). Story age was fixed at 7.
- **Latency:** measured on a hosted free-tier API with rate limits. Waits the harness could see were excluded; backoff inside the OpenAI SDK's own retries is not visible and is included. Treat it as an upper bound, not as the pipeline's inherent speed. It excludes the input guard and narrator-cue steps the real app also runs.
- **API calls/tokens** count calls made by the pipeline; SDK-internal retries are not counted.
- The judge and the storyteller are the same model, so shared blind spots are possible.
