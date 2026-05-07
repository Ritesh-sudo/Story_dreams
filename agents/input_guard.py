"""
InputGuard — pre-generation content safety check.

Why here instead of relying solely on the judge:
  The judge catches problems AFTER generation (3-5 API calls already spent).
  The guard catches them BEFORE generation (1 fast call), saving cost and
  preventing the frustrating experience of watching a story generate only
  to be rejected. The judge is still the *quality* gate; the guard is the
  *safety* gate at the door.

Prompting strategy : role prompting + structured output + constraint stacking
Temperature        : 0.1  (safety decisions must be maximally consistent)
"""

import re
import json
from utils.openai_client import get_client, get_model
from prompts.guard_prompts import GUARD_SYSTEM_PROMPT

VERDICTS = {"safe", "reframe", "block"}

# Terms that must be present (as whole words / word-start matches) for a
# "block" verdict to be respected. Uses word-boundary regex so that innocent
# words like "skilled" (contains "kill") or "drugstore" don't trigger a match.
_HARD_BLOCK_TERMS = [
    "sex", "sexual", "nude", "naked", "porn", "erotic",
    "murder", "gore", "torture",
    "cocaine", "heroin", "meth",
    "suicide", "self-harm", "self harm",
    "rape", "molest",
    "terrorist", "terrorism",
]

# Compiled pattern: \b at the start of each term catches "kills/killing" but
# NOT "skilled". Longer terms are listed first to avoid partial shadowing.
_HARD_BLOCK_RE = re.compile(
    r'\b(?:' +
    '|'.join(re.escape(t) for t in sorted(_HARD_BLOCK_TERMS, key=len, reverse=True)) +
    r')',
    re.IGNORECASE,
)


class InputGuard:
    def __init__(self):
        self._client = get_client()

    @staticmethod
    def _contains_hard_block_term(text: str) -> bool:
        return bool(_HARD_BLOCK_RE.search(text))

    def check(self, user_request: str, age: int = 7) -> dict:
        """
        Evaluates a story request for child-appropriateness.

        Returns:
        {
          "verdict"      : "safe" | "reframe" | "block",
          "reason"       : str,
          "safe_prompt"  : str | None,   # reframed request if verdict=reframe
          "child_message": str | None,   # friendly refusal text if verdict=block
        }
        """
        extra = {"response_format": {"type": "json_object"}}

        user_msg = (
            f"Story request for a {age}-year-old child: {user_request}\n\n"
            "Is this an appropriate bedtime story request?"
        )

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": GUARD_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,   # safety must be maximally consistent
            max_tokens=300,
            **extra,
        )

        raw = response.choices[0].message.content.strip()
        print(f"[InputGuard raw]: {raw[:300]}", flush=True)

        try:
            # Strip markdown code fences some models wrap JSON in
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            if result.get("verdict") not in VERDICTS:
                print(f"[InputGuard] unknown verdict {result.get('verdict')!r} — safe", flush=True)
                result["verdict"] = "safe"
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            print(f"[InputGuard] parse error ({exc}) — safe", flush=True)
            result = {
                "verdict": "safe",
                "reason": "Guard parse error — defaulting to safe.",
                "safe_prompt": None,
                "child_message": None,
            }

        # Override a false-positive block: if the request contains none of the
        # genuinely problematic terms, the model is being overly conservative.
        if result["verdict"] == "block" and not self._contains_hard_block_term(user_request):
            print(f"[InputGuard] false-positive block overridden → safe", flush=True)
            result["verdict"] = "safe"
            result["reason"] = "Request appears appropriate — override applied."

        print(f"[InputGuard] final verdict={result['verdict']}  reason={result.get('reason','')}", flush=True)
        return result
