"""
==================================================================
SPACE/PHYSICS & SCIENCE CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab. Run cells top to bottom, or paste into
one cell and execute.

UPDATES IN THIS VERSION:
- Removed the Bible category entirely.
- Re-weighted category selection across Space, Ocean, and History.
- Preserved all recent retention updates (loop/joke endings, 40-title 
  memory, improved TTS voices, fallback handling, and robust retries).
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

# Background music: drop royalty-free instrumental .mp3 files in a
# folder called "bgm" at the repo root (same level as this script).
BGM_DIR = Path(__file__).parent / "bgm"

VIDEO_W, VIDEO_H = 1080, 1920  # vertical shorts

# moviepy 2.x TextClip has no built-in font fallback
CAPTION_FONT_PATH = str(Path(__file__).parent / "Anton-Regular.ttf")

# Rotate between a small, consistent set of Edge TTS voices.
TTS_VOICES = [
    "en-GB-RyanNeural",              
    "en-US-EmmaMultilingualNeural",  
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]

# Seeded performance weights across your 3 active lanes:
FALLBACK_CATEGORY_WEIGHTS = {
    "space": 0.40,
    "ocean": 0.30,
    "history": 0.30,
}

# Odds that a given run's video is uploaded as public instead of unlisted.
PUBLIC_PUBLISH_CHANCE = 1.0

MANUAL_PERFORMANCE_LOG = [
    # {"title": "...", "category": "space", "views": 1700},
]

# Three focused lanes: space/physics, sea/ocean, and history.
TOPIC_POOL = [
    {"topic": "gravitational time dilation near a black hole", "category": "space"},
    {"topic": "what a neutron star's density actually means", "category": "space"},
    {"topic": "why the observable universe has an edge", "category": "space"},
    {"topic": "spaghettification near a black hole's event horizon", "category": "space"},
    {"topic": "how fast the Milky Way is actually moving", "category": "space"},
    {"topic": "what would happen if you fell into a wormhole", "category": "space"},
    {"topic": "why space is completely silent", "category": "space"},
    {"topic": "how close we've actually gotten to absolute zero", "category": "space"},
    {"topic": "the size of the largest known star compared to the sun", "category": "space"},
    {"topic": "why time moves slower for astronauts on the ISS", "category": "space"},
    {"topic": "what dark matter actually does to galaxies", "category": "space"},
    {"topic": "how a supernova could theoretically threaten Earth", "category": "space"},
    {"topic": "why Jupiter's Great Red Spot has lasted for centuries", "category": "space"},
    {"topic": "what a rogue planet drifting with no star actually looks like", "category": "space"},
    {"topic": "how astronauts' bodies actually change after months in orbit", "category": "space"},
    {"topic": "why Venus spins backward compared to almost every other planet", "category": "space"},
    {"topic": "what would really happen if the sun vanished for one second", "category": "space"},
    {"topic": "how close the nearest black hole actually is to Earth", "category": "space"},
    {"topic": "how big the largest known structure in the entire universe actually is", "category": "space"},
    {"topic": "how much of the periodic table can only be made inside a dying star", "category": "space"},
    {"topic": "how little of the ocean floor has actually been mapped", "category": "ocean"},
    {"topic": "the crushing pressure at the bottom of the Mariana Trench", "category": "ocean"},
    {"topic": "why the deep ocean is in permanent total darkness", "category": "ocean"},
    {"topic": "how much of Earth's oxygen actually comes from the ocean", "category": "ocean"},
    {"topic": "what lives in hydrothermal vents with no sunlight at all", "category": "ocean"},
    {"topic": "how big the largest recorded giant squid actually was", "category": "ocean"},
    {"topic": "why most of the ocean is still completely unexplored", "category": "ocean"},
    {"topic": "how deep sunlight actually stops reaching underwater", "category": "ocean"},
    {"topic": "what happens to a human body at extreme ocean depth", "category": "ocean"},
    {"topic": "how old the oldest living sea creature actually is", "category": "ocean"},
    {"topic": "why bioluminescence exists in deep sea animals", "category": "ocean"},
    {"topic": "how massive a blue whale's heart actually is", "category": "ocean"},
    {"topic": "why some deep sea fish can survive being frozen solid", "category": "ocean"},
    {"topic": "how a single drop of seawater can contain millions of microorganisms", "category": "ocean"},
    {"topic": "why the ocean's color actually changes with depth the way it does", "category": "ocean"},
    {"topic": "how sound travels four times faster underwater than in air", "category": "ocean"},
    {"topic": "what the 'twilight zone' of the ocean actually looks like", "category": "ocean"},
    {"topic": "how a shipwreck actually becomes an artificial reef over time", "category": "ocean"},
    {"topic": "why some ocean currents are strong enough to move entire islands of debris", "category": "ocean"},
    {"topic": "how deep-diving whales survive water pressure that would crush a submarine", "category": "ocean"},
    {"topic": "how the Antikythera mechanism baffled experts for a century", "category": "history"},
    {"topic": "how the pyramids at Giza were actually built without modern tools", "category": "history"},
    {"topic": "what really happened to the Library of Alexandria", "category": "history"},
    {"topic": "why the Voynich manuscript still hasn't been decoded", "category": "history"},
    {"topic": "how an entire Roman legion vanished without a trace", "category": "history"},
    {"topic": "what the Baghdad Battery might have actually been used for", "category": "history"},
    {"topic": "how ancient Rome's concrete outlasts modern concrete", "category": "history"},
    {"topic": "what the Dancing Plague of 1518 actually did to people", "category": "history"},
    {"topic": "how the Bronze Age Collapse wiped out multiple civilizations at once", "category": "history"},
    {"topic": "what really caused the Tunguska explosion", "category": "history"},
    {"topic": "how the Nazca Lines were made without ever being seen from above", "category": "history"},
    {"topic": "what happened to the lost colony of Roanoke", "category": "history"},
    {"topic": "how the Iron Pillar of Delhi has resisted rust for over 1,600 years", "category": "history"},
    {"topic": "why the Sutton Hoo ship burial rewrote what historians knew about early England", "category": "history"},
    {"topic": "what the Rosetta Stone actually took decades to fully decode", "category": "history"},
    {"topic": "how Greek fire's exact recipe was lost to history forever", "category": "history"},
    {"topic": "why the city of Petra was carved directly into solid rock", "category": "history"},
    {"topic": "how the Terracotta Army was hidden and undiscovered for over 2,000 years", "category": "history"},
    {"topic": "what really caused the sudden collapse of the Maya civilization", "category": "history"},
    {"topic": "why the Phaistos Disc's symbols still can't be translated", "category": "history"},
]

# ------------------------------------------------------------------
# STATE HANDLING
# ------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"category_progress": {}, "recent_titles": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def get_category_weights():
    categories = {t["category"] for t in TOPIC_POOL}
    try:
        rows = supabase_client.get_video_performance()
        if not rows:
            raise ValueError("no performance data yet")

        totals = {cat: 0 for cat in categories}
        counts = {cat: 0 for cat in categories}
        for row in rows:
            cat = row.get("category")
            views = row.get("views")
            if cat in totals and isinstance(views, (int, float)):
                totals[cat] += views
                counts[cat] += 1

        avgs = {
            cat: (totals[cat] / counts[cat] if counts[cat] > 0 else 0)
            for cat in totals
        }
        total_avg = sum(avgs.values())
        if total_avg <= 0:
            raise ValueError("no usable view data yet")

        return {cat: avgs[cat] / total_avg for cat in avgs}
    except Exception as e:
        print(f"      (topic weighting fallback to seeded defaults — {e})")
        return {
            cat: FALLBACK_CATEGORY_WEIGHTS.get(cat, 1.0 / len(categories))
            for cat in categories
        }

def log_manual_performance():
    if not MANUAL_PERFORMANCE_LOG:
        print("MANUAL_PERFORMANCE_LOG is empty — nothing to log.")
        return
    for entry in MANUAL_PERFORMANCE_LOG:
        supabase_client.upsert_video_performance(
            title=entry["title"],
            category=entry["category"],
            views=entry["views"],
        )
    print(f"Logged {len(MANUAL_PERFORMANCE_LOG)} manual performance entries.")

def get_category_topics(category: str) -> list:
    return [t for t in TOPIC_POOL if t["category"] == category]

def get_next_topic():
    state = load_state()
    state.setdefault("category_progress", {})

    weights = get_category_weights()
    chosen_category = random.choices(
        population=list(weights.keys()),
        weights=list(weights.values()),
        k=1,
    )[0]

    category_topics = get_category_topics(chosen_category)
    progress = state["category_progress"].get(chosen_category)

    if not progress or progress["position"] >= len(progress["order"]):
        order = list(range(len(category_topics)))
        random.shuffle(order)
        progress = {"order": order, "position": 0}

    topic_index = progress["order"][progress["position"]]
    topic_entry = category_topics[topic_index]

    progress["position"] += 1
    state["category_progress"][chosen_category] = progress
    save_state(state)
    return topic_entry

def record_used_title(title: str):
    state = load_state()
    recent = state.get("recent_titles", [])
    recent.append(title)
    state["recent_titles"] = recent[-40:]
    save_state(state)

def get_recent_titles() -> list:
    return load_state().get("recent_titles", [])

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION (Gemini)
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about one of: a space/physics fact, a sea/ocean fact, or a strange piece
of real history.

ENDING STYLE FOR THIS SCRIPT: {ending_style}

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
- Deliver the core fact clearly before the final scene.

HOOK (the very first scene's narration) — use ONE of these patterns,
whichever fits the topic best. The hook must work in 2-3 seconds:
  1. Compare the extreme to something ordinary the viewer already has
     a mental reference for.
  2. Lead with a specific number or stat before any setup.
  3. Direct address framed as a personal stake.
  4. False premise, immediate correction.
  5. Blunt, ominous fact fragment, no lead-in at all.
Prefer pattern 1 when a genuinely apt comparison exists for the topic.
Do NOT use generic hook filler like "did you know" or "here's a fact
that will blow your mind."

ENDING — follow whichever style is set above:
- If ending_style is "loop": the FINAL scene must end mid-thought or
  lead seamlessly into the very first word of the hook, so the video
  loops endlessly with no visible seam. No joke, no summary, no moral.
- If ending_style is "joke": the FINAL scene must be a short joke or
  pun directly related to the fact — one line, genuinely funny, not a
  generic "dad joke for the sake of it."

TITLE — use a curiosity-gap framing, not a flat description.
Under 60 characters. No clickbait that isn't actually true.
Favor plain, dry, factual phrasing over dramatic adjectives.

Break the script into scenes. Each scene is one or two sentences of
narration, including the final scene. For each scene, also provide
a visual:
- visual_type: "literal" if real stock footage of this exists
- visual_type: "abstract" if it's a concept with no real footage
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt.

Return ONLY valid JSON, no markdown fences, no commentary, in this
exact shape:

{{
  "title": "short punchy YouTube title, under 60 characters",
  "hook": "the first scene's narration — must stop the scroll in 2-3 seconds",
  "scenes": [
    {{
      "narration": "...",
      "visual_type": "literal",
      "visual_query": "..."
    }}
  ],
  "hashtags": ["#shorts", "#space", "#facts"]
}}

Topic: {topic}

{recent_titles_block}
"""

