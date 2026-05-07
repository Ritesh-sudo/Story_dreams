"""
RevisionLoop — runs up to MAX_REVISION_ROUNDS of judge→revise cycles.

Why max 2 rounds:
  The biggest quality jump always comes in revision 1. By revision 2, the model
  is approaching diminishing returns — it changes things rather than improving them.
  More critically, each round costs 2-3 API calls; 2 rounds keeps the pipeline
  responsive while covering most real failure modes. If the story still fails after
  2 rounds, we return the highest-scoring version seen — a good-enough story beats
  an infinite loop.
"""

from typing import Callable, Optional

MAX_REVISION_ROUNDS = 2


class RevisionLoop:
    def __init__(self, storyteller, judge):
        self._storyteller = storyteller
        self._judge = judge

    def run(
        self,
        initial_story: str,
        original_request: str = "",
        age: int = 7,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> dict:
        """
        Iteratively revises until the story passes the judge or rounds are exhausted.

        Returns:
        {
          "story"        : str,   # best version found
          "judgment"     : dict,  # judge result for that version
          "rounds"       : int,   # how many revision rounds were used (0 = passed on first try)
          "used_fallback": bool,  # True if story never passed the threshold
        }
        """
        story = initial_story
        best_story = story
        best_judgment: Optional[dict] = None
        best_score = -1.0
        rounds_used = 0

        for round_num in range(MAX_REVISION_ROUNDS + 1):
            # Round 0 = initial evaluation; rounds 1-2 = post-revision evaluations
            if progress_callback:
                if round_num == 0:
                    progress_callback("judging", "Reviewing for quality…")
                else:
                    progress_callback("revising", f"Polishing story (revision {round_num})…")

            judgment = self._judge.evaluate(story, original_request, age)

            if judgment["overall_score"] > best_score:
                best_score = judgment["overall_score"]
                best_story = story
                best_judgment = judgment

            if judgment["pass_threshold"]:
                return {
                    "story": story,
                    "judgment": judgment,
                    "rounds": round_num,
                    "used_fallback": False,
                }

            # Still failing — revise if we have rounds left
            if round_num < MAX_REVISION_ROUNDS:
                rounds_used = round_num + 1
                notes = judgment.get("specific_revision_notes", [])
                story = self._storyteller.revise(story, notes, age)

        return {
            "story": best_story,
            "judgment": best_judgment,
            "rounds": rounds_used,
            "used_fallback": True,
        }
