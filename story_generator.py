#!/usr/bin/env python3
"""
Bedtime Story Generator — CLI entry point.

Run with:
    python story_generator.py

Full pipeline:
    RequestClassifier  →  StoryPlanner  →  Storyteller
    →  JudgeAgent  →  RevisionLoop (max 2 rounds)
    →  NarratorVoice cues (optional)
    →  UserFeedbackLoop (interactive revisions)
"""

import sys
import textwrap

from agents.input_guard import InputGuard
from agents.classifier import RequestClassifier
from agents.planner import StoryPlanner
from agents.storyteller import Storyteller
from agents.judge import JudgeAgent
from pipeline.revision_loop import RevisionLoop
from pipeline.feedback_loop import UserFeedbackLoop

# ── Display helpers ──────────────────────────────────────────────────────────

def _hr(char="─", width=70):
    print(char * width)


def _print_scores(judgment: dict):
    scores = judgment.get("scores", {})
    overall = judgment.get("overall_score", 0)
    passed  = judgment.get("pass_threshold", False)

    print(f"\n  Overall score : {overall:.1f} / 10  "
          f"({'PASSED' if passed else 'did not reach threshold'})")
    print()

    dim_labels = {
        "safety":               "Safety",
        "age_appropriateness":  "Age-Appropriate",
        "narrative_arc_quality":"Narrative Arc",
        "engagement":           "Engagement",
        "language_level":       "Language Level",
        "originality":          "Originality",
    }

    for dim, label in dim_labels.items():
        score = scores.get(dim, {}).get("score", 0)
        bar   = "█" * score + "░" * (10 - score)
        print(f"  {label:<18} {bar} {score}/10")


def _print_story(story: str):
    """Word-wraps and prints the story, preserving paragraph breaks."""
    for line in story.split("\n"):
        if line.strip():
            print(textwrap.fill(line, width=72))
        else:
            print()


# ── Core pipeline ────────────────────────────────────────────────────────────

def run_pipeline(user_request: str, age: int = 7, narrator_cues: bool = False) -> dict:
    """
    Runs the full story generation pipeline and returns a result dict.
    Progress is printed to stdout as each step completes.
    """
    from prompts.age_profiles import get_age_profile
    profile = get_age_profile(age)

    print("\n" + "═" * 70)
    print(f"  BEDTIME STORY GENERATOR  —  {profile['band_label']}")
    print("═" * 70)

    # ── Step 0: Safety guard ──────────────────────────────────────────────────
    print("\n  [0/4] Checking request…")
    guard  = InputGuard()
    result = guard.check(user_request)

    if result["verdict"] == "block":
        print("\n  Request not suitable for bedtime stories.")
        print(f"  {result.get('child_message', 'Please try a different topic.')}")
        return None

    if result["verdict"] == "reframe":
        print(f"        Adjusted: {result.get('reason', '')}")
        user_request = result["safe_prompt"] or user_request
        print(f"        New prompt: \"{user_request}\"")

    # ── Step 1: Classify ─────────────────────────────────────────────────────
    print("\n  [1/4] Understanding your request…")
    classifier = RequestClassifier()
    classification = classifier.classify(user_request)
    category = classification["category"]
    print(f"        Category : {category.upper().replace('_', ' ')}")
    print(f"        Reason   : {classification['reasoning']}")

    # ── Step 2: Plan ──────────────────────────────────────────────────────────
    print("\n  [2/4] Planning the story…")
    planner = StoryPlanner()
    outline = planner.plan(user_request, category, age)
    print(f"        Title    : \"{outline.get('title', '—')}\"")
    print(f"        Character: {outline.get('main_character', '—')}")
    print(f"        Setting  : {outline.get('setting', '—')}")

    # ── Step 3: Write ─────────────────────────────────────────────────────────
    print("\n  [3/4] Writing the story…")
    storyteller = Storyteller()
    initial_story = storyteller.write(outline, category, age)

    # ── Step 4: Judge + revise ────────────────────────────────────────────────
    print("\n  [4/4] Reviewing quality…")
    judge   = JudgeAgent()
    r_loop  = RevisionLoop(storyteller, judge)

    def _cb(step: str, msg: str):
        print(f"        {msg}")

    result   = r_loop.run(initial_story, user_request, age, _cb)
    story    = result["story"]
    judgment = result["judgment"]

    if result["used_fallback"]:
        print(
            f"\n  Note: story didn't reach target score after "
            f"{result['rounds']} revision(s). "
            f"Returning best version ({judgment['overall_score']:.1f}/10)."
        )

    # ── Optional: narrator cues ───────────────────────────────────────────────
    if narrator_cues:
        print("\n  Adding read-aloud narrator cues…")
        story = storyteller.add_narrator_cues(story)

    return {
        "story":    story,
        "judgment": judgment,
        "category": category,
        "outline":  outline,
        "rounds":   result["rounds"],
    }


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    print("\nWelcome to the Bedtime Story Generator")
    print("For children ages 5–10\n")

    user_request = input("What kind of story would you like?\n> ").strip()
    if not user_request:
        print("Please provide a story request.")
        sys.exit(1)

    age_input = input("\nChild's age (5-10) [default 7]: ").strip()
    try:
        age = int(age_input) if age_input else 7
    except ValueError:
        age = 7

    narrator_input = input("\nAdd read-aloud narrator cues for parents? [y/N] ").strip().lower()
    narrator_cues  = narrator_input == "y"

    result = run_pipeline(user_request, age, narrator_cues)
    if result is None:
        sys.exit(0)

    # ── Display story ─────────────────────────────────────────────────────────
    print()
    _hr("═")
    print("  YOUR BEDTIME STORY")
    _hr("═")
    print()
    _print_story(result["story"])

    # ── Display scores ────────────────────────────────────────────────────────
    print()
    _hr()
    print("  QUALITY REVIEW")
    _hr()
    _print_scores(result["judgment"])

    if result["judgment"].get("reasoning"):
        print(f"\n  Editor's note: {result['judgment']['reasoning']}")

    # ── User feedback loop ────────────────────────────────────────────────────
    _hr()
    storyteller = Storyteller()
    judge       = JudgeAgent()
    fb_loop     = UserFeedbackLoop(storyteller, judge)
    story       = result["story"]

    while True:
        print()
        feedback = input(
            "Would you like changes? "
            "(e.g. 'make it shorter', 'add a dragon', 'sillier')\n"
            "Press Enter to finish: "
        ).strip()

        if not feedback:
            break

        print("\n  Revising story…")
        revision = fb_loop.apply_feedback(story, feedback, user_request, age)
        story    = revision["story"]

        print()
        _hr("═")
        print("  REVISED STORY")
        _hr("═")
        print()
        _print_story(story)

        print()
        _hr()
        print("  QUALITY REVIEW")
        _hr()
        _print_scores(revision["judgment"])

    print("\nSweet dreams. Goodnight.\n")


if __name__ == "__main__":
    main()
