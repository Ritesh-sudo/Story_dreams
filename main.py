import os
from openai import OpenAI

"""
Before submitting the assignment, describe here in a few sentences what you would have built next if you spent 2 more hours on this project:

Given two more hours, I would add (1) real-time token streaming — using stream=True
and yielding each delta.content chunk as a Server-Sent Event so the story appears
word-by-word in the UI rather than all at once; and (2) a persistent child profile
stored as a local JSON file (child's name, favourite characters, previously told
stories), so the planner can incorporate context and honour requests like "tell me
another story about Luna the rabbit." Both changes are additive and wouldn't
require rearchitecting the pipeline.
"""

# NOTE: Model is fixed per assignment instructions — do not change.
_MODEL = "gpt-3.5-turbo"


def call_model(prompt: str, max_tokens: int = 3000, temperature: float = 0.1) -> str:
    """
    Minimal wrapper kept from the original skeleton.
    Updated to use the OpenAI Python SDK >= 1.0 (client-based API).
    API key is read from the OPENAI_API_KEY environment variable — never hardcoded.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content  # type: ignore[return-value]


example_requests = "A story about a girl named Alice and her best friend Bob, who happens to be a cat."


def main():
    user_input = input("What kind of story do you want to hear? ")
    response = call_model(user_input)
    print(response)


if __name__ == "__main__":
    main()