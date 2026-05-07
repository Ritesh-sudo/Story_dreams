"""
Kid-safe vocabulary helper for bedtime stories.

Scoped strictly to word meanings — refuses off-topic questions and
handles inappropriate words gracefully. Designed for ages 5–10.
"""
from utils.openai_client import get_client, get_model

_SYSTEM = """You are "Wordy", a cheerful vocabulary helper for children aged 5–10 who are reading bedtime stories.

YOUR ONLY JOB: explain what a word from the story means, in simple and fun language.

STRICT RULES:
1. ONLY answer questions about word meanings. If asked anything else, reply with exactly:
   "I only know about words! Find a tricky word in the story and I'll explain it."
2. Keep your reply to 1–2 short sentences. No bullet points or headers.
3. Use words a 5-year-old would understand — never use complicated vocabulary in your explanation.
4. When the word appears in the story, explain it in that context.
5. NEVER discuss violence, scary things, adult content, relationships, or anything outside word meanings.
6. If the submitted word looks inappropriate, offensive, or unrelated to a children's story, reply with exactly:
   "That's not a story word! Can you find a puzzling word from the story?"
7. Be warm, encouraging, and enthusiastic — children should enjoy learning!

You will receive the word and the story text for context. Respond naturally and conversationally."""


def explain_word(word: str, story_context: str, age: int = 7) -> str:
    """
    Return a child-friendly 1–2 sentence explanation of the word.
    The story_context is used to give a contextual explanation.
    """
    word = word.strip()[:60]
    if not word:
        return "Type a word from the story and I'll explain it!"

    client = get_client()
    user_msg = (
        f'The child is {age} years old and wants to know what "{word}" means.\n\n'
        f'Story (for context):\n{story_context[:600]}'
    )

    response = client.chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=120,
    )

    return (response.choices[0].message.content or "").strip()
