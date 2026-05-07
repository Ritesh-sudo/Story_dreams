# Age-specific vocabulary and complexity profiles.
#
# Children's language development falls into three clear bands within the 5-10 range.
# These profiles are injected directly into the storyteller and judge system prompts
# so the model has concrete, actionable guidance — not just a vague age number.
#
# Band boundaries are deliberately inclusive: a 7-year-old who reads a lot is closer
# to the 7-8 band top; a struggling 8-year-old is closer to the bottom. The bands
# give a sensible default without trying to be a reading-level diagnostic tool.

from typing import TypedDict


class AgeProfile(TypedDict):
    band_label: str
    sentence_length: str
    vocabulary: str
    paragraph_count: str
    word_count: str
    repetition: str
    emotional_complexity: str
    example_words: str
    avoid_words: str


# Three developmental bands within ages 5-10
_PROFILES: dict[tuple[int, int], AgeProfile] = {
    (5, 6): AgeProfile(
        band_label="early listeners (ages 5-6)",
        sentence_length=(
            "Very short — 6 to 10 words each. Rarely go beyond 12 words. "
            "Short sentences feel natural when read aloud to young children."
        ),
        vocabulary=(
            "Kindergarten to 1st-grade level only. Use everyday, concrete words. "
            "Avoid any word a child this age would need defined. "
            "If you must use a slightly new word, immediately show its meaning through action."
        ),
        paragraph_count="4 to 6 short paragraphs",
        word_count="300 to 450 words total",
        repetition=(
            "REQUIRED: include at least 2-3 repeating phrases or a simple refrain "
            "(e.g. 'And so Pip tried again.' repeated after each attempt). "
            "Young children love and expect patterns — repetition IS the craft here."
        ),
        emotional_complexity=(
            "Simple, named feelings only: happy, sad, scared, proud, excited, tired. "
            "One emotion at a time. Avoid mixed or complex feelings."
        ),
        example_words=(
            "big, tiny, soft, bright, fast, slow, dark, warm, run, jump, "
            "laugh, sleep, friend, brave, kind, wonder, magic, cozy"
        ),
        avoid_words=(
            "mysterious, extraordinary, peculiar, reluctant, discover, "
            "hesitate, shimmer, ancient, vast — any word beyond 1st-grade level"
        ),
    ),

    (7, 8): AgeProfile(
        band_label="emerging readers (ages 7-8)",
        sentence_length=(
            "Mostly 10 to 16 words. Mix short punchy sentences with occasional "
            "longer ones for rhythm. Avoid sentences over 20 words."
        ),
        vocabulary=(
            "2nd to 3rd-grade level. One or two slightly challenging words per page "
            "are fine if the meaning is clear from context. "
            "Descriptive adjectives and vivid verbs are encouraged."
        ),
        paragraph_count="6 to 8 paragraphs",
        word_count="450 to 650 words total",
        repetition=(
            "Optional but welcome. A recurring phrase or image adds charm. "
            "Not required for every story."
        ),
        emotional_complexity=(
            "Can handle mixed feelings: nervous but excited, proud but a little sad. "
            "Interior thoughts ('She wondered if...') are appropriate."
        ),
        example_words=(
            "curious, discover, determined, enormous, gentle, whispering, "
            "sparkle, wonder, carefully, suddenly, at last, perhaps, brave"
        ),
        avoid_words=(
            "philosophical, melancholy, ambiguous, intricate, phenomenon — "
            "anything above a confident 3rd-grade reader's vocabulary"
        ),
    ),

    (9, 10): AgeProfile(
        band_label="confident readers (ages 9-10)",
        sentence_length=(
            "12 to 22 words average. Complex sentence structures are fine. "
            "Use subordinate clauses, varied rhythm, and longer descriptive passages."
        ),
        vocabulary=(
            "4th to 5th-grade level. Richer, more precise language is welcome. "
            "Introduce 2-3 memorable or slightly challenging words with clear context. "
            "Metaphors, similes, and figurative language are strongly encouraged."
        ),
        paragraph_count="7 to 10 paragraphs",
        word_count="650 to 850 words total",
        repetition="Optional — use only for deliberate stylistic effect.",
        emotional_complexity=(
            "Nuanced inner life: doubt, quiet bravery, bittersweet resolution. "
            "A character can hold two conflicting feelings simultaneously. "
            "A small but real character arc within the story is appropriate."
        ),
        example_words=(
            "hesitated, extraordinary, peculiar, shimmered, reluctantly, infinite, "
            "glimmered, mysterious, ancient, beneath, horizon, trembling, soared"
        ),
        avoid_words=(
            "Adult literary vocabulary, irony, sarcasm, or themes that require "
            "life experience beyond age 10 to understand."
        ),
    ),
}


def get_age_profile(age: int) -> AgeProfile:
    """Returns the vocabulary/complexity profile for a given age (5-10)."""
    age = max(5, min(10, age))   # clamp to valid range
    for (low, high), profile in _PROFILES.items():
        if low <= age <= high:
            return profile
    return _PROFILES[(7, 8)]     # safe default


def age_guidance_block(age: int) -> str:
    """
    Returns a formatted system-prompt block with age-specific writing requirements.
    Injected into the Storyteller and Planner system prompts.
    """
    p = get_age_profile(age)
    return f"""
━━ AGE-SPECIFIC REQUIREMENTS ({p['band_label']}) ━━
Sentence length    : {p['sentence_length']}
Vocabulary level   : {p['vocabulary']}
Paragraphs         : {p['paragraph_count']}
Word count target  : {p['word_count']}
Repetition/patterns: {p['repetition']}
Emotional depth    : {p['emotional_complexity']}
Good word examples : {p['example_words']}
Avoid              : {p['avoid_words']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def judge_age_context(age: int) -> str:
    """
    Returns a calibration note for the JudgeAgent so it scores language_level
    relative to the actual target age, not a generic 5-10 range.
    """
    p = get_age_profile(age)
    return (
        f"Target reader age: {age} years old ({p['band_label']}).\n"
        f"For language_level scoring: calibrate against {p['band_label']} standards. "
        f"Expected sentence length: {p['sentence_length'].split('.')[0]}. "
        f"Expected vocabulary: {p['vocabulary'].split('.')[0]}.\n"
        f"A score of 8 means the language is well-matched to a {age}-year-old, "
        f"not to the full 5-10 range."
    )
