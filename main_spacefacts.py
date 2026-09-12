"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab. Run cells top to bottom, or paste into
one cell and execute.

WHAT THIS DOES DIFFERENTLY (UPGRADED VERSION):
1. Script generates 6-10 short scenes (under 8 words each) for fast retention.
2. Implements a "Seamless Loop Hook" instead of a joke ending.
3. Edge TTS voice speed is boosted (+12%) for fast-paced shorts delivery.
4. Adds dynamic "Ken Burns" slow-zoom effects to static AI images.
5. AI Image prompts automatically appended with cinematic/high-quality tags.
6. Automatically mixes low-volume background music (BGM) if available.

REQUIRED INSTALLS (run first in Colab):
    !pip install google-generativeai edge-tts moviepy pillow requests --quiet
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

# Create BGM directory. Drop ambient .mp3 tracks in here!
BGM_DIR = Path("bgm")
BGM_DIR.mkdir(exist_ok=True) 

VIDEO_W, VIDEO_H = 1080, 1920  # vertical shorts

# Rotate between a small, consistent set of Edge TTS voices.
TTS_VOICES = [
    "en-US-GuyNeural",       # calm male
    "en-GB-RyanNeural",      # measured British male
    "en-US-JennyNeural",     # warm female, explainer tone
    "en-AU-WilliamNeural",   # relaxed Australian male
]

# EXPANDED TOPIC POOL (Optimized for extreme scale, danger, and mystery)
TOPIC_POOL = [
    # space / physics
    "what actually happens if a massive solar flare hits Earth today",
    "the horrifying distance between Earth and the nearest black hole",
    "why rogue planets drifting in pitch dark space are so dangerous",
    "how long a human could survive on the surface of Venus",
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
    # sea / ocean / earth
    "what scientists found inside the deepest hole ever drilled on Earth",
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
# STATE HANDLING 
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
# 1. SCRIPT GENERATION (Gemini) — Scene-segmented, Loop Hooks
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about a space/physics fact OR a sea/ocean fact.

Rules for how it should sound:
- Write like you're explaining something wild to a friend, not narrating a documentary.
- Use contractions (it's, you'd, that's, don't).
- Do NOT use rhetorical filler like "this isn't science fiction, it's reality."
- Do NOT stack intensifiers (incredibly, absolutely, insanely). Pick ONE strong word max per sentence.
- Keep each scene's narration SHORT — ideally under 8 words. 
- Create exactly 6 to 10 scenes per video so visuals and text change rapidly every 1.5–2.5 seconds.
- DO NOT end with a joke, pun, summary, or closing statement.
- The FINAL scene MUST end mid-thought or lead seamlessly into the very first word of the script/title so that the video loops endlessly.
  Example Loop: 
  First Scene: "...is why you can never touch a black hole."
  Final Scene: "And that terrifying reality..." -> (Loops back to First)

For each scene, provide a visual:
- visual_type: "literal" (real stock footage exists, e.g. a dam, the ISS, a person walking)
- visual_type: "abstract" (concept with no real footage, e.g. time dilation, event horizon)
- visual_query: for "literal", a 3-6 word stock footage search term. For "abstract", a descriptive AI image generation prompt.

Return ONLY valid JSON, no markdown fences, no commentary, in this exact shape:

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
    model = genai.GenerativeModel("gemini-1.5-flash") # Updated model reference

    prompt = SCRIPT_SYSTEM_PROMPT.replace("{topic}", topic)
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )

    data = json.loads(response.text)

    assert "scenes" in data and len(data["scenes"]) > 0, "No scenes returned"
    for scene in data["scenes"]:
        assert scene["visual_type"] in ("literal", "abstract")

    return data

# ------------------------------------------------------------------
# 2. NARRATION (Edge TTS) — Faster pacing for shorts
# ------------------------------------------------------------------

async def _synthesize(text: str, voice: str, out_path: Path):
    import edge_tts
    # Added rate='+12%' for punchier short-form delivery
    communicate = edge_tts.Communicate(text, voice, rate="+12%")
    await communicate.save(str(out_path))

def synthesize_scene_audio(scenes: list, run_dir: Path) -> list:
    from moviepy import AudioFileClip

    voice = random.choice(TTS_VOICES)
    results = []

    for i, scene in enumerate(scenes):
        out_path = run_dir / f"scene_{i}.mp3"
        asyncio.run(_synthesize(scene["narration"], voice, out_path))
        duration = AudioFileClip(str(out_path)).duration
        results.append({"path": out_path, "duration": duration})

    return results

# ------------------------------------------------------------------
# 3. VISUALS — Cinematic prompt enhancement for AI
# ------------------------------------------------------------------

