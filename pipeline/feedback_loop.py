"""
UserFeedbackLoop — applies post-delivery parent feedback and re-judges.

After the child's story is delivered, the parent can request changes in natural
language ("make it shorter", "add a dragon", "calmer ending"). The revised story
is re-judged before being shown so quality is maintained even after user edits.
"""


class UserFeedbackLoop:
    def __init__(self, storyteller, judge):
        self._storyteller = storyteller
        self._judge = judge

    def apply_feedback(
        self, story: str, feedback: str, original_request: str = "", age: int = 7
    ) -> dict:
        """
        Revises the story based on user feedback, then re-evaluates.

        Returns {"story": str, "narrator_story": str, "judgment": dict}
        """
        revised = self._storyteller.apply_user_feedback(story, feedback, age)
        narrator_story = self._storyteller.add_narrator_cues(revised)
        judgment = self._judge.evaluate(revised, original_request, age)

        return {
            "story": revised,
            "narrator_story": narrator_story,
            "judgment": judgment,
        }
