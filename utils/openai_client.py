import os
from openai import OpenAI, AsyncOpenAI

MODEL = "gpt-3.5-turbo"


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set.\n"
            "  export OPENAI_API_KEY=sk-..."
        )
    return OpenAI(api_key=api_key)


def get_model() -> str:
    return MODEL


def get_async_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set.\n"
            "  export OPENAI_API_KEY=sk-..."
        )
    return AsyncOpenAI(api_key=api_key)


async def generate_illustration(prompt: str) -> str | None:
    """Calls DALL-E 3 to create a story illustration. Returns the image URL or None on failure."""
    try:
        client = get_async_client()
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        return response.data[0].url
    except Exception as exc:
        print(f"[Illustration] skipped: {exc}", flush=True)
        return None
