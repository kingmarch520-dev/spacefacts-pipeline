"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v2)
==================================================================
Now with: retries, fact-checking, dynamic captions, crossfades,
punchline SFX, caching, parallel TTS, dry-run, and more.
All 100% free.
==================================================================
"""

import os
import json
import random
import asyncio
import time
import hashlib
import urllib.parse
from pathlib import Path
from datetime import datetime

import requests
import youtube_upload
import supabase_client

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "PASTE_YOUR_KEY_HERE")

# ---------- Mode ----------
DRY_RUN = False               # True = skip YouTube upload, just generate locally

# ---------- Paths ----------
STATE_FILE = Path("state_spacefacts.json")
OUTPUT_DIR = Path("output_spacefacts")
CACHE_DIR = Path("cache_spacefacts")          # for Pexels, Pollinations, SFX
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

VIDEO_W, VIDEO_H = 1080, 1920

# ---------- TTS ----------
TTS_VOICES = [
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
    "en-US-JennyNeural",
    "en-AU-WilliamNeural",
]

# ---------- Topics ----------
TOPIC_POOL = [
    "gravitational time dilation near a black hole",
    "what a neutron star's density actually means",
    "why the observable universe has an edge",
    "spaghettification near a black hole's event horizon",
    "how fast the Milky Way is actually moving",
    "what would happen if you fell into a wormhole",
    "why space is completely silent",
    "how close we've actually gotten to absolute zero",
    "the size of the largest known star compared to the sun",
    "why time moves slower for astronauts on the ISS",
    "what dark matter actually does to galaxies",
    "how a supernova could theoretically threaten Earth",
    "how little of the ocean floor has actually been mapped",
    "the crushing pressure at the bottom of the Mariana Trench",
    "why the deep ocean is in permanent total darkness",
    "how much of Earth's oxygen actually comes from the ocean",
    "what lives in hydrothermal vents with no sunlight at all",
    "how big the largest recorded giant squid actually was",
    "why most of the ocean is still completely unexplored",
    "how deep sunlight actually stops reaching underwater",
    "what happens to a human body at extreme ocean depth",
    "how old the oldest living sea creature actually is",
    "why bioluminescence exists in deep sea animals",
    "how massive a blue whale's heart actually is",
]

# ---------- Background Audio ----------
BACKGROUND_AUDIO_ENABLED = True
BACKGROUND_AUDIO_VOLUME = 0.12
SPACE_BG_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3"
OCEAN_BG_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3"
BACKGROUND_CACHE_DIR = CACHE_DIR / "bg"
BACKGROUND_CACHE_DIR.mkdir(exist_ok=True)

# ---------- Punchline SFX (free from Pixabay) ----------
PUNCHLINE_SFX_URL = "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a7b9c1.mp3"  # short drum hit
SFX_CACHE_DIR = CACHE_DIR / "sfx"
SFX_CACHE_DIR.mkdir(exist_ok=True)

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ------------------------------------------------------------------
# STATE
# ------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"index": 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def get_next_topic():
    state = load_state()
    idx = state["index"] % len(TOPIC_POOL)
    topic = TOPIC_POOL[idx]
    state["index"] = idx + 1
    save_state(state)
    return topic

# ------------------------------------------------------------------
# CACHE HELPERS
# ------------------------------------------------------------------

def cache_key(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()[:16]

def get_cached_file(cache_subdir: Path, key: str, ext: str) -> Path | None:
    p = cache_subdir / f"{key}.{ext}"
    return p if p.exists() else None

def save_cache_file(cache_subdir: Path, key: str, ext: str, content: bytes) -> Path:
    p = cache_subdir / f"{key}.{ext}"
    p.write_bytes(content)
    return p

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION (with retries + fact-check + hook optimization)
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about a space/physics fact OR a sea/ocean fact.

Rules for how it should sound:
- Write like you're explaining something wild to a friend, not narrating a documentary.
- Use contractions (it's, you'd, that's, don't).
- Vary sentence length: mix short punchy lines with one longer explanatory line.
- Do NOT use rhetorical filler like "this isn't science fiction, it's reality".
- Do NOT stack intensifiers (incredibly, absolutely, insanely). Pick ONE strong word max.
- Include exactly one moment of genuine surprise or disbelief, phrased like a reaction.
- Deliver the core fact clearly before the final scene. No summary, no moral.
- The FINAL scene must be a short joke or pun directly related to the fact — one line, genuinely funny.

Break the script into scenes. Each scene is one or two sentences.
For each scene, provide:
- visual_type: "literal" (real stock footage) or "abstract" (concept, no real footage)
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt (be specific, cinematic, include style/lighting).
- For the final joke scene, pick a literal visual that supports the punchline.

Return ONLY valid JSON, no markdown, in this shape:
{
  "title": "short punchy YouTube title, under 60 characters",
  "hook": "the first scene's narration — must stop the scroll in 2-3 seconds",
  "scenes": [
    { "narration": "...", "visual_type": "literal", "visual_query": "..." }
  ],
  "hashtags": ["#shorts", "#space", "#facts"]
}

Topic: {topic}
"""

