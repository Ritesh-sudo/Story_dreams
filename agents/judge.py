"""
JudgeAgent — evaluates story quality on a 6-dimension rubric.

Why a separate judge instead of self-critique:
  When the same model is asked to evaluate its own output in the same conversation,
  it is systematically biased toward finding merit in its own choices. A judge with
  a distinct system prompt, a separate "editor" persona, and explicit calibration
  guidance acts as a genuinely independent verifier — the same reason human authors
  have editors rather than proofreading only their own work.

Prompting strategy : chain-of-thought (reason before scoring) + structured output
Temperature        : 0.2  (scores must be consistent and reproducible across runs)
"""

import json
from utils.openai_client import get_client, get_model
from prompts.judge_prompts import JUDGE_SYSTEM_PROMPT
from prompts.age_profiles import judge_age_context

# Rubric weights sum to 1.0.
# Safety and age_appropriateness lead because an unsafe or age-inappropriate
# story fails its core purpose regardless of literary quality.
RUBRIC_WEIGHTS: dict[str, float] = {
    "safety":               0.25,
    "age_appropriateness":  0.20,
    "narrative_arc_quality":0.15,
    "engagement":           0.15,
    "language_level":       0.15,
    "originality":          0.10,
}

PASS_SCORE_THRESHOLD = 7.5   # overall weighted score must meet this
SAFETY_THRESHOLD     = 9.0   # safety must meet this regardless of overall score


class JudgeAgent:
    def __init__(self):
        self._client = get_client()

    def evaluate(self, story: str, original_request: str = "", age: int = 7) -> dict:
        """
        Evaluates the story and returns a judgment dict.

        Return schema:
        {
          "reasoning": str,
          "scores": {
            "<dimension>": {"score": int, "justification": str},
            ...
          },
          "overall_score": float,       # computed by _weighted_score()
          "pass_threshold": bool,       # overall >= 7.5 AND safety >= 9
          "specific_revision_notes": [str, ...],
        }
        """
        context = f"Original request: {original_request}\n\n" if original_request else ""
        age_ctx = judge_age_context(age) + "\n\n"
        user_msg = f"{age_ctx}{context}Story to evaluate:\n\n{story}"

        extra = {"response_format": {"type": "json_object"}}

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=1000,
            **extra,
        )

        try:
            result = json.loads(response.choices[0].message.content)
            result["overall_score"] = self._weighted_score(result.get("scores", {}))
            safety_score = result.get("scores", {}).get("safety", {}).get("score", 0)
            result["pass_threshold"] = (
                result["overall_score"] >= PASS_SCORE_THRESHOLD
                and safety_score >= SAFETY_THRESHOLD
            )
            return result
        except (json.JSONDecodeError, KeyError) as exc:
            return self._fallback(str(exc))

    def _weighted_score(self, scores: dict) -> float:
        total = weight_sum = 0.0
        for dim, w in RUBRIC_WEIGHTS.items():
            raw = scores.get(dim, {}).get("score")
            if raw is not None:
                total += raw * w
                weight_sum += w
        if weight_sum == 0:
            return 0.0
        return round(total / weight_sum, 2)

    def _fallback(self, error_msg: str) -> dict:
        return {
            "reasoning": f"Parse error — could not evaluate story: {error_msg}",
            "scores": {
                dim: {"score": 5, "justification": "Score defaulted due to parse error."}
                for dim in RUBRIC_WEIGHTS
            },
            "overall_score": 5.0,
            "pass_threshold": False,
            "specific_revision_notes": [
                "Re-run evaluation — judge response could not be parsed."
            ],
        }
