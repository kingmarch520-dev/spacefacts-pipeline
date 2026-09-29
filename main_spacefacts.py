"""
==================================================================
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v2, lean)
==================================================================
Runs on a schedule via GitHub Actions, or by hand anywhere with
Python. One run: pick a topic, write a script with Gemini, narrate
it with Edge TTS, source visuals from Pexels/Pollinations, assemble
the video with moviepy, upload it to YouTube as public.

WHY THIS IS A SEPARATE, FRESH FILE
No Supabase, no dashboard, no review queue — everything just goes
public. Only two topic lanes: space and history. State (which
topics have been used, recent titles) lives in a local JSON file
committed back to the repo after each run, same as before.

WHAT'S KEPT FROM THE OLD PIPELINE
- Per-category round robin with a shuffled order each full pass, so
  a topic never repeats until every topic in its lane has been used.
- Last 40 titles fed into the script prompt so new videos don't read
  like a repeat of a recent one.
- Hook patterns and ending styles ("loop" / "joke") in the prompt.
- Retry with backoff on Gemini, Pexels, Pollinations — quota errors
  from Gemini fail fast instead of wasting retries on a wall that
  won't clear for minutes.
- Pollinations falls back to a locally drawn placeholder image if it
  keeps failing, so a flaky free service can't kill a whole run.
- Optional background music from a "bgm" folder.
- Multilingual Edge TTS voices, picked for sounding less robotic.

WHAT'S DROPPED
- Supabase entirely — no video log, no performance-based weighting.
  Category odds are just fixed below; edit them by hand as you learn
  which lane performs better in YouTube Studio.
- The webapp/dashboard — unused, so it's not part of this repo.
- Ocean and bible lanes — this channel is space + history only now.

REQUIRED INSTALLS
    pip install google-generativeai edge-tts moviepy pillow requests

REQUIRED ENV VARS
    GEMINI_API_KEY, PEXELS_API_KEY,
    YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

REQUIRED FILES IN THIS REPO (same folder as this script)
    Anton-Regular.ttf   — caption font (moviepy 2.x has no default)
    bgm/*.mp3           — optional, royalty-free background tracks
==================================================================
"""

import os
import json
import random
import asyncio
import requests
from pathlib import Path

import youtube_upload

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "PASTE_YOUR_KEY_HERE")

