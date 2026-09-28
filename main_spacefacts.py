"""
==================================================================
SPACE/PHYSICS + HISTORY FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab / GitHub Actions.

TWO LANES ONLY — space/physics and history.

TARGET LENGTH: 20-30 seconds (60-75 words, 4 scenes). Shorter
videos make the AVD percentage bar physically easier to clear,
which is what the distribution algorithm actually rewards.

PERFORMANCE TRACKING: none. You check YouTube Studio yourself for
analytics. Topic selection uses a static weight (space slightly
favored) that you can hand-edit in CATEGORY_WEIGHTS.

GEMINI QUOTA HANDLING: free tier on gemini-3.6-flash is 5 requests
per minute per project. Manual re-runs cluster easily and trip it.
The pipeline now reads Gemini's "retry in Ns" hint, sleeps that
long, and retries once before giving up — instead of failing the
whole run on a quota blip.

REQUIRED INSTALLS (Colab + GitHub Actions pip line):
    !pip install google-generativeai edge-tts moviepy pillow requests --quiet

REQUIRED API KEYS (env vars or Colab secrets):
    GEMINI_API_KEY   -> https://aistudio.google.com/apikey (free)
    PEXELS_API_KEY   -> https://www.pexels.com/api/ (free)
    Pollinations needs NO KEY.
==================================================================
"""

import os
import re
import json
import time
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

# How often each lane gets picked. Hand-edit after a look at Studio
# if one lane is clearly pulling better — space starts a little
# ahead because that's the lane with real numbers so far. Values
# don't need to sum to 1.0; they get normalized at selection time.
CATEGORY_WEIGHTS = {
    "space": 0.55,
    "history": 0.45,
}

# Odds that a given run's video goes public instead of unlisted.
# 0.5 = 50/50. Set to 1.0 once you trust the pipeline enough to
# publish everything straight away.
PUBLIC_PUBLISH_CHANCE = 0.5

# ------------------------------------------------------------------
# INSPIRATION TRANSCRIPTS
# ------------------------------------------------------------------
# Style references fed into the script prompt. Match RHYTHM, not
# content: sentence length, how fast the first beat lands, how tight
# the payoff is, whether there's a callback.
#
# Both are trimmed to ~65-75 words to anchor the model on a short
# rhythm. The full Fosbury arc teaches "escalate over many beats,"
# which is a story shape, not a 25-second fact shape — the trim
# keeps the rhythm without the length.
#
# Paste raw — _clean_transcript() below strips [Music], >>, and
# timestamp artifacts at prompt-build time.
INSPIRATION_TRANSCRIPTS = [
    # History lane — setup + conflict + one specific detail.
    """
The first time 80,000 people watched Dick Fosbury jump, they laughed.
4 hours later, the stadium was dead silent. Back then, there were four
ways to high jump. Fosbury didn't use any of them. He just jumped the
way that felt natural to him. And every meet, that jump of his got a
little weirder and went a little higher. He walked in wearing two
different shoes.
""",

    # Space lane — your best performer, tightened. Keeps every beat:
    # hook, real number, turn to the lab, payoff number, translation,
    # callback, pun.
    """
Deep space seems freezing, but it isn't even close to the coldest
place in the universe. The void sits around 3 Kelvin, warmed by
leftover radiation from the Big Bang. The coldest spot ever recorded
is inside a physics lab on Earth — 38 pico Kelvins. That's 38
trillionths of a degree above absolute zero. Hold on. Humans built a
spot in Germany colder than the space between galaxies. How do
physicists feel about hitting absolute zero? Honestly, they think
it's zero K.
""",
]

# ------------------------------------------------------------------
# TOPIC POOL — space/physics + history only
# ------------------------------------------------------------------

