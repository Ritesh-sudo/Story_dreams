"""
StoryPlanner — generates a structured Freytag-arc outline before any prose is written.

Why plan first: separating structure from prose is a two-step chain that prevents
the storyteller from "meandering." The planner ensures the story has a real arc;
the storyteller can focus entirely on voice, rhythm, and imagery.

Prompting strategy : structured output (JSON mode) + constraint stacking
Temperature        : 0.5  (creative but reliably structured)
"""

import json
from utils.openai_client import get_client, get_model
from prompts.planner_prompts import PLANNER_SYSTEM_PROMPT
from prompts.age_profiles import age_guidance_block


class StoryPlanner:
    def __init__(self):
        self._client = get_client()

    def plan(self, user_request: str, category: str, age: int = 7, child_name: str = "") -> dict:
        """Returns a story outline dict matching the PLANNER_SYSTEM_PROMPT schema."""
        name_line = f"\nPersonalize the story for a child named {child_name}." if child_name.strip() else ""
        user_msg = (
            f"Story request: {user_request}\n"
            f"Category: {category}\n"
            + name_line
            + "\n\n"
            + age_guidance_block(age)
            + "\n\nCreate a story outline that fits the age requirements above."
        )

        extra = {"response_format": {"type": "json_object"}}

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=800,
            **extra,
        )

        try:
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            # Minimal valid outline so the pipeline can continue
            return {
                "title": "A Wonderful Story",
                "main_character": "A curious child",
                "supporting_characters": [],
                "setting": "A magical place",
                "setup": user_request,
                "inciting_incident": "Something wonderful and unexpected happens",
                "rising_action": ["A small challenge appears", "Another challenge follows"],
                "climax": "The main character finds a brave, kind solution",
                "resolution": "Everything works out warmly and everyone is happy",
                "moral": "Kindness and courage make the world better",
            }