STATE_FILE = Path("state_spacefacts.json")
UPLOAD_LOG_FILE = Path("upload_log.jsonl")
OUTPUT_DIR = Path("output_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)

VIDEO_W, VIDEO_H = 1080, 1920  # vertical shorts

CAPTION_FONT_PATH = str(Path(__file__).parent / "Anton-Regular.ttf")
BGM_DIR = Path(__file__).parent / "bgm"

# Fixed odds per lane. Space led slightly in early data on the old
# pipeline; history is unproven here since it's a fresh channel
# focus. Adjust by hand once you have real numbers in Studio.
CATEGORY_WEIGHTS = {
    "space": 0.55,
    "history": 0.45,
}

TTS_VOICES = [
    "en-GB-RyanNeural",              # widely regarded as one of the
                                      # least robotic standard voices
    "en-US-EmmaMultilingualNeural",  # newer "Multilingual" model —
                                      # noticeably more natural
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]

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

def get_category_topics(category: str) -> list:
    return [t for t in TOPIC_POOL if t["category"] == category]

def get_next_topic():
    """Per-category round robin: each lane tracks its own position and
    gets a freshly shuffled order every time it completes a full pass,
    so a topic never repeats until every topic in that lane has been
    used once."""
    state = load_state()
    state.setdefault("category_progress", {})

    categories = list(CATEGORY_WEIGHTS.keys())
    weights = [CATEGORY_WEIGHTS[c] for c in categories]
    chosen_category = random.choices(categories, weights=weights, k=1)[0]

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
    """Keeps the last 40 titles so the script prompt can steer away
    from producing something that reads like a recent repeat."""
    state = load_state()
    recent = state.get("recent_titles", [])
    recent.append(title)
    state["recent_titles"] = recent[-40:]
    save_state(state)

def get_recent_titles() -> list:
    return load_state().get("recent_titles", [])

def log_upload(video_id: str, title: str, category: str, ending_style: str):
    """Plain local log, one JSON line per upload — replaces Supabase.
    Not queried by anything; it's just a record you can grep through
    or open in a text editor if you want to see upload history."""
    entry = {
        "video_id": video_id,
        "title": title,
        "category": category,
        "ending_style": ending_style,
        "url": f"https://youtu.be/{video_id}",
    }
    with open(UPLOAD_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

# ------------------------------------------------------------------
# RETRY HELPER
# ------------------------------------------------------------------

def retry_with_backoff(fn, *args, retries=3, base_delay=3, should_retry=None, **kwargs):
    """Retries fn() with exponential backoff (3s, 6s, 12s by default).
    should_retry(exception) -> bool lets a caller skip retries entirely
    for errors that won't be fixed by waiting a few seconds (e.g. a
    per-minute rate limit) — without this, a single rate-limited call
    would burn all `retries` attempts against the same quota window."""
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

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION (Gemini)
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about one of: a space/physics fact, or a strange piece of real history.

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
     a mental reference for. This is the strongest pattern:
     e.g. "We built something colder than deep space."
  2. Lead with a specific number or stat before any setup:
     e.g. "One teaspoon of this would weigh six billion tons."
  3. Direct address framed as a personal stake:
     e.g. "You wouldn't even last one second down there."
  4. False premise, immediate correction:
     e.g. "Everyone thinks space is empty. It's not even close."
  5. Blunt, ominous fact fragment, no lead-in at all:
     e.g. "This star could swallow our entire solar system."
Prefer pattern 1 when a genuinely apt comparison exists for the topic.
Do NOT use generic hook filler like "did you know" or "here's a fact
that will blow your mind."

ENDING — follow whichever style is set above:
- If ending_style is "loop": the FINAL scene must end mid-thought or
  lead seamlessly into the very first word of the hook, so the video
  loops endlessly with no visible seam. No joke, no summary, no moral.
  Example: hook is "...is why you can never touch a black hole." ->
  final scene is "And that terrifying reality..." (loops back to hook).
- If ending_style is "joke": the FINAL scene must be a short joke or
  pun directly related to the fact — one line, genuinely funny, not a
  generic "dad joke for the sake of it." It should feel like a natural
  button on the video. If a clean pun exists in the topic, prefer that
  over a generic joke.

TITLE — use a curiosity-gap framing, not a flat description:
  Weak:  "Facts About Ancient Rome"
  Strong: "The Roman Concrete Recipe Modern Engineers Still Can't Match"
Under 60 characters. No clickbait that isn't actually true.

Favor plain, dry, factual phrasing over dramatic adjectives. Avoid
words like "terrifying," "insane," "shocking" in the title itself
(they're fine sparingly in narration, just not as the title's hook).

Break the script into scenes. Each scene is one or two sentences of
narration, including the final scene. For each scene, also provide
a visual:
- visual_type: "literal" if real stock footage of this exists
  (e.g. a dam, the ISS, a starfield, a person walking, ancient ruins)
- visual_type: "abstract" if it's a concept with no real footage
  (e.g. gravitational time dilation, a wormhole cross-section)
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt (can be
  longer, be specific and cinematic).
- For a "joke" ending, pick whichever visual actually supports the
  punchline.

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
        return not any(marker in msg for marker in ("RESOURCE_EXHAUSTED", "429", "quota"))

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
    """Verifies the response is actually an image before saving, so a
    rate-limit/error page from Pollinations can't silently become a
    corrupt "image" file that only fails much later in moviepy."""
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
    """Last-resort visual when Pollinations fails after all retries —
    a simple dark gradient card with the concept text overlaid,
    rendered locally with no network call, so the scene still has
    something on screen instead of crashing the whole run."""
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
        (80, VIDEO_H // 2 - 150), wrapped, fill=(220, 220, 220), font=font, spacing=16
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
    """Mixes a random track from BGM_DIR in at low volume under the
    narration. No files in BGM_DIR = clip returned unchanged."""
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
            "Make sure Anton-Regular.ttf is committed to the repo root, "
            "next to this script."
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
    final.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac")
    return out_path

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------

def run_pipeline():
    topic_entry = get_next_topic()
    topic = topic_entry["topic"]
    category = topic_entry["category"]
    ending_style = random.choice(["loop", "joke"])

    print(f"[1/5] Generating script for topic: {topic} (category={category}, ending={ending_style})")
    recent_titles = get_recent_titles()
    script = generate_script(topic, ending_style, recent_titles=recent_titles)
    print(f"      Title: {script['title']}")
    record_used_title(script["title"])

    run_dir = OUTPUT_DIR / script["title"].replace(" ", "_")[:40]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps(script, indent=2))

    print("[2/5] Synthesizing narration (Edge TTS)...")
    audio_clips = synthesize_scene_audio(script["scenes"], run_dir)

    print("[3/5] Fetching visuals (Pexels + Pollinations)...")
    visuals = [
        fetch_visual_for_scene(scene, i, run_dir)
        for i, scene in enumerate(script["scenes"])
    ]

    print("[4/5] Assembling final video...")
    final_path = build_video(script, audio_clips, visuals, run_dir)

    print("[5/5] Uploading to YouTube as public...")
    description = f"{script.get('hook', '')}\n\n{' '.join(script['hashtags'])}"
    upload_result = youtube_upload.upload_video(
        file_path=str(final_path),
        title=script["title"],
        description=description,
        tags=[h.replace("#", "") for h in script["hashtags"]],
        privacy_status="public",
    )
    video_id = upload_result["id"]
    log_upload(video_id, script["title"], category, ending_style)

    print(f"\nDone: {final_path}")
    print(f"YouTube: https://youtu.be/{video_id}")
    return final_path


if __name__ == "__main__":
    run_pipeline()
