"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab. Run cells top to bottom, or paste into
one cell and execute.

WHAT THIS DOES DIFFERENTLY FROM YOUR OLD PIPELINE:
1. Script generation returns scene-by-scene JSON (not one blob),
   so every line of narration has its own matching visual.
2. Each scene is tagged "literal" or "abstract":
   - literal  -> searched on Pexels (real stock footage)
   - abstract -> generated with Pollinations.ai (AI image), for
     concepts that don't exist as real footage (time dilation,
     event horizons, gravity wells, etc.)
3. Narration uses Edge TTS instead of gTTS — free, no API key,
   much more natural prosody.
4. Script-writing prompt is engineered to avoid "AI voice" —
   no rhetorical filler, no stacked intensifiers, contractions,
   varied sentence rhythm.

REQUIRED INSTALLS (run first in Colab):
    !pip install google-generativeai edge-tts moviepy pillow requests --quiet

REQUIRED API KEYS (set as Colab secrets or env vars):
    GEMINI_API_KEY   -> https://aistudio.google.com/apikey (free)
    PEXELS_API_KEY   -> https://www.pexels.com/api/ (free)
    Pollinations needs NO KEY — it's a plain GET request.
==================================================================
"""

import os
import json
import random
import asyncio
import requests
from pathlib import Path

import youtube_upload
import supabase_client

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "PASTE_YOUR_KEY_HERE")

STATE_FILE = Path("state_spacefacts.json")
OUTPUT_DIR = Path("output_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)

VIDEO_W, VIDEO_H = 1080, 1920  # vertical shorts

# Rotate between a small, consistent set of Edge TTS voices.
# Pick calm/explainer-toned voices, not overly dramatic ones.
TTS_VOICES = [
    "en-US-GuyNeural",       # calm male
    "en-GB-RyanNeural",      # measured British male
    "en-US-JennyNeural",     # warm female, explainer tone
    "en-AU-WilliamNeural",   # relaxed Australian male
]

# A rotating pool of space/physics sub-topics so state.json cycles
# through fresh angles instead of repeating.
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
]

# ------------------------------------------------------------------
# STATE HANDLING (sequential topic cycling, same pattern as before)
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
# 1. SCRIPT GENERATION (Gemini) — scene-segmented, "less AI" prompt
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about a space or physics fact.

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
- End on the fact itself. No summary, no moral, no "makes you think"
  closing line.

Break the script into scenes. Each scene is one or two sentences of
narration. For each scene, also provide a visual:
- visual_type: "literal" if real stock footage of this exists
  (e.g. a dam, the ISS, a starfield, a person walking)
- visual_type: "abstract" if it's a concept with no real footage
  (e.g. gravitational time dilation, a wormhole cross-section,
  spacetime curvature)
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt (can be
  longer, be specific and cinematic).

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

def generate_script(topic: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")

    prompt = SCRIPT_SYSTEM_PROMPT.replace("{topic}", topic)
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )

    data = json.loads(response.text)

    # basic validation so a bad Gemini response doesn't silently
    # break the rest of the pipeline
    assert "scenes" in data and len(data["scenes"]) > 0, "No scenes returned"
    for scene in data["scenes"]:
        assert scene["visual_type"] in ("literal", "abstract")

    return data

# ------------------------------------------------------------------
# 2. NARRATION (Edge TTS) — per scene, so we know each clip's timing
# ------------------------------------------------------------------

async def _synthesize(text: str, voice: str, out_path: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))

def synthesize_scene_audio(scenes: list, run_dir: Path) -> list:
    """Generates one mp3 per scene, returns list of (path, duration)."""
    from moviepy.editor import AudioFileClip

    voice = random.choice(TTS_VOICES)
    results = []

    for i, scene in enumerate(scenes):
        out_path = run_dir / f"scene_{i}.mp3"
        asyncio.run(_synthesize(scene["narration"], voice, out_path))
        duration = AudioFileClip(str(out_path)).duration
        results.append({"path": out_path, "duration": duration})

    return results

# ------------------------------------------------------------------
# 3. VISUALS — Pexels for literal, Pollinations for abstract
# ------------------------------------------------------------------

def fetch_pexels_video(query: str, out_path: Path) -> Path | None:
    """Downloads a short vertical-friendly stock clip matching query."""
    headers = {"Authorization": PEXELS_API_KEY}
    url = "https://api.pexels.com/videos/search"
    params = {"query": query, "orientation": "portrait", "per_page": 5}

    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        return None

    # pick a random one of the top results so repeated topics don't
    # always reuse the exact same clip
    video = random.choice(videos[: min(3, len(videos))])
    # prefer a moderate-resolution vertical file
    files = sorted(video["video_files"], key=lambda f: f.get("width", 0))
    chosen = next((f for f in files if f.get("width", 0) >= 720), files[-1])

    video_data = requests.get(chosen["link"], timeout=30).content
    out_path.write_bytes(video_data)
    return out_path

def fetch_pollinations_image(prompt: str, out_path: Path) -> Path:
    """Free, no-key AI image generation for abstract concepts."""
    import urllib.parse
    encoded = urllib.parse.quote(prompt)
    # width/height tuned for vertical shorts
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return out_path

def fetch_visual_for_scene(scene: dict, index: int, run_dir: Path) -> dict:
    """Returns {'type': 'video'|'image', 'path': Path}."""
    if scene["visual_type"] == "literal":
        out_path = run_dir / f"visual_{index}.mp4"
        result = fetch_pexels_video(scene["visual_query"], out_path)
        if result:
            return {"type": "video", "path": result}
        # fall back to an AI image if Pexels has nothing usable
        fallback_path = run_dir / f"visual_{index}.jpg"
        fetch_pollinations_image(scene["visual_query"], fallback_path)
        return {"type": "image", "path": fallback_path}
    else:
        out_path = run_dir / f"visual_{index}.jpg"
        fetch_pollinations_image(scene["visual_query"], out_path)
        return {"type": "image", "path": out_path}

# ------------------------------------------------------------------
# 4. ASSEMBLY (moviepy) — sync each visual to its scene's audio length
# ------------------------------------------------------------------

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path) -> Path:
    from moviepy.editor import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_audioclips, concatenate_videoclips,
        CompositeAudioClip,
    )

    scene_clips = []

    for i, scene in enumerate(script["scenes"]):
        audio = AudioFileClip(str(audio_clips[i]["path"]))
        duration = audio.duration
        visual = visuals[i]

        if visual["type"] == "video":
            clip = VideoFileClip(str(visual["path"])).without_audio()
            # loop or trim to match narration duration
            if clip.duration < duration:
                clip = clip.loop(duration=duration)
            else:
                clip = clip.subclip(0, duration)
        else:
            clip = ImageClip(str(visual["path"])).set_duration(duration)

        clip = clip.resize(height=VIDEO_H).set_position("center")

        # simple caption burned onto each scene (swap for your existing
        # caption/text styling system if you already have one)
        caption = (
            TextClip(
                scene["narration"],
                fontsize=54,
                color="yellow",
                stroke_color="black",
                stroke_width=2,
                method="caption",
                size=(VIDEO_W - 120, None),
                align="center",
            )
            .set_position(("center", "center"))
            .set_duration(duration)
        )

        composite = CompositeVideoClip([clip, caption], size=(VIDEO_W, VIDEO_H))
        composite = composite.set_audio(audio)
        scene_clips.append(composite)

    final = concatenate_videoclips(scene_clips, method="compose")

    out_path = run_dir / "final_video.mp4"
    final.write_videofile(
        str(out_path), fps=30, codec="libx264", audio_codec="aac"
    )
    return out_path

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------

def run_pipeline():
    topic = get_next_topic()
    print(f"[1/4] Generating script for topic: {topic}")
    script = generate_script(topic)
    print(f"      Title: {script['title']}")

    run_dir = OUTPUT_DIR / script["title"].replace(" ", "_")[:40]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps(script, indent=2))

    print("[2/4] Synthesizing narration (Edge TTS)...")
    audio_clips = synthesize_scene_audio(script["scenes"], run_dir)

    print("[3/4] Fetching visuals (Pexels + Pollinations)...")
    visuals = [
        fetch_visual_for_scene(scene, i, run_dir)
        for i, scene in enumerate(script["scenes"])
    ]

    print("[4/5] Assembling final video...")
    final_path = build_video(script, audio_clips, visuals, run_dir)

    print("[5/5] Uploading to YouTube as unlisted + logging to dashboard...")
    description = (
        f"{script.get('hook', '')}\n\n"
        f"{' '.join(script['hashtags'])}"
    )
    upload_result = youtube_upload.upload_video(
        file_path=str(final_path),
        title=script["title"],
        description=description,
        tags=[h.replace("#", "") for h in script["hashtags"]],
        privacy_status="unlisted",  # previewable in the dashboard without login
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

    print(f"\nDone: {final_path}")
    print(f"YouTube (unlisted): https://youtu.be/{video_id}")
    print("Review and publish from the dashboard.")
    return final_path


if __name__ == "__main__":
    run_pipeline()
