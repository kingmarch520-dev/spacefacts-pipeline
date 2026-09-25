"""
==================================================================
SPACE/OCEAN FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab. Run cells top to bottom, or paste into
one cell and execute.

CHANGES IN THIS VERSION (view-maximizing rethink):
1. Narrowed from 4 categories to 2: space and ocean only. History
   and bible had zero appearances in the channel's top 10 videos
   by view count — cut to concentrate the reduced upload volume
   (see #2) on what's actually working.
2. Upload frequency cut from 6/day to 2/day (see workflow YAML).
3. category and ending_style are now actually logged to Supabase
   (requires supabase_client.log_video() to accept these kwargs —
   already updated separately). Previously these were tracked
   locally and printed but never persisted, so get_category_weights()
   and the loop-vs-joke A/B test could never learn from real data.
4. Captions switched from static full-sentence blocks to word-by-word
   highlighted ("karaoke") captions, timed proportionally by
   character length within each scene's audio duration.
5. Added an optional comment-bait CTA rule for "joke" endings.
6. Added a trailing-silence trim on each scene's narration audio so
   dead air doesn't stretch out that scene's visual duration.
7. TOPIC_POOL trimmed to space/ocean only.
8. ALREADY_COVERED_TOPICS excludes the handful of topics that had
   videos made under the old system, before this file's round-robin
   state tracking existed — so the pipeline doesn't regenerate a
   video on a subject already posted. TOPIC_POOL is meant to be
   expanded to ~500 entries (generate in bulk with Gemini/AI Studio
   rather than by hand — see the comment above TOPIC_POOL below) so
   collisions become vanishingly unlikely on their own; the exclusion
   list stays anyway as a one-time cleanup for what's already posted.

Everything else (hook patterns, per-category round-robin, retry/
backoff logic, Pollinations fallback, background music, TTS voice
rotation) is unchanged from the prior version.

REQUIRED INSTALLS (run first in Colab, and keep your GitHub Actions
workflow's pip install line in sync):
    !pip install google-generativeai edge-tts moviepy pillow requests numpy --quiet

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

BGM_DIR = Path(__file__).parent / "bgm"

VIDEO_W, VIDEO_H = 1080, 1920  # vertical shorts

CAPTION_FONT_PATH = str(Path(__file__).parent / "Anton-Regular.ttf")

TTS_VOICES = [
    "en-GB-RyanNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]

# Seeded from your actual YouTube Studio "Top content" numbers
# (28-day window, 15 Aug - 11 Sept 2026): space ~1,158 avg views,
# ocean ~1,035 avg — a real but modest ~12% lean. Used only until
# Supabase has real per-video view data logged (via
# log_manual_performance()), at which point get_category_weights()
# switches over to live numbers automatically.
FALLBACK_CATEGORY_WEIGHTS = {
    "space": 0.57,
    "ocean": 0.43,
}

PUBLIC_PUBLISH_CHANCE = 1.0

MANUAL_PERFORMANCE_LOG = [
    # {"title": "...", "category": "space", "views": 1700},
]

# Two lanes: space/physics and sea/ocean. History and bible were cut
# — neither had a single video in the channel's top 10 by views.
#
# TO EXPAND THIS POOL TO ~500 TOPICS: don't write them by hand. Run
# a one-time prompt through Gemini/AI Studio like:
#
#   "Generate 240 unique space/physics facts and 240 unique ocean
#   facts suitable for 30-45 second YouTube Shorts. Each must be a
#   lowercase topic string starting with 'how', 'why', or 'what', in
#   the style of these examples: [paste a few from below]. Avoid
#   these already-used topics: [paste the topics already in this
#   pool]. Output ONLY valid Python as a list of dicts exactly like:
#   {"topic": "...", "category": "space"},"
#
# Then paste the output directly below the existing entries in this
# list. At 2 uploads/day, even the current ~39-topic pool gives
# ~20 days of runway per category before any repeat — a 500-topic
# pool stretches that to roughly a year.
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

    # --- PASTE YOUR GENERATED ~460 ADDITIONAL TOPICS BELOW THIS LINE ---
]

# Topics that already have videos made under the old (pre-rewrite)
# system, before this file's round-robin state tracking existed.
# Filtered out permanently so the pipeline never regenerates one of
# these. If you spot another old duplicate later, add its exact
# TOPIC_POOL topic string here.
ALREADY_COVERED_TOPICS = {
    "how close we've actually gotten to absolute zero",
    "how massive a blue whale's heart actually is",
    "what dark matter actually does to galaxies",
    "how a supernova could theoretically threaten Earth",
    "what would really happen if the sun vanished for one second",
    "how deep sunlight actually stops reaching underwater",
    "how fast the Milky Way is actually moving",
    "how old the oldest living sea creature actually is",
    "how a shipwreck actually becomes an artificial reef over time",
}

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
    """
    Asks Supabase for average views per category among videos logged
    so far. Falls back to FALLBACK_CATEGORY_WEIGHTS if there's no
    data yet, or if the query fails for any reason.
    """
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
    """
    Run this by hand whenever you've checked YouTube Studio and want
    to fold updated view counts into the weighting. Fill in
    MANUAL_PERFORMANCE_LOG above, then call this once.
    """
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
    """Returns this category's topics, excluding anything already
    covered by a video made under the old system."""
    return [
        t for t in TOPIC_POOL
        if t["category"] == category and t["topic"] not in ALREADY_COVERED_TOPICS
    ]

def get_next_topic():
    """
    Per-category round-robin: each category tracks its own position
    independently and gets a freshly shuffled order each time it
    completes a full pass, so every topic in a category is used
    exactly once before any repeat.
    """
    state = load_state()
    state.setdefault("category_progress", {})

    weights = get_category_weights()
    chosen_category = random.choices(
        population=list(weights.keys()),
        weights=list(weights.values()),
        k=1,
    )[0]

    category_topics = get_category_topics(chosen_category)
    if not category_topics:
        raise RuntimeError(
            f"No available topics left in category '{chosen_category}' "
            "after excluding ALREADY_COVERED_TOPICS. Add more topics to "
            "TOPIC_POOL for this category."
        )

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
    """Appends a generated title to state so future prompts can avoid
    producing near-duplicates of recently made videos. Keeps the most
    recent 40 across all categories."""
    state = load_state()
    recent = state.get("recent_titles", [])
    recent.append(title)
    state["recent_titles"] = recent[-40:]
    save_state(state)

def get_recent_titles() -> list:
    return load_state().get("recent_titles", [])

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION (Gemini) — scene-segmented, hook-engineered
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about either a space/physics fact or a sea/ocean fact.

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
     a mental reference for. This is the strongest pattern — it's
     what the channel's best-performing video used:
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

SECOND LINE — must deliver on the hook's promise immediately with a
concrete, specific detail (a number, comparison, or vivid image). Do
not generalize or delay the payoff here — this is the exact point
where the channel's videos have historically lost the most viewers.

ENDING — follow whichever style is set above:
- If ending_style is "loop": the FINAL scene must end mid-thought or
  lead seamlessly into the very first word of the hook, so the video
  loops endlessly with no visible seam. No joke, no summary, no moral.
  Example: hook is "...is why you can never touch a black hole." ->
  final scene is "And that terrifying reality..." (loops back to hook).
- If ending_style is "joke": the FINAL scene must be a short joke or
  pun directly related to the fact — one line, genuinely funny, not a
  generic "dad joke for the sake of it." If a clean pun exists in the
  topic, prefer that over a generic joke.
  CTA (optional, joke endings only): after the joke, you may add a
  short comment-bait question tied to the fact, under 8 words (e.g.
  "Would you go down there? Comment yes or no."). Only add it when it
  feels natural on top of the joke — never force it.

TITLE — use a curiosity-gap framing, not a flat description:
  Weak:  "Facts About Deep Ocean Darkness"
  Strong: "The Ocean Depth Where Light Physically Can't Exist"
Under 60 characters. No clickbait that isn't actually true.

Favor plain, dry, factual phrasing over dramatic adjectives. On this
channel, "Why Space is Completely Silent" outperformed "Why Space Is
Terrifyingly Silent" on the same topic — the flat version won. Avoid
words like "terrifying," "insane," "shocking" in the title itself.

Break the script into scenes. Each scene is one or two sentences of
narration, including the final scene. For each scene, also provide
a visual:
- visual_type: "literal" if real stock footage of this exists
- visual_type: "abstract" if it's a concept with no real footage
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt.
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
# 2. NARRATION (Edge TTS) — per scene, so we know each clip's timing
# ------------------------------------------------------------------

async def _synthesize(text: str, voice: str, out_path: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))

def _trim_trailing_silence(in_path: Path, threshold_db: float = -40.0, min_silence_ms: int = 150) -> float:
    """
    Trims trailing silence from a narration clip and returns the
    trimmed duration, so dead air doesn't stretch that scene's visual
    out for no reason. Falls back to the untrimmed duration on any
    failure rather than crashing the run.
    """
    try:
        from moviepy import AudioFileClip
        import numpy as np

        clip = AudioFileClip(str(in_path))
        arr = clip.to_soundarray(fps=22050)
        if arr.ndim > 1:
            arr = arr.mean(axis=1)

        amplitude = np.abs(arr)
        threshold = 10 ** (threshold_db / 20)
        above = np.where(amplitude > threshold)[0]

        if len(above) == 0:
            return clip.duration

        last_sample = above[-1]
        trimmed_duration = last_sample / 22050
        trimmed_duration = min(clip.duration, trimmed_duration + 0.12)

        if clip.duration - trimmed_duration > (min_silence_ms / 1000):
            return trimmed_duration
        return clip.duration
    except Exception as e:
        print(f"      (silence trim skipped for {in_path.name}: {e})")
        from moviepy import AudioFileClip
        return AudioFileClip(str(in_path)).duration

def synthesize_scene_audio(scenes: list, run_dir: Path) -> list:
    voice = random.choice(TTS_VOICES)
    results = []

    for i, scene in enumerate(scenes):
        out_path = run_dir / f"scene_{i}.mp3"
        asyncio.run(_synthesize(scene["narration"], voice, out_path))
        duration = _trim_trailing_silence(out_path)
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
    from moviepy import AudioFileClip, CompositeAudioClip, vfx

    if not BGM_DIR.exists():
        return final_clip

    bgm_files = list(BGM_DIR.glob("*.mp3"))
    if not bgm_files:
        return final_clip

    bgm_path = random.choice(bgm_files)
    bgm = AudioFileClip(str(bgm_path))

    if bgm.duration < final_clip.duration:
        bgm = bgm.with_effects([vfx.Loop(duration=final_clip.duration)])
    else:
        bgm = bgm.subclipped(0, final_clip.duration)

    bgm = bgm.with_effects([vfx.MultiplyVolume(0.10)])

    combined_audio = CompositeAudioClip([final_clip.audio, bgm])
    return final_clip.with_audio(combined_audio)

def _build_word_timings(narration: str, duration: float) -> list:
    """
    Estimates a (word, start, end) timing for each word, spread
    proportionally by character length across the scene's actual
    audio duration. Edge TTS doesn't return true word-level
    timestamps, so this is an approximation good enough to drive a
    highlight-as-you-go caption.
    """
    words = narration.split()
    if not words:
        return []

    weights = []
    for w in words:
        weight = max(len(w), 1)
        if w.endswith((",", ";", ":")):
            weight += 2
        if w.endswith((".", "!", "?")):
            weight += 4
        weights.append(weight)

    total_weight = sum(weights)
    timings = []
    t = 0.0
    for w, wt in zip(words, weights):
        span = duration * (wt / total_weight)
        timings.append((w, t, t + span))
        t += span

    return timings

def _build_caption_clips_for_scene(narration: str, duration: float):
    """
    Builds one TextClip per word, each visible for its estimated time
    window: the full line is shown each time with only the active
    word styled differently (bigger, yellow), so the caption block
    stays in one place while the highlight moves through it.
    """
    from moviepy import TextClip

    words = narration.split()
    timings = _build_word_timings(narration, duration)
    clips = []

    for i, (word, start, end) in enumerate(timings):
        span = max(end - start, 0.05)

        line_parts = []
        for j, w in enumerate(words):
            line_parts.append(w.upper() if j == i else w)
        display_line = " ".join(line_parts)

        base = TextClip(
            font=CAPTION_FONT_PATH,
            text=display_line,
            font_size=50,
            color="white",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(VIDEO_W - 120, None),
            text_align="center",
        ).with_start(start).with_duration(span)

        highlight_word = TextClip(
            font=CAPTION_FONT_PATH,
            text=word,
            font_size=58,
            color="yellow",
            stroke_color="black",
            stroke_width=3,
            method="label",
        ).with_start(start).with_duration(span)

        clips.append(base.with_position(("center", "center")))
        clips.append(highlight_word.with_position(("center", "center")))

    return clips

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        concatenate_videoclips, vfx,
    )

    if not Path(CAPTION_FONT_PATH).exists():
        raise FileNotFoundError(
            f"CAPTION_FONT_PATH does not exist: {CAPTION_FONT_PATH}. "
            "Make sure Anton-Regular.ttf (or your chosen font) is committed "
            "to the repo root, next to main_spacefacts.py."
        )

    scene_clips = []

    for i, scene in enumerate(script["scenes"]):
        audio = AudioFileClip(str(audio_clips[i]["path"])).subclipped(0, audio_clips[i]["duration"])
        duration = audio_clips[i]["duration"]
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

        caption_clips = _build_caption_clips_for_scene(scene["narration"], duration)

        composite = CompositeVideoClip([clip, *caption_clips], size=(VIDEO_W, VIDEO_H))
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
        category=category,
        ending_style=ending_style,
        status=privacy_status,
    )

    print(f"\nDone: {final_path}")
    print(f"YouTube ({privacy_status}): https://youtu.be/{video_id}")
    return final_path


if __name__ == "__main__":
    run_pipeline()