TOPIC_POOL = [
    # --- space / physics ---
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
    {"topic": "what actually happens at the speed of light", "category": "space"},
    {"topic": "why the moon is slowly drifting away from Earth", "category": "space"},
    {"topic": "what the Great Attractor is pulling our galaxy toward", "category": "space"},
    {"topic": "how gravitational waves were first detected on Earth", "category": "space"},
    {"topic": "why Mercury's day is longer than its year", "category": "space"},
    {"topic": "how far the Oort Cloud actually extends past the planets", "category": "space"},
    {"topic": "what would happen to Earth if Jupiter disappeared", "category": "space"},
    {"topic": "how a compass would actually behave on Mars", "category": "space"},

    # --- history ---
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
    {"topic": "what actually happened to the crew of the Mary Celeste", "category": "history"},
    {"topic": "where Genghis Khan's tomb might actually be hidden", "category": "history"},
    {"topic": "why the Olmec heads were carved and then deliberately buried", "category": "history"},
    {"topic": "what caused the abandoned city of Cahokia to empty out", "category": "history"},
    {"topic": "whether the Bimini Road is natural rock or something else", "category": "history"},
    {"topic": "why Stonehenge was actually built and by whom", "category": "history"},
    {"topic": "what the ruins of Great Zimbabwe were really used for", "category": "history"},
    {"topic": "who the Sea Peoples were and why they destroyed entire kingdoms", "category": "history"},
]

# ------------------------------------------------------------------
# STATE (round-robin topic progression + recent-titles memory)
# ------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"category_progress": {}, "recent_titles": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_category_topics(category: str) -> list:
    return [t for t in TOPIC_POOL if t["category"] == category]


def get_recent_titles() -> list:
    return load_state().get("recent_titles", [])


def record_used_title(title: str):
    """Appends a generated title to state so future prompts can avoid
    near-duplicates of recently made videos. Keeps the most recent 40."""
    state = load_state()
    recent = state.get("recent_titles", [])
    recent.append(title)
    state["recent_titles"] = recent[-40:]
    save_state(state)


