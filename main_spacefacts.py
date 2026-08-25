"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v2)
==================================================================
All 100% free. Includes retries, fact-checking, dynamic captions,
crossfades, punchline SFX, caching, parallel TTS, and dry-run.
==================================================================
"""

print("Script started...")  # DEBUG

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

DRY_RUN = False

STATE_FILE = Path("state_spacefacts.json")
OUTPUT_DIR = Path("output_spacefacts")
CACHE_DIR = Path("cache_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

VIDEO_W, VIDEO_H = 1080, 1920

TTS_VOICES = [
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
    "en-US-JennyNeural",
    "en-AU-WilliamNeural",
]

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

BACKGROUND_AUDIO_ENABLED = True
BACKGROUND_AUDIO_VOLUME = 0.12
SPACE_BG_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3"
OCEAN_BG_AUDIO_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3"
BACKGROUND_CACHE_DIR = CACHE_DIR / "bg"
BACKGROUND_CACHE_DIR.mkdir(exist_ok=True)

PUNCHLINE_SFX_URL = "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a7b9c1.mp3"
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
    if p.exists() and p.stat().st_size > 1000:   # validate size
        return p
    return None

def save_cache_file(cache_subdir: Path, key: str, ext: str, content: bytes) -> Path:
    p = cache_subdir / f"{key}.{ext}"
    p.write_bytes(content)
    return p

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about a space/physics fact OR a sea/ocean fact.

Rules:
- Use contractions, vary sentence length.
- No rhetorical filler or stacked intensifiers.
- Include one moment of genuine surprise.
- Deliver the core fact clearly before the final scene.
- The FINAL scene must be a short joke or pun.

Break the script into scenes. Each scene is one or two sentences.
For each scene, provide:
- visual_type: "literal" or "abstract"
- visual_query: search term (literal) or AI image prompt (abstract, be cinematic)

Return ONLY valid JSON:
{
  "title": "...",
  "hook": "...",
  "scenes": [ {"narration": "...", "visual_type": "...", "visual_query": "..."} ],
  "hashtags": ["#shorts", "#space", "#facts"]
}

Topic: {topic}
"""

def generate_hook_variants(topic: str, count: int = 3) -> list:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")
    prompt = f"Write {count} extremely short, scroll-stopping hooks (max 6 words each) for a YouTube Short about: {topic}. Return ONLY a JSON list of strings, no other text."
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    hooks = json.loads(response.text)
    return sorted(hooks, key=len)

def fact_check(script_text: str) -> bool:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")
    prompt = f"Is the following fact accurate? Reply ONLY 'Yes' or 'No'.\n\n{script_text}"
    response = model.generate_content(prompt)
    return response.text.strip().lower().startswith("yes")

def generate_script(topic: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")

    log("  Generating hook variants...")
    hooks = generate_hook_variants(topic)
    best_hook = hooks[0]
    log(f"  Best hook: '{best_hook}'")

    for attempt in range(4):
        try:
            prompt = SCRIPT_SYSTEM_PROMPT.replace("{topic}", topic)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)
            data["hook"] = best_hook
            data["scenes"][0]["narration"] = best_hook + " " + data["scenes"][0]["narration"].split(".", 1)[-1].strip()

            full_text = " ".join([s["narration"] for s in data["scenes"]])
            if not fact_check(full_text):
                log("  ⚠️ Fact-check failed, regenerating...")
                continue

            assert "scenes" in data and len(data["scenes"]) > 0
            for scene in data["scenes"]:
                assert scene["visual_type"] in ("literal", "abstract")
            return data

        except Exception as e:
            log(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)

    raise RuntimeError("Failed to generate a valid script after retries.")

# ------------------------------------------------------------------
# 2. NARRATION (parallel Edge TTS)
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
# 3. VISUALS (cached, with expanded queries)
# ------------------------------------------------------------------

def expand_visual_query(original: str) -> list:
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
    return list(dict.fromkeys(variations))[:3]

