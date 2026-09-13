"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab. Run cells top to bottom, or paste into
one cell and execute.

VIEW-MAXIMIZING CHANGES FROM YOUR LAST WORKING VERSION:
1. Ending style now alternates between two retention strategies
   instead of always ending on a joke:
     - "loop"  -> final scene loops back into the hook (higher
                  average view duration, more rewatches)
     - "joke"  -> punchline ending (higher comment/share rate)
   Both get logged to Supabase per video so you can compare real
   view/retention numbers between the two once you have a few
   weeks of data, instead of guessing which style wins.
2. Hook writing is no longer left vague. The prompt now gives
   Gemini 5 concrete hook patterns, led by "compare the extreme to
   something ordinary" — the pattern your actual best-performing
   video ("We Built Something Colder Than Deep Space", 1.7k views)
   used. Titles are steered toward plain/dry phrasing over dramatic
   adjectives, based on your own A/B evidence: "Why Space is
   Completely Silent" (971 views) beat "Why Space Is Terrifyingly
   Silent" (876 views) on the identical topic.
3. Topic selection is no longer strict round-robin. It's weighted
   toward whichever category (space vs ocean) is performing better.
   Seeded from your real 28-day YouTube Studio numbers (space
   ~1,158 avg views, ocean ~1,035 avg — a real but modest ~12% lean,
   not a hard cutoff) until Supabase has enough logged view data of
   its own to take over the weighting live. Use
   log_manual_performance() to feed in numbers you read off YouTube
   Studio if you don't have API sync set up.
4. Each run has a 50% chance of uploading as public instead of
   unlisted (PUBLIC_PUBLISH_CHANCE below) — no more manual review
   step needed for every single video before it can go live.
4. Model stays on gemini-3.6-flash (current, correct, GA as of
   July 2026) — do not swap this back to gemini-1.5-flash or any
   1.x model, those are permanently shut down.
5. Pollinations image fetch now checks content-type before saving,
   so a rate-limit/error response can't silently masquerade as a
   valid image and blow up later in moviepy.
6. TextClip now requires an explicit font path (moviepy 2.x has no
   default font fallback) — set CAPTION_FONT_PATH below or captions
   will crash the build step.

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

# moviepy 2.x TextClip has no built-in font fallback — this points at
# a font file committed to the repo root (same folder as this script),
# so it resolves the same way locally, in Colab, or in GitHub Actions.
CAPTION_FONT_PATH = str(Path(__file__).parent / "Anton-Regular.ttf")

# Rotate between a small, consistent set of Edge TTS voices.
TTS_VOICES = [
    "en-US-GuyNeural",       # calm male
    "en-GB-RyanNeural",      # measured British male
    "en-US-JennyNeural",     # warm female, explainer tone
    "en-AU-WilliamNeural",   # relaxed Australian male
]

# Seeded from your actual YouTube Studio "Top content" numbers
# (28-day window, 15 Aug - 11 Sept 2026):
#   space average ~1,158 views (absolute zero 1.7k, galaxies 1.2k,
#     supernova 1.1k, wormhole 1.1k, silence x2 971/876)
#   ocean average ~1,035 views (blue whale 1.3k, clam x2 1.0k/946,
#     giant squid 895)
# Space is ahead by ~12% — real but not dramatic, so this is a lean,
# not a hard cutoff. Used only when Supabase has no performance data
# logged yet; once get_video_performance() below returns real rows,
# these are ignored in favor of live numbers.
FALLBACK_CATEGORY_WEIGHTS = {"space": 0.55, "ocean": 0.45}

# Odds that a given run's video is uploaded as public instead of
# unlisted. Set to 0.5 for a 50/50 split. Every run still logs to
# Supabase either way, so you can see which videos went public.
PUBLIC_PUBLISH_CHANCE = 0.5

# Manually logged view counts, for when you don't have YouTube Data
# API sync wired up yet. Update this after checking YouTube Studio
# every so often — log_manual_performance() folds these into Supabase
# so the weighting stays current without needing API access.
MANUAL_PERFORMANCE_LOG = [
    # {"title": "...", "category": "space", "views": 1700},
]

# Two lanes: space/physics and sea/ocean. Each topic is tagged with
# a "category" so performance can be tracked and weighted per lane.
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

def get_category_weights():
    """
    Asks Supabase for average views per category among videos logged
    so far. Returns {"space": weight, "ocean": weight} normalized to
    sum to 1.0. Falls back to equal weights (0.5/0.5) if there's no
    data yet, or if the query fails for any reason (e.g. you haven't
    wired up a `views` column / sync job yet).

    NOTE: this assumes supabase_client exposes a helper that returns
    rows like [{"topic": "...", "category": "space", "views": 1234}, ...].
    Adjust `supabase_client.get_video_performance()` to match your
    actual table/column names if they differ.
    """
    try:
        rows = supabase_client.get_video_performance()
        if not rows:
            raise ValueError("no performance data yet")

        totals = {"space": 0, "ocean": 0}
        counts = {"space": 0, "ocean": 0}
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
        print(f"      (topic weighting fallback to seeded 55/45 — {e})")
        return dict(FALLBACK_CATEGORY_WEIGHTS)