# ---- Hook optimizer ----
def generate_hook_variants(topic: str, count: int = 3) -> list:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"Write {count} extremely short, scroll-stopping hooks (max 6 words each) for a YouTube Short about: {topic}. Return ONLY a JSON list of strings, no other text."
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    hooks = json.loads(response.text)
    return sorted(hooks, key=len)  # shortest first

def fact_check(script_text: str) -> bool:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"Is the following fact accurate? Reply ONLY 'Yes' or 'No'.\n\n{script_text}"
    response = model.generate_content(prompt)
    return response.text.strip().lower().startswith("yes")

def generate_script(topic: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # 1. Pick the shortest hook
    log("  Generating hook variants...")
    hooks = generate_hook_variants(topic)
    best_hook = hooks[0]
    log(f"  Best hook: '{best_hook}'")

    # 2. Generate the full script with retries
    for attempt in range(4):
        try:
            prompt = SCRIPT_SYSTEM_PROMPT.replace("{topic}", topic)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)
            # Replace hook with our optimized one
            data["hook"] = best_hook
            data["scenes"][0]["narration"] = best_hook + " " + data["scenes"][0]["narration"].split(".", 1)[-1].strip()

            # 3. Fact-check
            full_text = " ".join([s["narration"] for s in data["scenes"]])
            if not fact_check(full_text):
                log("  ⚠️ Fact-check failed, regenerating...")
                continue

            # Basic validation
            assert "scenes" in data and len(data["scenes"]) > 0
            for scene in data["scenes"]:
                assert scene["visual_type"] in ("literal", "abstract")
            return data

        except Exception as e:
            log(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)

    raise RuntimeError("Failed to generate a valid script after retries.")

# ------------------------------------------------------------------
# 2. NARRATION (Edge TTS) — parallel
# ------------------------------------------------------------------

async def _synthesize_one(text: str, voice: str, out_path: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))

async def _synthesize_all(scenes: list, run_dir: Path, voice: str):
    tasks = []
    for i, scene in enumerate(scenes):
        out_path = run_dir / f"scene_{i}.mp3"
        tasks.append(_synthesize_one(scene["narration"], voice, out_path))
    await asyncio.gather(*tasks)
    return [run_dir / f"scene_{i}.mp3" for i in range(len(scenes))]

def synthesize_scene_audio(scenes: list, run_dir: Path) -> list:
    from moviepy import AudioFileClip
    voice = random.choice(TTS_VOICES)
    log(f"  TTS voice: {voice}")
    # Run async parallel generation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    paths = loop.run_until_complete(_synthesize_all(scenes, run_dir, voice))
    loop.close()

    results = []
    for i, path in enumerate(paths):
        duration = AudioFileClip(str(path)).duration
        results.append({"path": path, "duration": duration})
    return results

# ------------------------------------------------------------------
# 3. VISUALS — with expanded query fallback + caching + cinematic prompts
# ------------------------------------------------------------------

