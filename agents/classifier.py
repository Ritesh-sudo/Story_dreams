"""
RequestClassifier — categorizes a story request into one of 6 genres.

Prompting strategy : role prompting + JSON structured output
Temperature        : 0.2  (classification must be deterministic and consistent)
"""

import json
from utils.openai_client import get_client, get_model
from prompts.classifier_prompts import CLASSIFIER_SYSTEM_PROMPT

VALID_CATEGORIES = frozenset(
    {"adventure", "friendship", "animal_tale", "fantasy", "bedtime_calm", "educational"}
)


class RequestClassifier:
    def __init__(self):
        self._client = get_client()

    def classify(self, user_request: str) -> dict:
        """
        Returns {"category": str, "reasoning": str}.
        Falls back to "adventure" on any parse error — most universally engaging
        category for ages 5-10.
        """
        extra = {"response_format": {"type": "json_object"}}

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Story request: {user_request}"},
            ],
            temperature=0.2,
            max_tokens=200,
            **extra,
        )

        try:
            result = json.loads(response.choices[0].message.content)
            if result.get("category") not in VALID_CATEGORIES:
                result["category"] = "adventure"
            return result
        except (json.JSONDecodeError, KeyError):
            return {
                "category": "adventure",
                "reasoning": "Fallback — classification response could not be parsed.",
            }