def fetch_pexels_video_with_fallback(query: str, out_path: Path) -> Path | None:
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
                if len(video_data) > 1000:
                    out_path.write_bytes(video_data)
                    return out_path
        except Exception:
            continue
    return None

def get_cached_visual(scene: dict, index: int, run_dir: Path) -> dict:
    q = scene["visual_query"]
    key = cache_key(q)

    if scene["visual_type"] == "literal":
        cache_path = get_cached_file(CACHE_DIR / "pexels", key, "mp4")
        if cache_path:
            return {"type": "video", "path": cache_path}

        # Cache miss or invalid – try to download
        out_path = run_dir / f"visual_{index}.mp4"
        result = fetch_pexels_video_with_fallback(q, out_path)
        if result:
            # Save to global cache (overwrite if exists)
            cached = save_cache_file(CACHE_DIR / "pexels", key, "mp4", result.read_bytes())
            return {"type": "video", "path": cached}

        log(f"    Pexels failed, falling back to Pollinations for: {q}")

    # Abstract OR fallback from literal:
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

    # Ultimate fallback: black screen
    from moviepy import ColorClip
    fallback_path = run_dir / f"visual_{index}_fallback.jpg"
    clip = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0,0,0), duration=1)
    clip.save_frame(str(fallback_path))
    return {"type": "image", "path": fallback_path}

# ------------------------------------------------------------------
# 4. BACKGROUND & SFX
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
# 5. CHUNK TEXT for dynamic captions
# ------------------------------------------------------------------

def chunk_text(text: str) -> list:
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