def get_next_topic():
    """
    Per-category round-robin. Each category tracks its own position
    independently; "order" is a shuffled permutation regenerated
    fresh each time a full pass completes, so you get variety in
    the sequence too while still guaranteeing every topic is used
    exactly once before any repeat.

    Weight comes from CATEGORY_WEIGHTS above.
    """
    state = load_state()
    state.setdefault("category_progress", {})

    categories = [t["category"] for t in TOPIC_POOL]
    categories = list(dict.fromkeys(categories))  # dedupe, preserve order
    weights = [CATEGORY_WEIGHTS.get(c, 0.0) for c in categories]

    # If every weight is zeroed out, fall back to uniform so the
    # pipeline doesn't crash on a config mistake.
    if sum(weights) <= 0:
        weights = [1.0] * len(categories)

    chosen_category = random.choices(
        population=categories, weights=weights, k=1
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

# ------------------------------------------------------------------
# SCRIPT GENERATION
# ------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """You are writing a 20-30 second YouTube Shorts script
about either a space/physics fact or a strange piece of real history.

ENDING STYLE FOR THIS SCRIPT: {ending_style}

HARD LENGTH LIMITS — do not exceed these:
  - Total narration: 60-75 words. Count them. A 75-word script runs
    about 30 seconds spoken; anything longer and the video is too
    long for the retention math to work in its favor.
  - Scenes: 4 scenes, 5 absolute maximum (including the final scene).
    If you find yourself needing a 6th scene, you're explaining too
    much — cut the weakest fact instead.
  - Hook: 8 words or fewer (see below).

WHY LENGTH MATTERS — average view duration is judged as a PERCENTAGE
of the clip, not as raw seconds. Hitting 100% on a 20-second video
means holding attention for 20 seconds; hitting it on a 45-second
video means holding attention for 45. Same ratio, twice the work.
Shorter videos make the retention bar physically easier to clear,
which is why they get pushed harder. Do not pad.

RETENTION TARGETS — the two numbers the algorithm judges this on:
  - Swipe rate (share of viewers who leave in the first 4 seconds):
    must be 20% or LOWER. Controlled entirely by the hook.
  - Average view duration: must be 100% of clip length or more. The
    loop ending pushes this past 100%, which is why loop endings
    tend to win on this metric.

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
- When you cite a number, ALWAYS translate it into a comparison or
  ordinary reference in the same breath. "38 pico Kelvins" means
  nothing to a viewer; "38 trillionths of a degree above absolute
  zero" does. A number without a translation is a number the viewer
  will not remember.

HOOK — the first scene's narration. This is the single most important
line in the video. It must be fully spoken within 2.5 seconds (roughly
8 words or fewer) because that is the window in which the viewer's
finger decides whether to swipe. A longer hook = higher swipe rate,
full stop.

Use ONE of these five patterns, whichever fits the topic best:
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
Prefer pattern 1 when a genuinely apt comparison exists.
Do NOT use generic hook filler like "did you know" or "here's a fact
that will blow your mind."
Do NOT start with a subordinate clause ("In the depths of...",
"Somewhere in the universe...") — those push the actual hook past
the swipe window.

ENDING — follow whichever style is set above:
- If ending_style is "loop": the FINAL scene must end mid-thought or
  lead seamlessly into the very first word of the hook, so the video
  loops endlessly with no visible seam. No joke, no summary, no moral.
  Example: hook is "...is why you can never touch a black hole." ->
  final scene is "And that terrifying reality..." (loops back to hook).
- If ending_style is "joke": the FINAL scene must be a short joke or
  pun directly related to the fact — one line, genuinely funny, not a
  generic "dad joke for the sake of it." If a clean pun exists in the
  topic (wordplay on the phenomenon, object, or historical term),
  prefer that over a generic joke. The strongest joke endings connect
  the pun directly back to the specific number or comparison the
  video just established.

TITLE — under 60 characters. Use a curiosity-gap framing, not a flat
description:
  Weak:  "Facts About Deep Ocean Darkness"
  Strong: "The Ocean Depth Where Light Physically Can't Exist"

Also return a "title_emphasis" field: the substring of your title
that a thumbnail renderer should highlight in a different color.
Pick the one phrase that carries the whole hook of the title (2-4
words), e.g. for "The Ocean Depth Where Light Physically Can't Exist"
the emphasis would be "Can't Exist". This is what top channels do on
their titles, and it's why a two-line colored break reads faster
than a flat white sentence.

Favor plain, dry, factual phrasing over dramatic adjectives. On this
channel, "Why Space is Completely Silent" outperformed "Why Space Is
Terrifyingly Silent" on the same topic — the flat version won. Avoid
"terrifying," "insane," "shocking" in the title itself.

Break the script into scenes. Each scene is one or two sentences of
narration, including the final scene. For each scene, also provide
a visual:
- visual_type: "literal" if real stock footage of this exists
- visual_type: "abstract" if it's a concept with no real footage
- visual_query: for "literal", a 3-6 word stock footage search term.
  For "abstract", a descriptive AI image generation prompt (longer
  is fine, be specific and cinematic).
- For a "joke" ending, pick whichever visual actually supports the
  punchline (often literal — a simple relevant clip works better
  than an abstract image for comedic timing).

Return ONLY valid JSON, no markdown fences, no commentary, in this
exact shape:

{{
  "title": "short punchy YouTube title, under 60 characters",
  "title_emphasis": "2-4 word substring of title to highlight",
  "hook": "the first scene's narration — spoken in <= 2.5 seconds",
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
{style_reference_block}
"""


def _clean_transcript(raw: str) -> str:
    """
    Strips artifacts transcript sites leave in: [Music], [Applause],
    >> speaker markers, timestamp lines, and blank-line runs. Safe to
    run on already-clean text.
    """
    text = raw
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"^\s*>>\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s*$", "", text, flags=re.M)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _build_style_reference_block() -> str:
    """
    Turns INSPIRATION_TRANSCRIPTS into a concrete style-reference
    block for the prompt. Pasting a real viral short's rhythm does
    far more for swipe rate than any list of adjectives, because the
    model copies structure, not vibes.
    """
    if not INSPIRATION_TRANSCRIPTS:
        return ""

    cleaned = [_clean_transcript(t) for t in INSPIRATION_TRANSCRIPTS]
    cleaned = [t for t in cleaned if t]
    if not cleaned:
        return ""

    joined = "\n\n---\n\n".join(cleaned)
    return (
        "STYLE REFERENCE — these are transcripts of shorts that went "
        "viral. Match their RHYTHM: how fast the first sentence lands, "
        "how short the sentences are, how quickly the payoff arrives, "
        "how they transition between beats, whether there's a "
        "callback. Do NOT copy their content, wording, or topic — "
        "only the pacing. If a rule above conflicts with their style, "
        "the rule above wins.\n\n"
        + joined
    )


def _is_transient_gemini_error(e) -> bool:
    """Quota / rate-limit errors are not worth retrying within seconds
    — they need a real time gap, and retrying just burns the same
    per-minute quota three times instead of once."""
    msg = str(e)
    return not any(
        marker in msg for marker in ("RESOURCE_EXHAUSTED", "429", "quota")
    )


def _extract_retry_delay(e) -> float | None:
    """
    Gemini's quota errors include a literal 'retry in Ns' string in
    the error body. Pull it out so we sleep exactly as long as they
    ask, instead of guessing. Returns None if not present.
    """
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(e))
    return float(m.group(1)) if m else None


def _call_gemini_with_quota_fallback(call_fn):
    """
    Runs call_fn(). On a quota-exhaustion error, reads the delay
    Gemini tells us to wait, sleeps that long + buffer, and retries
    once. On any other error, re-raises immediately — the caller's
    inner retry_with_backoff handles those.

    Why this exists: Gemini's free tier on gemini-3.6-flash is 5
    requests per minute per project. A 2-runs/day schedule can't hit
    that, but manual workflow_dispatch triggers cluster easily — two
    re-runs inside the same minute will. Without this, a single
    quota blip fails an otherwise-healthy scheduled run.

    Delay is capped at 90s so a run can't sit for minutes waiting on
    Gemini before the GitHub Actions job timeout (30 min) triggers.
    If the second attempt also fails, it raises normally — no
    infinite loops.
    """
    try:
        return call_fn()
    except Exception as e:
        msg = str(e)
        if not any(m in msg for m in ("RESOURCE_EXHAUSTED", "429", "quota")):
            raise

        delay = _extract_retry_delay(e)
        if delay is None:
            # Can't read the hint — better to fail than guess and
            # sleep an arbitrary amount.
            raise

        delay = min(delay, 90.0) + 5.0
        print(f"      (quota hit — sleeping {delay:.0f}s for window to "
              f"clear, then retrying once)")
        time.sleep(delay)
        return call_fn()


def generate_script(topic: str, ending_style: str, recent_titles: list = None) -> dict:
    if recent_titles:
        titles_list = "\n".join(f"- {t}" for t in recent_titles)
        recent_titles_block = (
            "AVOID RESEMBLING RECENT VIDEOS — these titles were made "
            "recently on this channel. Even if today's topic is "
            "technically different, do not produce a hook, angle, or "
            "framing that would feel like a repeat of any of these to a "
            "viewer who's seen them:\n" + titles_list
        )
    else:
        recent_titles_block = ""

    style_reference_block = _build_style_reference_block()

    prompt = SCRIPT_SYSTEM_PROMPT.format(
        topic=topic,
        ending_style=ending_style,
        recent_titles_block=recent_titles_block,
        style_reference_block=style_reference_block,
    )

    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    # Do not downgrade this. gemini-1.x models are permanently shut
    # down, and gemini-3.6-flash is the current GA model.
    model = genai.GenerativeModel("gemini-3.6-flash")

    def _call_gemini():
        return model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )

    # Two layers of retry, deliberately stacked:
    #   inner — handles transient 5xx / network hiccups with quick backoff
    #   outer — handles quota-exhaustion by sleeping the exact window
    # Quota errors are excluded from the inner retry (should_retry
    # returns False for them) so they bubble straight to the outer
    # wrapper instead of burning the per-minute budget on useless
    # fast retries.
    response = _call_gemini_with_quota_fallback(
        lambda: retry_with_backoff(
            _call_gemini, retries=3, base_delay=5,
            should_retry=_is_transient_gemini_error,
        )
    )

    data = json.loads(response.text)

    assert "scenes" in data and len(data["scenes"]) > 0, "No scenes returned"
    for scene in data["scenes"]:
        assert scene["visual_type"] in ("literal", "abstract")

    if not data.get("title_emphasis"):
        words = data["title"].split()
        data["title_emphasis"] = (
            " ".join(words[-2:]) if len(words) >= 2 else data["title"]
        )

    return data

# ------------------------------------------------------------------
# TTS
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
# VISUALS
# ------------------------------------------------------------------

def retry_with_backoff(fn, *args, retries=3, base_delay=3,
                       should_retry=None, **kwargs):
    """
    Retries fn on failure with exponential backoff (3s, 6s, 12s).
    should_retry(exception) -> bool: if it returns False, fail
    immediately instead of burning all retries on an error that
    can't possibly resolve in seconds.
    """
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


def fetch_pexels_video(query: str, out_path: Path):
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
    url = (f"https://image.pollinations.ai/prompt/{encoded}"
           f"?width={VIDEO_W}&height={VIDEO_H}&nologo=true")

    r = requests.get(url, timeout=60)
    r.raise_for_status()

    content_type = r.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise RuntimeError(
            f"Pollinations did not return an image (content-type: "
            f"{content_type})"
        )

    out_path.write_bytes(r.content)
    return out_path


def _generate_fallback_image(prompt: str, out_path: Path) -> Path:
    """Last-resort visual if Pollinations is down. Local-only, so it
    can't fail the same way, and the run still produces a video."""
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
        (80, VIDEO_H // 2 - 150), wrapped,
        fill=(220, 220, 220), font=font, spacing=16,
    )

    img.save(out_path)
    return out_path


def fetch_pollinations_image(prompt: str, out_path: Path) -> Path:
    try:
        return retry_with_backoff(
            _fetch_pollinations_image_once, prompt, out_path
        )
    except Exception as e:
        print(f"      (Pollinations failed — using fallback image: {e})")
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
# ASSEMBLY
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

    # Keep it low — should sit under the narration, not compete with
    # it. 10% is a conservative start; raise toward 0.15-0.18 if it
    # feels too quiet, but test a few videos first.
    bgm = bgm.with_effects([afx.MultiplyVolume(0.10)])

    combined = CompositeAudioClip([final_clip.audio, bgm])
    return final_clip.with_audio(combined)


def build_video(script: dict, audio_clips: list, visuals: list,
                run_dir: Path) -> Path:
    from moviepy import (
        AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip,
        TextClip, concatenate_videoclips, vfx,
    )

    if not Path(CAPTION_FONT_PATH).exists():
        raise FileNotFoundError(
            f"CAPTION_FONT_PATH does not exist: {CAPTION_FONT_PATH}. "
            "Commit your font file to the repo root, next to main.py."
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

        clip = clip.with_effects(
            [vfx.Resize(height=VIDEO_H)]
        ).with_position("center")

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

        composite = CompositeVideoClip(
            [clip, caption], size=(VIDEO_W, VIDEO_H)
        )
        composite = composite.with_audio(audio)
        scene_clips.append(composite)

    final = concatenate_videoclips(scene_clips, method="compose")
    final = add_background_music(final)

    out_path = run_dir / "final_video.mp4"
    # preset="fast" roughly halves encode time vs the default medium
    # preset. File is ~10% larger, which is irrelevant at Shorts
    # sizes. logger=None suppresses moviepy's per-frame progress
    # print, which floods Actions logs and eats CPU.
    final.write_videofile(
        str(out_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        logger=None,
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

    print(f"[1/4] Generating script for topic: {topic} "
          f"(category={category}, ending={ending_style})")
    recent_titles = get_recent_titles()
    script = generate_script(
        topic, ending_style, recent_titles=recent_titles
    )
    print(f"      Title: {script['title']}")
    print(f"      Emphasis: {script.get('title_emphasis', '(none)')}")
    print(f"      Scenes: {len(script['scenes'])}")
    record_used_title(script["title"])

    run_dir = OUTPUT_DIR / script["title"].replace(" ", "_")[:40]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps(script, indent=2))

    print("[2/4] Synthesizing narration (Edge TTS)...")
    audio_clips = synthesize_scene_audio(script["scenes"], run_dir)
    total_seconds = sum(a["duration"] for a in audio_clips)
    print(f"      Total narration: {total_seconds:.1f}s")

    print("[3/4] Fetching visuals (Pexels + Pollinations)...")
    visuals = [
        fetch_visual_for_scene(scene, i, run_dir)
        for i, scene in enumerate(script["scenes"])
    ]

    print("[4/4] Assembling final video...")
    final_path = build_video(script, audio_clips, visuals, run_dir)

    privacy_status = (
        "public" if random.random() < PUBLIC_PUBLISH_CHANCE else "unlisted"
    )

    print(f"Uploading to YouTube as {privacy_status}...")
    description = (
        f"{script.get('hook', '')}\n\n{' '.join(script['hashtags'])}"
    )
    upload_result = youtube_upload.upload_video(
        file_path=str(final_path),
        title=script["title"],
        description=description,
        tags=[h.replace("#", "") for h in script["hashtags"]],
        privacy_status=privacy_status,
    )
    video_id = upload_result["id"]

    print(f"\nDone: {final_path}")
    print(f"YouTube ({privacy_status}): https://youtu.be/{video_id}")
    print(f"Ending style this run: {ending_style}")
    return final_path


if __name__ == "__main__":
    run_pipeline()