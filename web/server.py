"""
FastAPI server for the Bedtime Story Generator web UI.

Run from the project root:
    uvicorn web.server:app --reload

Endpoints:
    GET  /            — serves index.html
    POST /generate    — SSE stream of agent progress + final story
    POST /revise      — applies user feedback, returns revised story JSON
"""

import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Agents and pipeline are imported from the project root (uvicorn adds "." to sys.path)
from agents.input_guard import InputGuard
from agents.classifier import RequestClassifier
from agents.planner import StoryPlanner
from agents.storyteller import Storyteller
from agents.judge import JudgeAgent
from pipeline.revision_loop import MAX_REVISION_ROUNDS
from utils.openai_client import generate_illustration
from utils.storage import save_story, get_all_stories, get_story
from utils.tts import synthesize_async as tts_synthesize_async
from utils.vocabulary import explain_word

app = FastAPI(title="Bedtime Story Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


# ── Request / response models ────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str
    age: int = 7
    category: str = ""        # empty = auto-detect
    child_name: str = ""      # optional personalisation


class ReviseRequest(BaseModel):
    story: str
    feedback: str
    original_request: str = ""
    age: int = 7


class TTSRequest(BaseModel):
    story_id: str = ""   # if set, load from history
    text: str = ""       # fallback: raw text passed directly


class VocabRequest(BaseModel):
    word: str
    story: str = ""      # story text for context
    age: int = 7


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return HTMLResponse((_static / "index.html").read_text())


@app.post("/generate")
async def generate(req: GenerateRequest):
    """
    Streams Server-Sent Events as each agent completes its step.

    Event format:  data: {"step": str, "type": "start"|"complete"|"error", "data": {…}}

    Steps in order: classify → plan → write → judge → [revise →] complete
    """
    return StreamingResponse(
        _generation_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/revise")
async def revise(req: ReviseRequest):
    """Applies user feedback synchronously and returns the revised story."""
    storyteller = Storyteller()
    judge       = JudgeAgent()

    revised       = storyteller.apply_user_feedback(req.story, req.feedback, req.age)
    narrator      = storyteller.add_narrator_cues(revised)
    judgment      = judge.evaluate(revised, req.original_request, req.age)

    return {"story": revised, "narrator_story": narrator, "judgment": judgment}


@app.get("/history")
async def history():
    """Returns the 50 most recent stories (no full text, for list display)."""
    return await asyncio.to_thread(get_all_stories)


@app.get("/history/{story_id}")
async def history_item(story_id: str):
    """Returns the full story record for a given ID."""
    record = await asyncio.to_thread(get_story, story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return record


@app.post("/vocabulary")
async def vocabulary(req: VocabRequest):
    """Explains a word from the story in kid-friendly language (ages 5-10)."""
    explanation = await asyncio.to_thread(explain_word, req.word, req.story, req.age)
    return {"word": req.word.strip(), "explanation": explanation}


@app.post("/tts")
async def tts(req: TTSRequest):
    """
    Synthesizes story text using Microsoft Edge Neural TTS.
    Returns JSON: { audio_b64: str, word_timings: [{text, start_ms, end_ms}] }
    """
    import base64

    text = req.text
    if req.story_id and not text:
        record = await asyncio.to_thread(get_story, req.story_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Story not found")
        text = record.get("story") or ""

    if not text.strip():
        raise HTTPException(status_code=400, detail="No story text provided.")

    try:
        mp3_bytes, word_timings = await tts_synthesize_async(text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "audio_b64":    base64.b64encode(mp3_bytes).decode(),
        "word_timings": word_timings,
    }


# ── SSE stream generator ─────────────────────────────────────────────────────

async def _generation_stream(req: GenerateRequest) -> AsyncGenerator[str, None]:
    """Runs the full pipeline, yielding SSE events at each agent boundary."""

    def _sse(step: str, event_type: str, data: dict) -> str:
        payload = json.dumps({"step": step, "type": event_type, "data": data})
        return f"data: {payload}\n\n"

    prompt     = req.prompt
    age        = req.age or 7
    child_name = req.child_name or ""

    try:
        # ── Guard ─────────────────────────────────────────────────────────────
        yield _sse("guard", "start", {"message": "Checking request…"})
        await asyncio.sleep(0)

        guard       = InputGuard()
        guard_result = await asyncio.to_thread(guard.check, prompt, age)
        verdict     = guard_result["verdict"]
        print(f"[GUARD] prompt={prompt!r}  verdict={verdict}  reason={guard_result.get('reason', '')}", flush=True)

        if verdict == "block":
            yield _sse("guard", "blocked", {
                "reason":        guard_result.get("reason", ""),
                "child_message": guard_result.get(
                    "child_message",
                    "That topic isn't quite right for a bedtime story. "
                    "Try asking for an adventure, a talking animal, or a magical world."
                ),
            })
            return

        if verdict == "reframe":
            prompt = guard_result.get("safe_prompt") or prompt
            yield _sse("guard", "complete", {
                "verdict": "reframe",
                "reason":  guard_result.get("reason", ""),
                "safe_prompt": prompt,
            })
        else:
            yield _sse("guard", "complete", {"verdict": "safe"})
        await asyncio.sleep(0)

        # ── Classify ─────────────────────────────────────────────────────────
        yield _sse("classify", "start", {"message": "Understanding your request…"})
        await asyncio.sleep(0)

        classifier   = RequestClassifier()
        classification = await asyncio.to_thread(classifier.classify, prompt)
        category     = req.category or classification["category"]

        yield _sse("classify", "complete", {
            "category": category,
            "reasoning": classification["reasoning"],
        })
        await asyncio.sleep(0)

        # ── Plan ──────────────────────────────────────────────────────────────
        yield _sse("plan", "start", {"message": "Planning the story…"})
        await asyncio.sleep(0)

        planner = StoryPlanner()
        outline = await asyncio.to_thread(planner.plan, prompt, category, age, child_name)

        yield _sse("plan", "complete", {"outline": outline})
        await asyncio.sleep(0)

        # Start illustration concurrently — runs while write + judge execute
        illus_prompt = (
            f"Children's watercolor picture book illustration. "
            f"{outline.get('main_character', 'A young hero')} in "
            f"{outline.get('setting', 'a magical world')}. "
            f"Warm pastel colors, cozy bedtime atmosphere, no text."
        )
        illus_task = asyncio.create_task(generate_illustration(illus_prompt))

        # ── Write (streaming) ─────────────────────────────────────────────────
        yield _sse("write", "start", {"message": "Writing your story…"})
        await asyncio.sleep(0)

        storyteller  = Storyteller()
        story_tokens: list[str] = []
        async for token in storyteller.write_stream_async(outline, category, age):
            story_tokens.append(token)
            yield _sse("write", "token", {"token": token})
            await asyncio.sleep(0)
        initial_story = "".join(story_tokens)

        yield _sse("write", "complete", {"story": initial_story})
        await asyncio.sleep(0)

        # ── Judge + optional revisions ────────────────────────────────────────
        yield _sse("judge", "start", {"message": "Reviewing for quality…"})
        await asyncio.sleep(0)

        judge      = JudgeAgent()
        story      = initial_story
        best_story = story
        best_judgment: dict = {}
        best_score = -1.0
        rounds_used = 0

        for round_num in range(MAX_REVISION_ROUNDS + 1):
            judgment = await asyncio.to_thread(judge.evaluate, story, prompt, age)

            if judgment["overall_score"] > best_score:
                best_score    = judgment["overall_score"]
                best_story    = story
                best_judgment = judgment

            if judgment["pass_threshold"]:
                rounds_used = round_num
                break

            if round_num < MAX_REVISION_ROUNDS:
                rounds_used = round_num + 1
                yield _sse("revise", "start", {
                    "message": f"Polishing story (revision {round_num + 1})…",
                    "round": round_num + 1,
                })
                await asyncio.sleep(0)

                notes = judgment.get("specific_revision_notes", [])
                story = await asyncio.to_thread(storyteller.revise, story, notes, age)
            else:
                rounds_used = MAX_REVISION_ROUNDS

        yield _sse("judge", "complete", {"judgment": best_judgment})
        await asyncio.sleep(0)

        # ── Narrator cues ─────────────────────────────────────────────────────
        narrator_story = await asyncio.to_thread(storyteller.add_narrator_cues, best_story)

        # ── Await illustration (capped — should be done by now) ───────────────
        image_url = None
        try:
            image_url = await asyncio.wait_for(illus_task, timeout=8.0)
        except Exception:
            image_url = None

        # ── Persist to history ─────────────────────────────────────────────────
        story_id = await asyncio.to_thread(
            save_story,
            prompt=prompt,
            age=age,
            category=category,
            title=outline.get("title", ""),
            story=best_story,
            narrator_story=narrator_story,
            judgment=best_judgment,
            image_url=image_url,
        )

        # ── Final payload ─────────────────────────────────────────────────────
        yield _sse("complete", "complete", {
            "story":          best_story,
            "narrator_story": narrator_story,
            "judgment":       best_judgment,
            "category":       category,
            "outline":        outline,
            "rounds":         rounds_used,
            "used_fallback":  not best_judgment.get("pass_threshold", False),
            "image_url":      image_url,
            "story_id":       story_id,
        })

    except Exception as exc:
        yield _sse("error", "error", {"message": str(exc)})