def generate_script(topic: str, ending_style: str, recent_titles: list = None) -> dict:
    if recent_titles:
        titles_list = "\n".join(f"- {t}" for t in recent_titles)
        recent_titles_block = (
            "AVOID RESEMBLING RECENT VIDEOS — these titles were made recently "
            "on this channel. Even if today's topic is technically different, "
            "do not produce a hook, angle, or framing that would feel like a "
            "repeat of any of these to a viewer who's seen them:\n" + titles_list
        )
    else:
        recent_titles_block = ""

    prompt = SCRIPT_SYSTEM_PROMPT.format(
        topic=topic,
        ending_style=ending_style,
        recent_titles_block=recent_titles_block,
    )

    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")

    def _call_gemini():
        return model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )

    def _is_transient_gemini_error(e) -> bool:
        msg = str(e)
        return not any(
            marker in msg
            for marker in ("RESOURCE_EXHAUSTED", "429", "quota")
        )

    response = retry_with_backoff(
        _call_gemini, retries=3, base_delay=5, should_retry=_is_transient_gemini_error
    )

    data = json.loads(response.text)

    assert "scenes" in data and len(data["scenes"]) > 0, "No scenes returned"
    for scene in data["scenes"]:
        assert scene["visual_type"] in ("literal", "abstract")

    return data

