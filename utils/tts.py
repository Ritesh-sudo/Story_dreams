"""
Text-to-speech using Microsoft Edge Neural TTS (via edge-tts).

No API key required. Returns both MP3 audio bytes and per-word timing data
so the frontend can highlight each word as it is spoken.

Voice: en-US-JennyNeural — warm, expressive, well-suited for storytelling.

Narrator cues are handled via multi-pass synthesis:
  [pause]      → gap between segments (natural sentence pause)
  [pause long] → same, with longer implied rest at end
  [whisper]    → next passage synthesized with slower rate + lower pitch
                 so it sounds softer and more gentle

The timing offset for each segment is derived from the audio byte count
(48 kbps CBR → 6 bytes/ms) so word-highlight sync stays accurate
across segments.
"""

import re
import edge_tts

_VOICE   = "en-US-JennyNeural"
_CUE_RE  = re.compile(r'\[(pause long|pause|whisper)\]', re.IGNORECASE)

# Prosody presets
_NORMAL  = {"rate": "-12%", "pitch": "+2Hz"}
_WHISPER = {"rate": "-35%", "pitch": "-3Hz"}  # softer, slower, lower

# audio-24khz-48kbitrate-mono-mp3: 48 000 bits/s = 6 000 bytes/s → 6 bytes/ms
_BYTES_PER_MS = 6.0


# ── Segment parser ────────────────────────────────────────────────────────────

def _parse_segments(text: str) -> list[dict]:
    """
    Split narrator text at cue markers.

    Returns a list of dicts, each either:
        {"type": "normal"|"whisper", "text": str}
      or
        {"type": "pause", "ms": int}
    """
    segments: list[dict] = []
    last_end  = 0
    is_whisper = False

    for m in _CUE_RE.finditer(text):
        chunk = text[last_end : m.start()].strip()
        if chunk:
            segments.append({"type": "whisper" if is_whisper else "normal", "text": chunk})
            is_whisper = False          # whisper applies to the ONE chunk before next cue

        cue = m.group(1).lower()
        if cue == "pause":
            segments.append({"type": "pause", "ms": 500})
        elif cue == "pause long":
            segments.append({"type": "pause", "ms": 1200})
        elif cue == "whisper":
            is_whisper = True           # flag: next text chunk is whispered

        last_end = m.end()

    tail = text[last_end:].strip()
    if tail:
        segments.append({"type": "whisper" if is_whisper else "normal", "text": tail})

    return segments


# ── Single-segment synthesizer ────────────────────────────────────────────────

async def _synth_segment(text: str, *, rate: str, pitch: str) -> tuple[bytes, list[dict]]:
    """Synthesize one text segment; return (mp3_bytes, word_timings)."""
    communicate = edge_tts.Communicate(
        text,
        voice=_VOICE,
        rate=rate,
        pitch=pitch,
        boundary="WordBoundary",
    )
    audio_chunks: list[bytes] = []
    word_timings: list[dict]  = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start_ms    = chunk["offset"]   / 10_000
            duration_ms = chunk["duration"] / 10_000
            word_timings.append({
                "text":     chunk["text"],
                "start_ms": round(start_ms, 1),
                "end_ms":   round(start_ms + duration_ms, 1),
            })

    if not audio_chunks:
        raise RuntimeError("Edge TTS returned no audio data for segment.")

    return b"".join(audio_chunks), word_timings


# ── Public API ────────────────────────────────────────────────────────────────

async def synthesize_async(text: str) -> tuple[bytes, list[dict]]:
    """
    Returns (mp3_bytes, word_timings).

    word_timings is a list of:
        {"text": str, "start_ms": float, "end_ms": float}

    Narrator cues ([pause], [pause long], [whisper]) are respected:
    whisper sections use a softer voice preset; pause markers are skipped
    (sentence-ending punctuation creates a natural breath in the audio).
    """
    text = text.strip()
    if not text:
        raise ValueError("Story text is empty.")

    # Fast path: no cues → single-pass synthesis
    if not _CUE_RE.search(text):
        return await _synth_segment(text, **_NORMAL)

    segments = _parse_segments(text)

    all_audio: list[bytes] = []
    all_timings: list[dict] = []
    offset_ms = 0.0

    for seg in segments:
        if seg["type"] == "pause":
            # No audio inserted for pauses; sentence-final punctuation already
            # creates a natural breath in the TTS output, so we skip rather than
            # misaligning word highlights by advancing offset without audio bytes.
            continue

        preset = _WHISPER if seg["type"] == "whisper" else _NORMAL
        audio, timings = await _synth_segment(seg["text"], **preset)

        # Offset each word timing by our running cursor
        for t in timings:
            all_timings.append({
                "text":     t["text"],
                "start_ms": round(t["start_ms"] + offset_ms, 1),
                "end_ms":   round(t["end_ms"]   + offset_ms, 1),
            })

        all_audio.append(audio)

        # Advance offset by actual audio duration (derived from CBR byte count)
        seg_duration_ms = len(audio) / _BYTES_PER_MS
        offset_ms += seg_duration_ms

    if not all_audio:
        raise RuntimeError("Edge TTS returned no audio data.")

    return b"".join(all_audio), all_timings
