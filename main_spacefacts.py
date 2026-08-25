"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v1.5)
==================================================================
Stable core with:
- Caching (TTS + visuals)
- Parallel TTS
- Retries & better error handling
- Optional background audio
- Dry-run mode
- Enhanced logging
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

DRY_RUN = False                     # Set True to skip upload/logging

STATE_FILE = Path("state_spacefacts.json")
OUTPUT_DIR = Path("output_spacefacts")
CACHE_DIR = Path("cache_spacefacts")   # NEW: global cache for TTS/visuals
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Optional background audio (toggle)
BACKGROUND_AUDIO_ENABLED = True
BACKGROUND_AUDIO_VOLUME = 0.10
SPACE_BG_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3"
OCEAN_BG_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3"
BACKGROUND_CACHE_DIR = CACHE_DIR / "bg"
BACKGROUND_CACHE_DIR.mkdir(exist_ok=True)

VIDEO_W, VIDEO_H = 1080, 1920

TTS_VOICES = [
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
    "en-US-JennyNeural",
    "en-AU-WilliamNeural",
]

TOPIC_POOL = [
    # space / physics
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
    # sea / ocean
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
    if p.exists() and p.stat().st_size > 1000:
        return p
    return None

def save_cache_file(cache_subdir: Path, key: str, ext: str, content: bytes) -> Path:
    p = cache_subdir / f"{key}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION (with retries and optional hook variants)
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about a space/physics fact OR a sea/ocean fact.

Rules for how it should sound:
- Write like you're explaining something wild to a friend, not narrating
  a documentary.
- Use contractions (it's, you'd, that's, don't).
- Vary sentence length: mix short punchy lines with one longer
  explanatory line.
- Do NOT use rhetorical filler like "this isn't science fiction, it's
  reality" or "prepare to have your mind blown."
- Do NOT stack intensifiers (incredibly, absolutely, insanely). Pick
  ONE strong word max per sentence, and only when it's earned.
- Include exactly one moment of genuine surprise or disbelief, phrased
  like a reaction, not a lecture.
- Deliver the core fact clearly before the final scene. No summary, no
  moral, no "makes you think" closing line.
- The FINAL scene must be a short joke or pun directly related to the
  fact — one line, genuinely funny, not corny "dad joke for the sake
  of it" filler. It should feel like a natural button on the video, the
  kind of line that gets a laugh-comment.

Break the script into scenes. Each scene is one or two sentences of
narration, including the final joke scene. For each scene, also provide
a visual:
- visual_type: "literal" if real stock footage of this exists
- visual_type: "abstract" if it's a concept with no real footage
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt (be cinematic).

Return ONLY valid JSON, no markdown fences, no commentary, in this
exact shape:

{
  "title": "short punchy YouTube title, under 60 characters",
  "hook": "the first scene's narration — must stop the scroll in 2-3 seconds",
  "scenes": [
    {
      "narration": "...",
      "visual_type": "literal",
      "visual_query": "..."
    }
  ],
  "hashtags": ["#shorts", "#space", "#facts"]
}

Topic: {topic}
"""

def generate_script(topic: str, use_hook_variants: bool = True) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")

    # Optional: generate multiple hooks and pick the shortest
    if use_hook_variants:
        try:
            hook_prompt = f"Write 3 extremely short, scroll-stopping hooks (max 6 words each) for a YouTube Short about: {topic}. Return ONLY a JSON list of strings, no other text."
            hook_resp = model.generate_content(hook_prompt, generation_config={"response_mime_type": "application/json"})
            hooks = json.loads(hook_resp.text)
            best_hook = sorted(hooks, key=len)[0]  # shortest
            log(f"  Best hook: '{best_hook}'")
        except Exception:
            best_hook = None
    else:
        best_hook = None

    for attempt in range(4):   # retry up to 4 times
        try:
            prompt = SCRIPT_SYSTEM_PROMPT.replace("{topic}", topic)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)

            # Replace hook if we generated one
            if best_hook:
                data["hook"] = best_hook
                # Prepend hook to first scene's narration (if it doesn't already contain it)
                first = data["scenes"][0]["narration"]
                if not first.startswith(best_hook):
                    data["scenes"][0]["narration"] = best_hook + " " + first

            # Basic validation
            assert "scenes" in data and len(data["scenes"]) > 0
            for scene in data["scenes"]:
                assert scene["visual_type"] in ("literal", "abstract")
            return data

        except Exception as e:
            log(f"  Script attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)

    raise RuntimeError("Failed to generate a valid script after retries.")

# ------------------------------------------------------------------
# 2. NARRATION (parallel Edge TTS with caching)
# ------------------------------------------------------------------

async def _synthesize_one(text: str, voice: str, out_path: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))

async def _synthesize_all(scenes: list, run_dir: Path, voice: str, cache_subdir: Path = None):
    tasks = []
    for i, scene in enumerate(scenes):
        # Use caching if cache_subdir provided
        if cache_subdir:
            key = cache_key(scene["narration"] + voice)
            cached = get_cached_file(cache_subdir, key, "mp3")
            if cached:
                # Copy cached file to run_dir (or use directly)
                target = run_dir / f"scene_{i}.mp3"
                target.write_bytes(cached.read_bytes())
                continue
        out_path = run_dir / f"scene_{i}.mp3"
        tasks.append(_synthesize_one(scene["narration"], voice, out_path))

    if tasks:
        await asyncio.gather(*tasks)

    # Now return all paths (may include cached ones)
    paths = []
    for i in range(len(scenes)):
        p = run_dir / f"scene_{i}.mp3"
        if p.exists():
            # If cache_subdir and not already cached, save it
            if cache_subdir:
                key = cache_key(scenes[i]["narration"] + voice)
                if not get_cached_file(cache_subdir, key, "mp3"):
                    save_cache_file(cache_subdir, key, "mp3", p.read_bytes())
            paths.append(p)
        else:
            raise FileNotFoundError(f"Scene {i} audio missing")
    return paths

def synthesize_scene_audio(scenes: list, run_dir: Path) -> list:
    from moviepy import AudioFileClip
    voice = random.choice(TTS_VOICES)
    log(f"  TTS voice: {voice}")

    # Use a global TTS cache
    tts_cache = CACHE_DIR / "tts"
    tts_cache.mkdir(exist_ok=True)

    # Ensure we have a fresh event loop (safe for Colab)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    paths = loop.run_until_complete(_synthesize_all(scenes, run_dir, voice, tts_cache))
    loop.close()

    results = []
    for i, path in enumerate(paths):
        duration = AudioFileClip(str(path)).duration
        results.append({"path": path, "duration": duration})
    return results

# ------------------------------------------------------------------
# 3. VISUALS — Pexels (with retries) + Pollinations (with fallback)
# ------------------------------------------------------------------

def fetch_pexels_video(query: str, out_path: Path, max_retries: int = 2) -> Path | None:
    headers = {"Authorization": PEXELS_API_KEY}
    url = "https://api.pexels.com/videos/search"
    params = {"query": query, "orientation": "portrait", "per_page": 5}

    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=20)
            r.raise_for_status()
            videos = r.json().get("videos", [])
            if not videos:
                return None

            video = random.choice(videos[: min(3, len(videos))])
            files = sorted(video["video_files"], key=lambda f: f.get("width", 0))
            chosen = next((f for f in files if f.get("width", 0) >= 720), files[-1])

            video_data = requests.get(chosen["link"], timeout=30).content
            if len(video_data) > 1000:
                out_path.write_bytes(video_data)
                return out_path
        except Exception as e:
            log(f"    Pexels attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)
    return None

def fetch_pollinations_image(prompt: str, out_path: Path) -> Path | None:
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if len(r.content) > 1000:
            out_path.write_bytes(r.content)
            return out_path
    except Exception as e:
        log(f"    Pollinations error: {e}")
    return None

def fetch_visual_for_scene(scene: dict, index: int, run_dir: Path) -> dict:
    # Check global cache first (by visual_query hash)
    q = scene["visual_query"]
    key = cache_key(q)
    if scene["visual_type"] == "literal":
        cache_subdir = CACHE_DIR / "pexels"
        cache_subdir.mkdir(exist_ok=True)
        cached = get_cached_file(cache_subdir, key, "mp4")
        if cached:
            return {"type": "video", "path": cached}

    # Abstract or no cache – generate
    if scene["visual_type"] == "literal":
        out_path = run_dir / f"visual_{index}.mp4"
        result = fetch_pexels_video(scene["visual_query"], out_path)
        if result:
            # Save to global cache
            save_cache_file(cache_subdir, key, "mp4", result.read_bytes())
            return {"type": "video", "path": result}
        # Fall through to Pollinations
        log(f"  Pexels failed, falling back to Pollinations for: {q}")

    # Abstract or fallback
    enhanced_prompt = f"{q}, cinematic, dramatic lighting, photorealistic, 8k"
    key = cache_key(enhanced_prompt)
    cache_subdir = CACHE_DIR / "pollinations"
    cache_subdir.mkdir(exist_ok=True)
    cached = get_cached_file(cache_subdir, key, "jpg")
    if cached:
        return {"type": "image", "path": cached}

    out_path = run_dir / f"visual_{index}.jpg"
    result = fetch_pollinations_image(enhanced_prompt, out_path)
    if result:
        save_cache_file(cache_subdir, key, "jpg", result.read_bytes())
        return {"type": "image", "path": result}

    # Ultimate fallback: solid color frame
    from moviepy import ColorClip
    fallback_path = run_dir / f"visual_{index}_fallback.jpg"
    clip = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0, 0, 0), duration=1)
    clip.save_frame(str(fallback_path))
    return {"type": "image", "path": fallback_path}

# ------------------------------------------------------------------
# 4. ASSEMBLY (with optional background audio)
# ------------------------------------------------------------------

def get_background_audio(topic: str) -> Path | None:
    if not BACKGROUND_AUDIO_ENABLED:
        return None
    if any(w in topic.lower() for w in ("ocean", "sea", "mariana", "water", "deep")):
        url = OCEAN_BG_AUDIO_URL
    else:
        url = SPACE_BG_AUDIO_URL
    key = cache_key(url)
    cached = get_cached_file(BACKGROUND_CACHE_DIR, key, "mp3")
    if cached:
        return cached
    try:
        log("  Downloading background audio...")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return save_cache_file(BACKGROUND_CACHE_DIR, key, "mp3", r.content)
    except Exception as e:
        log(f"  Background download failed: {e}")
        return None

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path, topic: str) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx, CompositeAudioClip
    )

    scene_clips = []

    for i, scene in enumerate(script["scenes"]):
        audio = AudioFileClip(str(audio_clips[i]["path"]))
        duration = audio.duration
        visual = visuals[i]

        if visual["type"] == "video":
            clip = VideoFileClip(str(visual["path"])).without_audio()
            if clip.duration < duration:
                clip = clip.with_effects([vfx.Loop(duration=duration)])
            else:
                clip = clip.subclipped(0, duration)
        else:
            clip = ImageClip(str(visual["path"])).with_duration(duration)

        # Vertical resize and center
        clip = clip.with_effects([vfx.Resize(height=VIDEO_H)]).with_position(("center", "center"))

        # Nicer captions (white with black outline, larger font)
        caption = TextClip(
            text=scene["narration"],
            font="Arial",                    # safer default
            font_size=56,
            color="white",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(VIDEO_W - 120, None),
            text_align="center",
            duration=duration,
        ).with_position(("center", "center"))

        # Slight zoom effect on caption (optional)
        caption = caption.with_effects([vfx.Resize(lambda t: 1 + 0.04 * (1 - t / duration))])

        composite = CompositeVideoClip([clip, caption], size=(VIDEO_W, VIDEO_H))
        composite = composite.with_audio(audio)
        scene_clips.append(composite)

    final = concatenate_videoclips(scene_clips, method="compose")

    # Add background music
    bg_path = get_background_audio(topic)
    if bg_path and final.duration > 0:
        try:
            bg = AudioFileClip(str(bg_path))
            bg = bg.with_effects([vfx.Loop(duration=final.duration)])
            bg = bg.with_volume(BACKGROUND_AUDIO_VOLUME)
            final = final.with_audio(CompositeAudioClip([final.audio, bg]))
        except Exception as e:
            log(f"  Background mix failed: {e}")

    out_path = run_dir / "final_video.mp4"
    final.write_videofile(
        str(out_path), fps=30, codec="libx264", audio_codec="aac"
    )
    return out_path

# ------------------------------------------------------------------
# MAIN PIPELINE
# ------------------------------------------------------------------

def run_pipeline():
    topic = get_next_topic()
    log(f"Topic: {topic}")

    log("Generating script...")
    script = generate_script(topic, use_hook_variants=True)
    log(f"Title: {script['title']}")

    run_dir = OUTPUT_DIR / script["title"].replace(" ", "_")[:40]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps(script, indent=2))

    log("Synthesizing narration...")
    audio_clips = synthesize_scene_audio(script["scenes"], run_dir)

    log("Fetching visuals...")
    visuals = [
        fetch_visual_for_scene(scene, i, run_dir)
        for i, scene in enumerate(script["scenes"])
    ]

    log("Assembling video...")
    final_path = build_video(script, audio_clips, visuals, run_dir, topic)

    if DRY_RUN:
        log("DRY RUN: Skipping upload and logging.")
        print(f"\n✅ Done: {final_path}")
        return

    log("Uploading to YouTube as unlisted...")
    description = f"{script.get('hook', '')}\n\n{' '.join(script['hashtags'])}"
    upload_result = youtube_upload.upload_video(
        file_path=str(final_path),
        title=script["title"],
        description=description,
        tags=[h.replace("#", "") for h in script["hashtags"]],
        privacy_status="unlisted",
    )
    video_id = upload_result["id"]
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    supabase_client.log_video(
        youtube_id=video_id,
        title=script["title"],
        description=description,
        hashtags=script["hashtags"],
        thumbnail_url=thumbnail_url,
        topic=topic,
        status="unlisted",
    )

    print(f"\n🎬 Done: {final_path}")
    print(f"📺 YouTube (unlisted): https://youtu.be/{video_id}")
    print("Review and publish from the dashboard.")

if __name__ == "__main__":
    run_pipeline()