def fetch_pexels_video(query: str, out_path: Path) -> Path | None:
    headers = {"Authorization": PEXELS_API_KEY}
    url = "https://api.pexels.com/videos/search"
    params = {"query": query, "orientation": "portrait", "per_page": 5}

    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        return None

    video = random.choice(videos[: min(3, len(videos))])
    files = sorted(video["video_files"], key=lambda f: f.get("width", 0))
    chosen = next((f for f in files if f.get("width", 0) >= 720), files[-1])

    video_data = requests.get(chosen["link"], timeout=30).content
    out_path.write_bytes(video_data)
    return out_path

def fetch_pollinations_image(prompt: str, out_path: Path) -> Path:
    import urllib.parse
    # Automatically boost AI image quality with cinematic modifiers
    enhanced_prompt = f"{prompt}, cinematic lighting, photorealistic, 8k, hyperdetailed, dark atmosphere, space documentary style"
    encoded = urllib.parse.quote(enhanced_prompt)
    
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return out_path

def fetch_visual_for_scene(scene: dict, index: int, run_dir: Path) -> dict:
    if scene["visual_type"] == "literal":
        out_path = run_dir / f"visual_{index}.mp4"
        result = fetch_pexels_video(scene["visual_query"], out_path)
        if result:
            return {"type": "video", "path": result}
        
        fallback_path = run_dir / f"visual_{index}.jpg"
        fetch_pollinations_image(scene["visual_query"], fallback_path)
        return {"type": "image", "path": fallback_path}
    else:
        out_path = run_dir / f"visual_{index}.jpg"
        fetch_pollinations_image(scene["visual_query"], out_path)
        return {"type": "image", "path": out_path}

# ------------------------------------------------------------------
# 4. ASSEMBLY (moviepy) — Ken Burns zoom & BGM mixing
# ------------------------------------------------------------------

def apply_ken_burns(clip, duration, zoom_ratio=0.08):
    """Adds a dynamic slow-zoom effect to static images."""
    from moviepy import vfx
    return clip.with_effects([
        vfx.Resize(lambda t: 1 + (zoom_ratio * (t / duration)))
    ])

def add_background_music(final_clip, bgm_folder=Path("bgm")):
    """Layers low-volume ambient music if available."""
    from moviepy import AudioFileClip, CompositeAudioClip, vfx
    bgm_files = list(bgm_folder.glob("*.mp3"))
    if not bgm_files:
        return final_clip
    
    bgm_path = random.choice(bgm_files)
    bgm = AudioFileClip(str(bgm_path))
    
    # Loop BGM if shorter than final video, else trim it
    if bgm.duration < final_clip.duration:
        bgm = bgm.with_effects([vfx.Loop(duration=final_clip.duration)])
    else:
        bgm = bgm.subclipped(0, final_clip.duration)
        
    # Set background music volume low (12% of original)
    bgm = bgm.with_effects([vfx.MultiplyVolume(0.12)])
    
    combined_audio = CompositeAudioClip([final_clip.audio, bgm])
    return final_clip.with_audio(combined_audio)

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx,
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
            base_clip = ImageClip(str(visual["path"])).with_duration(duration)
            clip = apply_ken_burns(base_clip, duration)

        clip = clip.with_effects([vfx.Resize(height=VIDEO_H)]).with_position("center")

        # Captions will now be fast, 2-4 word bursts
        caption = TextClip(
            text=scene["narration"],
            font_size=62, # Slightly larger for shorter bursts
            color="yellow",
            stroke_color="black",
            stroke_width=2.5,
            method="caption",
            size=(VIDEO_W - 120, None),
            text_align="center",
            duration=duration,
        ).with_position(("center", "center"))

        composite = CompositeVideoClip([clip, caption], size=(VIDEO_W, VIDEO_H))
        composite = composite.with_audio(audio)
        scene_clips.append(composite)

    final = concatenate_videoclips(scene_clips, method="compose")
    
    # Mix in background music automatically
    final = add_background_music(final, BGM_DIR)

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

    run_dir = OUTPUT_DIR / script["title"].replace(" ", "_").replace("/", "")[:40]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps(script, indent=2))

    print("[2/4] Synthesizing narration (Edge TTS, boosted pacing)...")
    audio_clips = synthesize_scene_audio(script["scenes"], run_dir)

    print("[3/4] Fetching visuals (Pexels + Cinematic Pollinations)...")
    visuals = [
        fetch_visual_for_scene(scene, i, run_dir)
        for i, scene in enumerate(script["scenes"])
    ]

    print("[4/5] Assembling final video (Applying Ken Burns & BGM)...")
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

    print(f"\nDone: {final_path}")
    print(f"YouTube (unlisted): https://youtu.be/{video_id}")
    print("Review and publish from the dashboard.")
    return final_path


if __name__ == "__main__":
    run_pipeline()