# ------------------------------------------------------------------
# 2. NARRATION (Edge TTS)
# ------------------------------------------------------------------

async def _synthesize(text: str, voice: str, out_path: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
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
# 3. VISUALS — Pexels for literal, Pollinations for abstract
# ------------------------------------------------------------------

def retry_with_backoff(fn, *args, retries=3, base_delay=3, should_retry=None, **kwargs):
    import time
    last_exc = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if should_retry is not None and not should_retry(e):
                print(f"      (not retrying — error isn't transient: {e})")
                raise
            if attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"      (retrying after error: {e} — waiting {delay}s)")
                time.sleep(delay)
    raise last_exc

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

def _fetch_pollinations_image_once(prompt: str, out_path: Path) -> Path:
    import urllib.parse
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"

    r = requests.get(url, timeout=60)
    r.raise_for_status()

    content_type = r.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise RuntimeError(
            f"Pollinations did not return an image for prompt "
            f"'{prompt[:60]}...' (content-type: {content_type})"
        )

    out_path.write_bytes(r.content)
    return out_path

def _generate_fallback_image(prompt: str, out_path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

    img = Image.new("RGB", (VIDEO_W, VIDEO_H), color=(10, 10, 20))
    draw = ImageDraw.Draw(img)

    for y in range(VIDEO_H):
        shade = int(10 + (y / VIDEO_H) * 40)
        draw.line([(0, y), (VIDEO_W, y)], fill=(shade, shade, shade + 15))

    try:
        font = ImageFont.truetype(CAPTION_FONT_PATH, 60)
    except Exception:
        font = ImageFont.load_default()

    wrapped = textwrap.fill(prompt, width=28)
    draw.multiline_text(
        (80, VIDEO_H // 2 - 150),
        wrapped,
        fill=(220, 220, 220),
        font=font,
        spacing=16,
    )

    img.save(out_path)
    return out_path

def fetch_pollinations_image(prompt: str, out_path: Path) -> Path:
    try:
        return retry_with_backoff(_fetch_pollinations_image_once, prompt, out_path)
    except Exception as e:
        print(f"      (Pollinations failed after retries — using fallback image: {e})")
        return _generate_fallback_image(prompt, out_path)

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
# 4. ASSEMBLY (moviepy)
# ------------------------------------------------------------------

def add_background_music(final_clip):
    from moviepy import AudioFileClip, CompositeAudioClip, afx

    if not BGM_DIR.exists():
        return final_clip

    bgm_files = list(BGM_DIR.glob("*.mp3"))
    if not bgm_files:
        return final_clip

    bgm_path = random.choice(bgm_files)
    bgm = AudioFileClip(str(bgm_path))

    if bgm.duration < final_clip.duration:
        bgm = bgm.with_effects([afx.AudioLoop(duration=final_clip.duration)])
    else:
        bgm = bgm.subclipped(0, final_clip.duration)

    bgm = bgm.with_effects([afx.MultiplyVolume(0.10)])

    combined_audio = CompositeAudioClip([final_clip.audio, bgm])
    return final_clip.with_audio(combined_audio)

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx,
    )

    if not Path(CAPTION_FONT_PATH).exists():
        raise FileNotFoundError(
            f"CAPTION_FONT_PATH does not exist: {CAPTION_FONT_PATH}. "
            "Make sure Anton-Regular.ttf is committed to the repo root."
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

        clip = clip.with_effects([vfx.Resize(height=VIDEO_H)]).with_position("center")

        caption = TextClip(
            font=CAPTION_FONT_PATH,
            text=scene["narration"],
            font_size=54,
            color="yellow",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(VIDEO_W - 120, None),
            text_align="center",
            duration=duration,
        ).with_position(("center", "center"))

        composite = CompositeVideoClip([clip, caption], size=(VIDEO_W, VIDEO_H))
        composite = composite.with_audio(audio)
        scene_clips.append(composite)

    final = concatenate_videoclips(scene_clips, method="compose")
    final = add_background_music(final)

    out_path = run_dir / "final_video.mp4"
    final.write_videofile(
        str(out_path), fps=30, codec="libx264", audio_codec="aac"
    )
    return out_path

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------

def run_pipeline():
    topic_entry = get_next_topic()
    topic = topic_entry["topic"]
    category = topic_entry["category"]

    ending_style = random.choice(["loop", "joke"])

    print(f"[1/4] Generating script for topic: {topic} (category={category}, ending={ending_style})")
    recent_titles = get_recent_titles()
    script = generate_script(topic, ending_style, recent_titles=recent_titles)
    print(f"      Title: {script['title']}")
    record_used_title(script["title"])

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

    privacy_status = "public" if random.random() < PUBLIC_PUBLISH_CHANCE else "unlisted"

    print(f"[5/5] Uploading to YouTube as {privacy_status} + logging to dashboard...")
    description = (
        f"{script.get('hook', '')}\n\n"
        f"{' '.join(script['hashtags'])}"
    )
    upload_result = youtube_upload.upload_video(
        file_path=str(final_path),
        title=script["title"],
        description=description,
        tags=[h.replace("#", "") for h in script["hashtags"]],
        privacy_status=privacy_status,
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
        status=privacy_status,
    )

    print(f"\nDone: {final_path}")
    print(f"YouTube ({privacy_status}): https://youtu.be/{video_id}")
    print("Review and publish from the dashboard.")
    return final_path


if __name__ == "__main__":
    run_pipeline()