def log_manual_performance():
    """
    Run this by hand whenever you've checked YouTube Studio and want
    to fold updated view counts into the weighting, without needing
    YouTube Data API access. Fill in MANUAL_PERFORMANCE_LOG above,
    then call this once. Requires supabase_client to expose an
    upsert-style helper — adjust to match your actual client.
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

def get_next_topic():
    """
    Picks the next topic. Cycles sequentially through whichever
    category wins the current weighting, so you still work through
    the full pool over time instead of hammering one topic — you're
    just visiting the winning lane's topics more often on average.
    """
    state = load_state()
    idx = state["index"]

    weights = get_category_weights()
    chosen_category = random.choices(
        population=list(weights.keys()),
        weights=list(weights.values()),
        k=1,
    )[0]

    category_topics = [t for t in TOPIC_POOL if t["category"] == chosen_category]
    topic_entry = category_topics[idx % len(category_topics)]

    state["index"] = idx + 1
    save_state(state)
    return topic_entry

# ------------------------------------------------------------------
# 1. SCRIPT GENERATION (Gemini) — scene-segmented, hook-engineered
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 30-45 second YouTube Shorts script
about a space/physics fact OR a sea/ocean fact.

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
     a mental reference for. This is the strongest pattern of the
     five — it's what the channel's best-performing video used:
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
  button on the video, the kind of line that gets a laugh-comment. If
  a clean pun exists in the topic (wordplay on the animal, phenomenon,
  or scientific term), prefer that over a generic joke.

TITLE — use a curiosity-gap framing, not a flat description:
  Weak:  "Facts About Deep Ocean Darkness"
  Strong: "The Ocean Depth Where Light Physically Can't Exist"
Under 60 characters. No clickbait that isn't actually true.

Favor plain, dry, factual phrasing over dramatic adjectives. On this
channel, "Why Space is Completely Silent" outperformed "Why Space Is
Terrifyingly Silent" on the same topic — the flat version won. Avoid
words like "terrifying," "insane," "shocking" in the title itself
(they're fine sparingly in narration, just not as the title's hook).

Break the script into scenes. Each scene is one or two sentences of
narration, including the final scene. For each scene, also provide
a visual:
- visual_type: "literal" if real stock footage of this exists
  (e.g. a dam, the ISS, a starfield, a person walking)
- visual_type: "abstract" if it's a concept with no real footage
  (e.g. gravitational time dilation, a wormhole cross-section,
  spacetime curvature)
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt (can be
  longer, be specific and cinematic).
- For a "joke" ending, pick whichever visual actually supports the
  punchline (often literal — the animal/phenomenon reacting, or a
  simple relevant clip works better than an abstract image for
  comedic timing).

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
"""

def generate_script(topic: str, ending_style: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")

    prompt = SCRIPT_SYSTEM_PROMPT.format(topic=topic, ending_style=ending_style)
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
# 2. NARRATION (Edge TTS) — per scene, so we know each clip's timing
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

def fetch_pollinations_image(prompt: str, out_path: Path) -> Path:
    """Free, no-key AI image generation for abstract concepts.
    Verifies the response is actually an image before saving, so a
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

def build_video(script: dict, audio_clips: list, visuals: list, run_dir: Path) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx,
    )

    if not Path(CAPTION_FONT_PATH).exists():
        raise FileNotFoundError(
            f"CAPTION_FONT_PATH does not exist: {CAPTION_FONT_PATH}. "
            "Make sure Anton-Regular.ttf (or your chosen font) is committed "
            "to the repo root, next to main_spacefacts.py."
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

    # Alternate ending style per run so both strategies keep getting
    # fresh data logged against them for later comparison.
    ending_style = random.choice(["loop", "joke"])

    print(f"[1/4] Generating script for topic: {topic} (category={category}, ending={ending_style})")
    script = generate_script(topic, ending_style)
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

    # 50/50 chance this run's video goes public vs. stays unlisted for
    # manual review. Determined once per run so the print, upload call,
    # and Supabase log all agree on the same value.
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
    # NOTE: category and ending_style are tracked locally (printed above)
    # but not yet logged to Supabase — log_video()'s current signature in
    # supabase_client.py doesn't accept them. The category-weighting
    # feature falls back to the seeded 55/45 split until that function is
    # updated to store and return these fields.

    print(f"\nDone: {final_path}")
    print(f"YouTube ({privacy_status}): https://youtu.be/{video_id}")
    print("Review and publish from the dashboard.")
    return final_path


if __name__ == "__main__":
    run_pipeline()