def expand_visual_query(original: str) -> list:
    """Generate 2-3 search variations."""
    # Quick synonyms for common space/ocean terms
    swaps = {
        "galaxy": ["star cluster", "milky way", "cosmic"],
        "star": ["sun", "celestial", "stellar"],
        "ocean": ["sea", "water", "deep sea"],
        "fish": ["marine life", "school of fish", "underwater"],
        "black hole": ["spacetime", "singularity", "dark void"],
    }
    words = original.split()
    variations = [original]
    for i, word in enumerate(words):
        if word.lower() in swaps:
            for syn in swaps[word.lower()][:2]:
                new_words = words.copy()
                new_words[i] = syn
                variations.append(" ".join(new_words))
    return list(dict.fromkeys(variations))[:3]  # unique, max 3

def fetch_pexels_video_with_fallback(query: str, out_path: Path) -> Path | None:
    """Try original query, then expanded synonyms."""
    variations = expand_visual_query(query)
    for q in variations:
        log(f"    Trying Pexels: '{q}'")
        try:
            headers = {"Authorization": PEXELS_API_KEY}
            url = "https://api.pexels.com/videos/search"
            params = {"query": q, "orientation": "portrait", "per_page": 5}
            r = requests.get(url, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            videos = r.json().get("videos", [])
            if videos:
                video = random.choice(videos[:min(3, len(videos))])
                files = sorted(video["video_files"], key=lambda f: f.get("width", 0))
                chosen = next((f for f in files if f.get("width", 0) >= 720), files[-1])
                video_data = requests.get(chosen["link"], timeout=30).content
                if len(video_data) > 1000:  # sanity check
                    out_path.write_bytes(video_data)
                    return out_path
        except Exception:
            continue
    return None

def get_cached_visual(scene: dict, index: int, run_dir: Path) -> dict:
    """Return {'type': 'video'|'image', 'path': Path}.
       Uses caching by query hash.
    """
    q = scene["visual_query"]
    key = cache_key(q)

    # If literal, try cache first
    if scene["visual_type"] == "literal":
        cache_path = get_cached_file(CACHE_DIR / "pexels", key, "mp4")
        if cache_path:
            return {"type": "video", "path": cache_path}

        out_path = run_dir / f"visual_{index}.mp4"
        result = fetch_pexels_video_with_fallback(q, out_path)
        if result:
            # save to global cache
            cached = save_cache_file(CACHE_DIR / "pexels", key, "mp4", result.read_bytes())
            return {"type": "video", "path": cached}

        # fall through to Pollinations
        log(f"    Pexels failed, falling back to Pollinations for: {q}")

    # Abstract OR fallback from literal:
    # Enhance prompt for Pollinations (cinematic)
    enhanced_prompt = f"{q}, cinematic, dramatic lighting, photorealistic, 8k, highly detailed"
    key = cache_key(enhanced_prompt)
    cache_path = get_cached_file(CACHE_DIR / "pollinations", key, "jpg")
    if cache_path:
        return {"type": "image", "path": cache_path}

    out_path = run_dir / f"visual_{index}.jpg"
    try:
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced_prompt)}?width=1080&height=1920&nologo=true"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if len(r.content) > 1000:
            out_path.write_bytes(r.content)
            cached = save_cache_file(CACHE_DIR / "pollinations", key, "jpg", r.content)
            return {"type": "image", "path": cached}
    except Exception as e:
        log(f"    Pollinations error: {e}")

    # Ultimate fallback: a static black image with text
    from moviepy import ColorClip
    fallback_path = run_dir / f"visual_{index}_fallback.jpg"
    clip = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0,0,0), duration=1)
    clip.save_frame(str(fallback_path))
    return {"type": "image", "path": fallback_path}

# ------------------------------------------------------------------
# 4. BACKGROUND AUDIO + SFX (cached)
# ------------------------------------------------------------------

def get_background_audio(topic: str) -> Path | None:
    if not BACKGROUND_AUDIO_ENABLED:
        return None
    if any(w in topic.lower() for w in ("ocean", "sea", "mariana", "water", "deep")):
        url = OCEAN_BG_AUDIO_URL
    else:
        url = SPACE_BG_AUDIO_URL
    key = cache_key(url)
    cache_path = get_cached_file(BACKGROUND_CACHE_DIR, key, "mp3")
    if cache_path:
        return cache_path
    try:
        log("  Downloading background audio...")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return save_cache_file(BACKGROUND_CACHE_DIR, key, "mp3", r.content)
    except Exception as e:
        log(f"  Background download failed: {e}")
        return None

