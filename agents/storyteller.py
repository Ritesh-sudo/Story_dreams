"""
Storyteller — writes and revises children's story prose.

Prompting strategies in use:
  - Role prompting         : distinct writer persona per category (see CATEGORY_SYSTEM_PROMPTS)
  - Few-shot examples      : animal_tale and bedtime_calm prompts embed full prose samples
  - Constraint stacking    : STORYTELLER_BASE_RULES appended to every prompt (word count,
                             paragraph count, sentence complexity, safety hard-stops)
  - Outline-first chain    : receives a structured outline so the model focuses on voice
                             and imagery rather than inventing structure on the fly
  - Temperature 0.85       : high enough for lexical diversity and fresh imagery;
                             lower temperatures produce repetitive, predictable prose
"""

from utils.openai_client import get_client, get_model
from prompts.storyteller_prompts import (
    CATEGORY_SYSTEM_PROMPTS,
    STORYTELLER_BASE_RULES,
    REVISION_SYSTEM_PROMPT,
    NARRATOR_VOICE_SYSTEM_PROMPT,
    USER_FEEDBACK_SYSTEM_PROMPT,
)
from prompts.age_profiles import age_guidance_block


def _outline_to_text(outline: dict) -> str:
    """Converts an outline dict into readable prose instructions for the storyteller."""
    lines = [
        f"Title           : {outline.get('title', 'Untitled')}",
        f"Main character  : {outline.get('main_character', '')}",
    ]
    if outline.get("supporting_characters"):
        lines.append(f"Supporting chars: {', '.join(outline['supporting_characters'])}")
    lines += [
        f"Setting         : {outline.get('setting', '')}",
        f"Opening         : {outline.get('setup', '')}",
        f"Inciting event  : {outline.get('inciting_incident', '')}",
        f"Challenges      : {'; '.join(outline.get('rising_action', []))}",
        f"Climax          : {outline.get('climax', '')}",
        f"Resolution      : {outline.get('resolution', '')}",
        f"Implicit moral  : {outline.get('moral', '')}  "
        f"[Do NOT state this explicitly in the story]",
    ]
    return "\n".join(lines)


class Storyteller:
    def __init__(self):
        self._client = get_client()

    def write(self, outline: dict, category: str, age: int = 7) -> str:
        """Writes a full story from a structured outline."""
        category_prompt = CATEGORY_SYSTEM_PROMPTS.get(
            category, CATEGORY_SYSTEM_PROMPTS["adventure"]
        )
        system_prompt = category_prompt + age_guidance_block(age) + STORYTELLER_BASE_RULES

        user_msg = (
            "Write a complete bedtime story using this outline:\n\n"
            + _outline_to_text(outline)
            + "\n\nWrite the full story now."
        )

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.85,
            max_tokens=1400,
        )
        return response.choices[0].message.content.strip()

    def revise(self, original_story: str, revision_notes: list[str], age: int = 7) -> str:
        """Rewrites the story to address judge feedback."""
        notes_text = "\n".join(f"- {note}" for note in revision_notes)
        user_msg = (
            f"Original story:\n\n{original_story}\n\n"
            f"Editor's revision notes:\n{notes_text}\n\n"
            "Rewrite the story addressing all notes."
        )

        system_prompt = REVISION_SYSTEM_PROMPT + age_guidance_block(age)

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            # Slightly lower temp for revision: improve, don't reinvent
            temperature=0.7,
            max_tokens=1400,
        )
        return response.choices[0].message.content.strip()

    def add_narrator_cues(self, story: str) -> str:
        """
        Adds [pause] and [whisper] cues for parents reading aloud.
        Creative addition: "Narrator voice" mode.
        """
        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": NARRATOR_VOICE_SYSTEM_PROMPT},
                {"role": "user", "content": story},
            ],
            temperature=0.3,   # deterministic cue placement
            max_tokens=1600,
        )
        return response.choices[0].message.content.strip()

    def apply_user_feedback(self, story: str, feedback: str, age: int = 7) -> str:
        """Revises a story based on free-form parent/user feedback."""
        user_msg = (
            f"Story:\n\n{story}\n\n"
            f"Requested changes: {feedback}\n\n"
            "Please revise the story accordingly."
        )

        system_prompt = USER_FEEDBACK_SYSTEM_PROMPT + age_guidance_block(age)

        response = self._client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.8,
            max_tokens=1400,
        )
        return response.choices[0].message.content.strip()

    async def write_stream_async(self, outline: dict, category: str, age: int = 7):
        """Streams story tokens asynchronously for real-time display."""
        from utils.openai_client import get_async_client, get_model as _get_model
        client = get_async_client()
        category_prompt = CATEGORY_SYSTEM_PROMPTS.get(
            category, CATEGORY_SYSTEM_PROMPTS["adventure"]
        )
        system_prompt = category_prompt + age_guidance_block(age) + STORYTELLER_BASE_RULES
        user_msg = (
            "Write a complete bedtime story using this outline:\n\n"
            + _outline_to_text(outline)
            + "\n\nWrite the full story now."
        )
        stream = await client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.85,
            max_tokens=1400,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content