# ------------------------------------------------------------------
# 6. ASSEMBLY (robust with fallbacks)
# ------------------------------------------------------------------

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path, topic: str) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx, CompositeAudioClip, ColorClip
    )

    scene_clips = []
    for i, scene in enumerate(script["scenes"]):
        try:
            audio_path = audio_clips[i]["path"]
            audio = AudioFileClip(str(audio_path))
            duration = audio.duration
            if duration <= 0:
                log(f"  Scene {i} has zero duration, skipping")
                continue

            visual = visuals[i]
            # Double‑check that the visual file actually exists
            if not visual["path"].exists():
                log(f"  Visual file missing for scene {i}, re‑fetching...")
                # Regenerate this visual and update the list
                visuals[i] = get_cached_visual(scene, i, run_dir)
                visual = visuals[i]

            if visual["type"] == "video":
                clip = VideoFileClip(str(visual["path"])).without_audio()
                if clip.duration < duration:
                    clip = clip.with_effects([vfx.Loop(duration=duration)])
                else:
                    clip = clip.subclipped(0, duration)
            else:
                clip = ImageClip(str(visual["path"])).with_duration(duration)

            clip = clip.with_effects([vfx.Resize(height=VIDEO_H)]).with_position("center")

            # Captions
            chunks = chunk_text(scene["narration"])
            chunk_duration = duration / len(chunks) if chunks else duration
            caption_clips = []
            for j, chunk in enumerate(chunks):
                start = j * chunk_duration
                txt = TextClip(
                    text=chunk,
                    font_size=56,
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    font=None,
                    method="caption",
                    size=(VIDEO_W - 100, None),
                    text_align="center",
                ).with_duration(chunk_duration).with_start(start).with_position(("center", "center"))

                txt = txt.with_effects([vfx.Resize(lambda t: 1 + 0.05 * (1 - t / max(chunk_duration, 0.01)))])
                caption_clips.append(txt)

            composite = CompositeVideoClip([clip] + caption_clips, size=(VIDEO_W, VIDEO_H))
            composite = composite.with_audio(audio)
            scene_clips.append(composite)
            log(f"  Scene {i} composed successfully")

        except Exception as e:
            log(f"  ❌ Scene {i} failed: {e}")
            # Fallback: black screen with text
            try:
                fallback = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0,0,0), duration=duration)
                txt = TextClip(
                    text=scene["narration"],
                    font_size=60,
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    font=None,
                    method="caption",
                    size=(VIDEO_W-100, None),
                    text_align="center",
                ).with_duration(duration).with_position("center")
                composite = CompositeVideoClip([fallback, txt], size=(VIDEO_W, VIDEO_H))
                composite = composite.with_audio(audio)
                scene_clips.append(composite)
                log(f"  Scene {i} replaced with fallback black screen")
            except Exception as e2:
                log(f"  ❌ Fallback also failed: {e2}")

    if not scene_clips:
        raise RuntimeError("No valid scenes could be assembled.")

    final = scene_clips[0]
    for clip in scene_clips[1:]:
        final = concatenate_videoclips([final, clip], method="compose", transition=vfx.CrossFadeIn(0.3))

    # Background
    bg_path = get_background_audio(topic)
    if bg_path and final.duration > 0:
        try:
            bg = AudioFileClip(str(bg_path))
            bg = bg.with_effects([vfx.Loop(duration=final.duration)])
            bg = bg.with_volume(BACKGROUND_AUDIO_VOLUME)
            final = final.with_audio(CompositeAudioClip([final.audio, bg]))
        except Exception as e:
            log(f"  Background mix failed: {e}")

    # SFX
    sfx_path = get_punchline_sfx()
    if sfx_path and len(scene_clips) > 0:
        try:
            sfx = AudioFileClip(str(sfx_path)).subclipped(0, 0.8)
            sfx = sfx.with_volume(0.4)
            sfx = sfx.with_start(final.duration - 0.8)
            final = final.with_audio(CompositeAudioClip([final.audio, sfx]))
        except Exception as e:
            log(f"  SFX overlay failed: {e}")

    out_path = run_dir / "final_video.mp4"
    log("  Rendering final video...")
    try:
        final.write_videofile(
            str(out_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
            threads=2,
        )
        if out_path.exists() and out_path.stat().st_size > 1000:
            log(f"  ✅ Video rendered: {out_path} ({out_path.stat().st_size/1e6:.2f} MB)")
        else:
            raise RuntimeError("Output video file is too small or missing.")
    except Exception as e:
        log(f"  ❌ Rendering failed: {e}")
        # Last-ditch fallback: simple black video
        try:
            log("  Attempting fallback render with minimal settings...")
            fallback_video = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0,0,0), duration=10)
            txt = TextClip("Video generation failed", font_size=60, color="white", font=None, duration=10).with_position("center")
            final_fallback = CompositeVideoClip([fallback_video, txt], size=(VIDEO_W, VIDEO_H))
            final_fallback.write_videofile(str(out_path), fps=1, codec="libx264", audio_codec="aac", verbose=False)
            log(f"  ⚠️ Fallback video created at {out_path}")
        except Exception as e2:
            log(f"  ❌ Fallback also failed: {e2}")
            raise

    return out_path

# ------------------------------------------------------------------
# 7. MAIN PIPELINE
# ------------------------------------------------------------------

def run_pipeline():
    try:
        topic = get_next_topic()
        log(f"Topic: {topic}")

        log("Generating script...")
        script = generate_script(topic)
        log(f"Title: {script['title']}")

        run_dir = OUTPUT_DIR / script["title"].replace(" ", "_")[:40]
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "script.json").write_text(json.dumps(script, indent=2))

        log("Synthesizing narration...")
        audio_clips = synthesize_scene_audio(script["scenes"], run_dir)

        log("Fetching visuals...")
        visuals = []
        for i, scene in enumerate(script["scenes"]):
            log(f"  Scene {i+1}: '{scene['visual_query']}'")
            visuals.append(get_cached_visual(scene, i, run_dir))

        log("Assembling video...")
        final_path = build_video(script, audio_clips, visuals, run_dir, topic)

        if DRY_RUN:
            log("DRY RUN: Skipping upload.")
            print(f"\n✅ Done: {final_path}")
            return

        log("Uploading to YouTube...")
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

    except Exception as e:
        log(f"❌ Pipeline crashed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    run_pipeline()