def get_punchline_sfx() -> Path | None:
    key = cache_key(PUNCHLINE_SFX_URL)
    cache_path = get_cached_file(SFX_CACHE_DIR, key, "mp3")
    if cache_path:
        return cache_path
    try:
        log("  Downloading punchline SFX...")
        r = requests.get(PUNCHLINE_SFX_URL, timeout=20)
        r.raise_for_status()
        return save_cache_file(SFX_CACHE_DIR, key, "mp3", r.content)
    except Exception:
        return None

# ------------------------------------------------------------------
# 5. ASSEMBLY — crossfades, dynamic captions (chunked), SFX overlay
# ------------------------------------------------------------------

def chunk_text(text: str) -> list:
    """Split into chunks by punctuation, keep delimiters."""
    import re
    parts = re.split(r'([.!?])', text)
    chunks = []
    for i in range(0, len(parts)-1, 2):
        chunk = (parts[i] + parts[i+1]).strip()
        if chunk:
            chunks.append(chunk)
    if len(parts) % 2 == 1 and parts[-1].strip():
        chunks.append(parts[-1].strip())
    return chunks if chunks else [text]

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path, topic: str) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx, CompositeAudioClip, ColorClip
    )

    scene_clips = []

    for i, scene in enumerate(script["scenes"]):
        audio_path = audio_clips[i]["path"]
        audio = AudioFileClip(str(audio_path))
        duration = audio.duration
        visual = visuals[i]

        # ---- Load visual ----
        if visual["type"] == "video":
            clip = VideoFileClip(str(visual["path"])).without_audio()
            if clip.duration < duration:
                clip = clip.with_effects([vfx.Loop(duration=duration)])
            else:
                clip = clip.subclipped(0, duration)
        else:
            clip = ImageClip(str(visual["path"])).with_duration(duration)

        clip = clip.with_effects([vfx.Resize(height=VIDEO_H)]).with_position("center")

        # ---- Dynamic chunked captions ----
        chunks = chunk_text(scene["narration"])
        chunk_duration = duration / len(chunks)
        caption_clips = []
        for j, chunk in enumerate(chunks):
            start = j * chunk_duration
            txt = TextClip(
                text=chunk,
                font_size=56,
                color="white",
                stroke_color="black",
                stroke_width=2,
                font="Arial",
                method="caption",
                size=(VIDEO_W - 100, None),
                text_align="center",
            ).with_duration(chunk_duration).with_start(start).with_position(("center", "center"))

            # Add a subtle scale pulse at start
            txt = txt.with_effects([vfx.Resize(lambda t: 1 + 0.05 * (1 - t / chunk_duration))])
            caption_clips.append(txt)

        # ---- Combine visual + captions ----
        composite = CompositeVideoClip([clip] + caption_clips, size=(VIDEO_W, VIDEO_H))
        composite = composite.with_audio(audio)
        scene_clips.append(composite)

    # ---- Crossfade transitions ----
    final = scene_clips[0]
    for clip in scene_clips[1:]:
        final = concatenate_videoclips([final, clip], method="compose", transition=vfx.CrossFadeIn(0.3))

    # ---- Background audio ----
    bg_path = get_background_audio(topic)
    if bg_path and final.duration > 0:
        try:
            bg = AudioFileClip(str(bg_path))
            bg = bg.with_effects([vfx.Loop(duration=final.duration)])
            bg = bg.with_volume(BACKGROUND_AUDIO_VOLUME)
            final = final.with_audio(CompositeAudioClip([final.audio, bg]))
        except Exception as e:
            log(f"  Background mix failed: {e}")

    # ---- Punchline SFX on the last scene ----
    sfx_path = get_punchline_sfx()
    if sfx_path and len(scene_clips) > 0:
        try:
            # Overlay on last 0.8s of the final scene
            sfx = AudioFileClip(str(sfx_path)).subclipped(0, 0.8)
            sfx = sfx.with_volume(0.4)
            # Position at the end of the video
            sfx = sfx.with_start(final.duration - 0.8)
            final = final.with_audio(CompositeAudioClip([final.audio, sfx]))
        except Exception as e:
            log(f"  SFX overlay failed: {e}")