"""
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v9.3)

FORMAT:
    Interesting stock footage
    +
    History / trivia / science narration
    +
    Dynamic captions
    +
    Consistent male narrator

VIDEO SOURCE:
    Coverr API
    Multiple clips per Short

PIPELINE:
    1. Fetch fresh On This Day events and/or trivia
    2. Select a strong topic with Gemini
    3. Generate a 30–45 second Shorts script
    4. Generate visual search queries
    5. Search Coverr for multiple clips
    6. Fall back to local footage if Coverr fails
    7. Generate narration with Edge TTS
    8. Build 1080x1920 vertical Short
    9. Add dynamic captions
   10. Upload to YouTube
   11. Save state only after successful upload
"""

import os
import re
import json
import time
import random
import hashlib
import html
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

import requests

# ============================================================
# PILLOW / MOVIEPY 1.0.3 COMPATIBILITY FIX
# ============================================================

# MoviePy 1.0.3 expects Image.ANTIALIAS.
# Pillow 10+ removed it and replaced it with Image.Resampling.LANCZOS.
# Restore the old alias before importing MoviePy.
from PIL import Image

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS


# ============================================================
# MOVIEPY
# ============================================================

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)


# ============================================================
# CONFIG
# ============================================================

VERSION = "v9.3"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
COVERR_API_KEY = os.environ.get("COVERR_API_KEY", "")

STATE_FILE = Path("state_spacefacts.json")
UPLOAD_LOG_FILE = Path("upload_log.jsonl")

OUTPUT_DIR = Path("output_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)

FOOTAGE_DIR = Path(os.environ.get("FOOTAGE_DIR", "footage"))
GAMEPLAY_DIR = Path(os.environ.get("GAMEPLAY_DIR", "gameplay"))

COVERR_DOWNLOAD_DIR = Path("downloaded_footage")
COVERR_DOWNLOAD_DIR.mkdir(exist_ok=True)

BGM_DIR = Path(os.environ.get("BGM_DIR", "bgm"))

VIDEO_W = 1080
VIDEO_H = 1920

CAPTION_FONT_PATH = str(Path(__file__).parent / "Anton-Regular.ttf")

TTS_VOICE = "en-US-AndrewMultilingualNeural"

COVERR_API_URL = "https://api.coverr.co/videos/search"
COVERR_BASE_URL = "https://coverr.co/"

REQUEST_TIMEOUT = 45

TARGET_MIN_SECONDS = 30
TARGET_MAX_SECONDS = 45

MAX_SCENES = 8

CONTENT_WEIGHTS = {
    "on_this_day": 0.45,
    "trivia": 0.25,
    "evergreen": 0.30,
}

FOOTAGE_STYLES = [
    "construction",
    "machines",
    "cars",
    "nature",
    "satisfying",
    "sports",
    "animation",
    "ocean",
    "aviation",
    "general",
]


# ============================================================
# GEMINI MODELS
# ============================================================

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]


# ============================================================
# EVERGREEN TOPICS
# ============================================================

EVERGREEN_TOPICS = [
    # History
    {
        "key": "roman_concrete",
        "category": "history",
        "topic": "Why Roman concrete lasted for thousands of years",
    },
    {
        "key": "cats_ancient_egypt",
        "category": "history",
        "topic": "Why cats were important in ancient Egypt",
    },
    {
        "key": "viking_navigation",
        "category": "history",
        "topic": "How Vikings navigated across the ocean",
    },
    {
        "key": "pompeii",
        "category": "history",
        "topic": "What happened when Mount Vesuvius buried Pompeii",
    },
    {
        "key": "titanic",
        "category": "history",
        "topic": "Why the Titanic sank so quickly",
    },
    {
        "key": "telegraph",
        "category": "history",
        "topic": "How the telegraph changed communication",
    },
    {
        "key": "black_death",
        "category": "history",
        "topic": "How the Black Death spread across Europe",
    },
    {
        "key": "great_fire_london",
        "category": "history",
        "topic": "How the Great Fire of London spread",
    },

    # Science
    {
        "key": "lightning",
        "category": "science",
        "topic": "How lightning can heat the air around it",
    },
    {
        "key": "ocean_depth",
        "category": "science",
        "topic": "How deep the deepest part of the ocean really is",
    },
    {
        "key": "black_holes",
        "category": "science",
        "topic": "What happens near a black hole",
    },
    {
        "key": "banana_radiation",
        "category": "science",
        "topic": "Why bananas are slightly radioactive",
    },
    {
        "key": "sound_space",
        "category": "science",
        "topic": "Why sound cannot travel through empty space",
    },
    {
        "key": "sharks_electricity",
        "category": "science",
        "topic": "How sharks detect tiny electrical signals",
    },
    {
        "key": "ant_strength",
        "category": "science",
        "topic": "Why ants can carry objects much heavier than themselves",
    },
    {
        "key": "time_dilation",
        "category": "science",
        "topic": "How time can move differently at high speeds",
    },

    # Engineering
    {
        "key": "bridges",
        "category": "engineering",
        "topic": "How suspension bridges handle enormous forces",
    },
    {
        "key": "tall_buildings",
        "category": "engineering",
        "topic": "How skyscrapers survive strong winds",
    },
    {
        "key": "dams",
        "category": "engineering",
        "topic": "How huge dams hold back millions of tons of water",
    },
    {
        "key": "tunnels",
        "category": "engineering",
        "topic": "How engineers build tunnels underground",
    },
    {
        "key": "cranes",
        "category": "engineering",
        "topic": "How tower cranes lift enormous loads",
    },
    {
        "key": "bulldozers",
        "category": "engineering",
        "topic": "How bulldozers generate enough force to move huge amounts of soil",
    },

    # Technology
    {
        "key": "microchips",
        "category": "technology",
        "topic": "How billions of transistors fit inside a tiny microchip",
    },
    {
        "key": "fiber_optics",
        "category": "technology",
        "topic": "How fiber optic cables send information using light",
    },
    {
        "key": "gps",
        "category": "technology",
        "topic": "How GPS satellites know where your phone is",
    },
    {
        "key": "smartphones",
        "category": "technology",
        "topic": "How smartphones became tiny computers",
    },

    # Transport
    {
        "key": "jet_engines",
        "category": "transport",
        "topic": "How jet engines produce enormous thrust",
    },
    {
        "key": "supersonic",
        "category": "transport",
        "topic": "What happens when an aircraft breaks the sound barrier",
    },
    {
        "key": "train_brakes",
        "category": "transport",
        "topic": "How massive trains stop safely",
    },
    {
        "key": "container_ships",
        "category": "transport",
        "topic": "How container ships carry thousands of containers",
    },

    # Nature
    {
        "key": "octopus",
        "category": "nature",
        "topic": "Why octopuses are so unusual",
    },
    {
        "key": "crows",
        "category": "nature",
        "topic": "Why crows are surprisingly intelligent",
    },
    {
        "key": "bird_migration",
        "category": "nature",
        "topic": "How birds navigate during long migrations",
    },
    {
        "key": "volcanoes",
        "category": "nature",
        "topic": "What happens beneath a volcano before an eruption",
    },
    {
        "key": "tornadoes",
        "category": "nature",
        "topic": "How tornadoes form",
    },
    {
        "key": "lightning_nature",
        "category": "nature",
        "topic": "Why lightning strikes some places more often than others",
    },
]


# ============================================================
# STATE
# ============================================================

DEFAULT_STATE = {
    "recent_titles": [],
    "used_source_ids": [],
    "used_topic_keys": [],
    "used_gameplay": [],
}


def load_state():
    if not STATE_FILE.exists():
        return DEFAULT_STATE.copy()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            return DEFAULT_STATE.copy()

        for key, value in DEFAULT_STATE.items():
            if key not in data or not isinstance(data[key], list):
                data[key] = []

        return data

    except Exception as e:
        print(f"[SpaceFacts] Could not load state: {e}")
        return DEFAULT_STATE.copy()


def save_state(state):
    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[SpaceFacts] Failed to save state: {e}")
        raise


# ============================================================
# UTILITIES
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def slugify(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")

    if not value:
        value = "clip"

    return value[:80]


def safe_json_loads(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])

        raise


def weighted_choice(items):
    names = list(items.keys())
    weights = list(items.values())
    return random.choices(names, weights=weights, k=1)[0]


def hash_text(text):
    return hashlib.sha256(
        text.encode("utf-8", errors="ignore")
    ).hexdigest()[:16]


# ============================================================
# GEMINI
# ============================================================

def get_gemini_client():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    from google import genai

    return genai.Client(api_key=GEMINI_API_KEY)


def discover_gemini_models(client):
    """
    Discover available Gemini models.

    We still retain the static fallback list because API model
    discovery can occasionally fail or return unexpected formats.
    """

    discovered = []

    try:
        for model in client.models.list():
            name = getattr(model, "name", "")

            if not name:
                continue

            name = name.replace("models/", "")

            if "gemini" not in name.lower():
                continue

            if "flash" not in name.lower():
                continue

            discovered.append(name)

    except Exception as e:
        print(f"[SpaceFacts] Gemini model discovery failed: {e}")

    preferred = []

    for model in GEMINI_MODELS:
        if model in discovered:
            preferred.append(model)

    for model in discovered:
        if model not in preferred:
            preferred.append(model)

    if not preferred:
        preferred = GEMINI_MODELS.copy()

    return preferred


def is_service_unavailable(error):
    text = str(error).upper()

    return (
        "503" in text
        or "UNAVAILABLE" in text
        or "SERVICE UNAVAILABLE" in text
    )


def is_quota_or_rate_limit(error):
    text = str(error).upper()

    return (
        "429" in text
        or "RESOURCE_EXHAUSTED" in text
        or "QUOTA" in text
        or "RATE LIMIT" in text
        or "RATE_LIMIT" in text
    )


def gemini_generate(prompt, temperature=0.8):
    client = get_gemini_client()

    models = discover_gemini_models(client)

    last_error = None

    for model_index, model_name in enumerate(models):

        print(
            f"[SpaceFacts] Trying Gemini model "
            f"{model_index + 1}/{len(models)}: {model_name}"
        )

        for attempt in range(2):

            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "temperature": temperature,
                    },
                )

                text = getattr(response, "text", None)

                if not text:
                    raise RuntimeError(
                        f"Gemini returned an empty response using {model_name}."
                    )

                print(
                    f"[SpaceFacts] Gemini succeeded with {model_name}"
                )

                return text.strip()

            except Exception as e:
                last_error = e

                print(
                    f"[SpaceFacts] Gemini {model_name} "
                    f"attempt {attempt + 1}/2 failed: {e}"
                )

                if is_service_unavailable(e):
                    print(
                        f"[SpaceFacts] {model_name} is temporarily "
                        f"unavailable. Switching to next Gemini model..."
                    )
                    break

                if is_quota_or_rate_limit(e):
                    print(
                        f"[SpaceFacts] {model_name} hit a quota/rate "
                        f"limit. Switching to next Gemini model..."
                    )
                    break

                if attempt == 0:
                    time.sleep(2)

        print("[SpaceFacts] Moving to next Gemini model...")

    raise RuntimeError(
        f"All Gemini models failed. Last error: {last_error}"
    )


# ============================================================
# WIKIMEDIA — ON THIS DAY
# ============================================================

def fetch_on_this_day():
    today = datetime.now(timezone.utc)

    month = today.month
    day = today.day

    print(
        f"[SpaceFacts] Fetching Wikimedia events for "
        f"{month:02d}/{day:02d}..."
    )

    url = (
        "https://en.wikipedia.org/api/rest_v1/feed/"
        f"onthisday/events/{month}/{day}"
    )

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "SpaceFactsPipeline/9.3"
        },
    )

    response.raise_for_status()

    data = response.json()

    events = []

    for event in data.get("events", []):
        year = event.get("year")
        text = clean_text(event.get("text"))

        if not text:
            continue

        pages = event.get("pages") or []

        source_id = ""

        if pages:
            source_id = (
                pages[0].get("pageid")
                or pages[0].get("title")
                or ""
            )

        if not source_id:
            source_id = hash_text(
                f"{year}:{text}"
            )

        events.append({
            "source_id": str(source_id),
            "year": year,
            "text": text,
            "pages": pages,
        })

    print(
        f"[SpaceFacts] Found {len(events)} usable "
        f"historical events."
    )

    return events


# ============================================================
# TRIVIA
# ============================================================

def fetch_trivia():
    print("[SpaceFacts] Fetching trivia...")

    url = "https://opentdb.com/api.php"

    response = requests.get(
        url,
        params={
            "amount": 15,
            "type": "multiple",
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    results = data.get("results", [])

    trivia = []

    for item in results:
        question = clean_text(item.get("question"))

        if not question:
            continue

        trivia.append({
            "source_id": hash_text(question),
            "category": clean_text(item.get("category")),
            "question": question,
            "answer": clean_text(item.get("correct_answer")),
        })

    return trivia


# ============================================================
# TOPIC SELECTION
# ============================================================

TOPIC_SELECTOR_PROMPT = """
You are selecting a topic for a YouTube Shorts channel.

The channel creates short, highly interesting factual videos.

Choose ONE candidate.

Prioritize:
- Strong curiosity
- Easy to explain in 30–45 seconds
- Visually interesting footage
- A surprising fact or mechanism
- Factual accuracy
- Topics that work with stock footage

Avoid:
- Politics
- Current political controversies
- Medical advice
- Graphic violence
- Extremely depressing subjects
- Unsupported claims
- Topics requiring complicated calculations

Return ONLY valid JSON.

{{
  "selected_index": 0,
  "topic": "short topic description",
  "category": "history",
  "angle": "specific story angle",
  "source_summary": "brief factual basis"
}}

CANDIDATES:

{candidates}
"""


def build_candidates(on_this_day, trivia, state):
    candidates = []

    used_source_ids = set(
        str(x) for x in state.get("used_source_ids", [])
    )

    used_topic_keys = set(
        str(x) for x in state.get("used_topic_keys", [])
    )

    # Historical events
    for event in on_this_day:
        source_id = str(event["source_id"])

        if source_id in used_source_ids:
            continue

        candidates.append({
            "source_id": source_id,
            "type": "on_this_day",
            "category": "history",
            "topic": event["text"],
            "year": event.get("year"),
        })

    # Trivia
    for item in trivia:
        source_id = str(item["source_id"])

        if source_id in used_source_ids:
            continue

        candidates.append({
            "source_id": source_id,
            "type": "trivia",
            "category": item.get("category", "trivia"),
            "topic": item["question"],
            "answer": item["answer"],
        })

    # Evergreen
    for item in EVERGREEN_TOPICS:
        if item["key"] in used_topic_keys:
            continue

        candidates.append({
            "source_id": f"evergreen:{item['key']}",
            "type": "evergreen",
            "category": item["category"],
            "topic": item["topic"],
            "key": item["key"],
        })

    random.shuffle(candidates)

    # Prevent an enormous prompt
    return candidates[:80]


def select_topic(state):
    print("[SpaceFacts] Fetching a fresh topic...")

    today = datetime.now(timezone.utc)

    try:
        on_this_day = fetch_on_this_day()
    except Exception as e:
        print(
            f"[SpaceFacts] On This Day fetch failed: {e}"
        )
        on_this_day = []

    try:
        trivia = fetch_trivia()
    except Exception as e:
        print(
            f"[SpaceFacts] Trivia fetch failed: {e}"
        )
        trivia = []

    candidates = build_candidates(
        on_this_day,
        trivia,
        state,
    )

    if not candidates:
        unused = [
            item
            for item in EVERGREEN_TOPICS
            if item["key"] not in state.get("used_topic_keys", [])
        ]

        if not unused:
            state["used_topic_keys"] = []

            unused = EVERGREEN_TOPICS.copy()

        item = random.choice(unused)

        return {
            "source_id": f"evergreen:{item['key']}",
            "type": "evergreen",
            "category": item["category"],
            "topic": item["topic"],
            "angle": item["topic"],
            "source_summary": item["topic"],
            "topic_key": item["key"],
        }

    candidate_text = json.dumps(
        candidates,
        indent=2,
        ensure_ascii=False,
    )

    prompt = TOPIC_SELECTOR_PROMPT.format(
        candidates=candidate_text
    )

    raw = gemini_generate(
        prompt,
        temperature=0.75,
    )

    result = safe_json_loads(raw)

    selected_index = result.get("selected_index", 0)

    try:
        selected_index = int(selected_index)
    except Exception:
        selected_index = 0

    selected_index = max(
        0,
        min(
            selected_index,
            len(candidates) - 1,
        ),
    )

    selected = candidates[selected_index]

    source_id = str(selected["source_id"])

    topic_key = selected.get("key")

    if not topic_key and selected["type"] == "evergreen":
        topic_key = source_id.replace(
            "evergreen:",
            "",
        )

    topic = {
        "source_id": source_id,
        "type": selected["type"],
        "category": selected.get(
            "category",
            "general",
        ),
        "topic": result.get(
            "topic",
            selected["topic"],
        ),
        "angle": result.get(
            "angle",
            selected["topic"],
        ),
        "source_summary": result.get(
            "source_summary",
            selected["topic"],
        ),
        "topic_key": topic_key,
        "year": selected.get("year"),
        "answer": selected.get("answer"),
        "date": f"{today.month:02d}/{today.day:02d}",
    }

    print(
        f"[SpaceFacts] Selected topic: {topic['topic']}"
    )

    return topic


# ============================================================
# SCRIPT GENERATION
# ============================================================

SCRIPT_PROMPT = """
You write scripts for a fast-paced YouTube Shorts channel.

Create a factual 30–45 second Short.

TOPIC:
{topic}

CATEGORY:
{category}

ANGLE:
{angle}

SOURCE BASIS:
{source_summary}

SOURCE TYPE:
{source_type}

Requirements:

1. Narration must be 85–115 spoken words.
2. Start immediately with a strong curiosity hook.
3. Use short spoken sentences.
4. No intro such as "Hey guys".
5. No "welcome back".
6. Explain the interesting part clearly.
7. End with either:
   - a loop,
   - a question,
   - or a punchline.
8. Do not invent facts.
9. Avoid unsupported superlatives.
10. Keep it understandable for a general audience.
11. The narration should sound natural when spoken by TTS.
12. Generate 3–5 visual search queries suitable for stock footage.
13. Captions should be short, punchy phrases of 2–5 words.
14. Captions must be uppercase.
15. Maximum 8 scenes.

Each scene must contain:
- narration
- caption

Return ONLY valid JSON:

{{
  "title": "Short YouTube title",
  "hook": "Opening hook",
  "ending_style": "loop",
  "footage_style": "construction",
  "visual_search_queries": [
    "search query 1",
    "search query 2",
    "search query 3"
  ],
  "scenes": [
    {{
      "narration": "spoken narration",
      "caption": "SHORT CAPTION"
    }}
  ],
  "hashtags": [
    "#shorts",
    "#facts"
  ]
}}
"""


def validate_script(script):
    if not isinstance(script, dict):
        raise ValueError("Script is not a JSON object.")

    title = clean_text(script.get("title"))

    if not title:
        raise ValueError("Script title is empty.")

    if len(title) > 60:
        title = title[:57].rstrip() + "..."

    script["title"] = title

    scenes = script.get("scenes")

    if not isinstance(scenes, list):
        raise ValueError("Scenes must be a list.")

    if not scenes:
        raise ValueError("No scenes generated.")

    if len(scenes) > MAX_SCENES:
        script["scenes"] = scenes[:MAX_SCENES]

    total_words = 0

    cleaned_scenes = []

    for scene in script["scenes"]:
        narration = clean_text(
            scene.get("narration")
        )

        caption = clean_text(
            scene.get("caption")
        ).upper()

        if not narration:
            continue

        caption_words = caption.split()

        if len(caption_words) > 6:
            caption = " ".join(
                caption_words[:6]
            )

        total_words += len(
            narration.split()
        )

        cleaned_scenes.append({
            "narration": narration,
            "caption": caption,
        })

    if not cleaned_scenes:
        raise ValueError("All scenes were empty.")

    script["scenes"] = cleaned_scenes

    if total_words < 70:
        raise ValueError(
            f"Generated narration is too short: "
            f"{total_words} words."
        )

    if total_words > 140:
        raise ValueError(
            f"Generated narration is too long: "
            f"{total_words} words."
        )

    footage_style = clean_text(
        script.get("footage_style")
    ).lower()

    if footage_style not in FOOTAGE_STYLES:
        footage_style = "general"

    script["footage_style"] = footage_style

    queries = script.get(
        "visual_search_queries",
        [],
    )

    if not isinstance(queries, list):
        queries = []

    queries = [
        clean_text(q)
        for q in queries
        if clean_text(q)
    ]

    queries = queries[:5]

    if not queries:
        queries = [
            footage_style,
            "interesting technology",
            "modern architecture",
        ]

    script["visual_search_queries"] = queries

    ending_style = clean_text(
        script.get("ending_style")
    ).lower()

    if ending_style not in [
        "loop",
        "question",
        "punchline",
    ]:
        ending_style = "loop"

    script["ending_style"] = ending_style

    hashtags = script.get("hashtags", [])

    if not isinstance(hashtags, list):
        hashtags = []

    hashtags = [
        clean_text(tag)
        for tag in hashtags
        if clean_text(tag)
    ]

    if "#shorts" not in [
        x.lower() for x in hashtags
    ]:
        hashtags.insert(0, "#shorts")

    if "#facts" not in [
        x.lower() for x in hashtags
    ]:
        hashtags.append("#facts")

    script["hashtags"] = hashtags[:8]

    return script


def generate_script(topic):
    print("[SpaceFacts] Generating Shorts script...")

    prompt = SCRIPT_PROMPT.format(
        topic=topic["topic"],
        category=topic.get("category", "general"),
        angle=topic.get("angle", topic["topic"]),
        source_summary=topic.get(
            "source_summary",
            "",
        ),
        source_type=topic.get(
            "type",
            "evergreen",
        ),
    )

    raw = gemini_generate(
        prompt,
        temperature=0.85,
    )

    script = safe_json_loads(raw)

    script = validate_script(script)

    word_count = sum(
        len(scene["narration"].split())
        for scene in script["scenes"]
    )

    print(
        f"[SpaceFacts] Generated {word_count} narration words."
    )

    print(
        f"[SpaceFacts] Title: {script['title']}"
    )

    print(
        "[SpaceFacts] Visual queries: "
        + ", ".join(
            script["visual_search_queries"]
        )
    )

    return script


# ============================================================
# EDGE TTS
# ============================================================

async def synthesize_tts_async(text, output_path):
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=TTS_VOICE,
        rate="+2%",
        pitch="+0Hz",
    )

    await communicate.save(str(output_path))


def synthesize_tts(text, output_path):
    import asyncio

    asyncio.run(
        synthesize_tts_async(
            text,
            output_path,
        )
    )


def generate_scene_audio(scenes, work_dir):
    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_files = []

    for index, scene in enumerate(scenes):
        print(
            f"[SpaceFacts] Synthesizing scene "
            f"{index + 1}/{len(scenes)}"
        )

        output = (
            work_dir
            / f"scene_{index + 1:02d}.mp3"
        )

        synthesize_tts(
            scene["narration"],
            output,
        )

        audio_files.append(output)

    return audio_files


# ============================================================
# COVERR
# ============================================================

def coverr_headers():
    return {
        "x-api-key": COVERR_API_KEY,
        "Accept": "application/json",
        "User-Agent": "SpaceFactsPipeline/9.3",
    }


def recursive_find_url(obj):
    """
    Recursively search a Coverr API response for a likely
    downloadable video URL.
    """

    preferred_keys = [
        "download_url",
        "downloadUrl",
        "video_url",
        "videoUrl",
        "file_url",
        "fileUrl",
        "src",
        "url",
    ]

    if isinstance(obj, dict):

        for key in preferred_keys:
            value = obj.get(key)

            if isinstance(value, str):
                lowered = value.lower()

                if (
                    lowered.startswith("http://")
                    or lowered.startswith("https://")
                ):
                    return value

        for value in obj.values():
            found = recursive_find_url(value)

            if found:
                return found

    elif isinstance(obj, list):

        for value in obj:
            found = recursive_find_url(value)

            if found:
                return found

    return None


def extract_coverr_videos(data):
    if not isinstance(data, dict):
        return []

    possible_keys = [
        "videos",
        "results",
        "data",
        "items",
    ]

    for key in possible_keys:
        value = data.get(key)

        if isinstance(value, list):
            return value

    return []


def coverr_search(query, limit=10):
    if not COVERR_API_KEY:
        print(
            "[SpaceFacts] COVERR_API_KEY is missing."
        )
        return []

    params = {
        "query": query,
        "page_size": min(
            max(limit, 1),
            20,
        ),
    }

    try:
        response = requests.get(
            COVERR_API_URL,
            headers=coverr_headers(),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code in [401, 403]:
            print(
                "[SpaceFacts] Coverr authentication failed. "
                "Check COVERR_API_KEY."
            )
            return []

        response.raise_for_status()

        data = response.json()

        return extract_coverr_videos(data)

    except Exception as e:
        print(
            f"[SpaceFacts] Coverr search failed for "
            f"'{query}': {e}"
        )
        return []


def coverr_detail(video_id):
    if not video_id:
        return {}

    url = (
        f"https://api.coverr.co/videos/"
        f"{quote(str(video_id), safe='')}"
    )

    try:
        response = requests.get(
            url,
            headers=coverr_headers(),
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code in [401, 403]:
            print(
                "[SpaceFacts] Coverr authentication failed "
                "while fetching video details."
            )
            return {}

        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(
            f"[SpaceFacts] Coverr detail request failed: {e}"
        )
        return {}


def get_coverr_id(item):
    if not isinstance(item, dict):
        return None

    for key in [
        "id",
        "video_id",
        "videoId",
        "uuid",
    ]:
        value = item.get(key)

        if value is not None:
            return str(value)

    return None


def get_coverr_media_url(item):
    if not isinstance(item, dict):
        return None

    direct = recursive_find_url(item)

    if direct:
        return direct

    video_id = get_coverr_id(item)

    if video_id:
        detail = coverr_detail(video_id)

        if detail:
            direct = recursive_find_url(detail)

            if direct:
                return direct

    return None


def download_coverr_video(item):
    video_id = get_coverr_id(item)

    if not video_id:
        video_id = hash_text(
            json.dumps(
                item,
                sort_keys=True,
                default=str,
            )
        )

    filename = (
        f"coverr_{slugify(video_id)}.mp4"
    )

    destination = (
        COVERR_DOWNLOAD_DIR
        / filename
    )

    if destination.exists() and destination.stat().st_size > 10000:
        return destination

    media_url = get_coverr_media_url(item)

    if not media_url:
        return None

    print(
        f"[SpaceFacts] Downloading Coverr clip "
        f"{video_id}..."
    )

    temp_path = destination.with_suffix(
        ".tmp"
    )

    try:
        with requests.get(
            media_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "SpaceFactsPipeline/9.3"
            },
        ) as response:

            response.raise_for_status()

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        f.write(chunk)

        if (
            not temp_path.exists()
            or temp_path.stat().st_size < 10000
        ):
            temp_path.unlink(
                missing_ok=True
            )
            return None

        temp_path.replace(destination)

        return destination

    except Exception as e:
        print(
            f"[SpaceFacts] Coverr download failed: {e}"
        )

        temp_path.unlink(
            missing_ok=True
        )

        return None


def select_coverr_clips(
    queries,
    required_count,
    state,
):
    if not COVERR_API_KEY:
        return []

    print(
        f"[SpaceFacts] Searching Coverr for "
        f"{required_count} clips..."
    )

    used_source_ids = set(
        str(x)
        for x in state.get(
            "used_source_ids",
            [],
        )
    )

    selected = []
    seen_ids = set()

    for query in queries:

        if len(selected) >= required_count:
            break

        results = coverr_search(
            query,
            limit=10,
        )

        for item in results:

            if len(selected) >= required_count:
                break

            video_id = get_coverr_id(item)

            if not video_id:
                continue

            video_id = str(video_id)

            if video_id in seen_ids:
                continue

            if video_id in used_source_ids:
                continue

            seen_ids.add(video_id)

            path = download_coverr_video(item)

            if not path:
                continue

            selected.append({
                "path": path,
                "source_id": video_id,
                "source": "coverr",
                "query": query,
            })

    return selected


# ============================================================
# LOCAL FOOTAGE FALLBACK
# ============================================================

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
}


def get_footage_root():
    if FOOTAGE_DIR.exists():
        return FOOTAGE_DIR

    if GAMEPLAY_DIR.exists():
        return GAMEPLAY_DIR

    return None


def list_local_footage():
    root = get_footage_root()

    if not root:
        return []

    files = []

    for path in root.rglob("*"):
        if (
            path.is_file()
            and path.suffix.lower()
            in VIDEO_EXTENSIONS
        ):
            files.append(path)

    return files


def score_local_footage(
    path,
    style,
):
    path_text = str(path).lower()

    score = 0

    if style and style in path_text:
        score += 10

    keywords = {
        "construction": [
            "construction",
            "building",
            "crane",
            "concrete",
        ],
        "machines": [
            "machine",
            "machinery",
            "factory",
            "engine",
        ],
        "cars": [
            "car",
            "vehicle",
            "driving",
            "race",
        ],
        "nature": [
            "nature",
            "forest",
            "mountain",
            "animal",
        ],
        "satisfying": [
            "satisfying",
            "oddly",
            "clean",
            "asmr",
        ],
        "sports": [
            "sport",
            "football",
            "basketball",
            "running",
        ],
        "animation": [
            "animation",
            "animated",
            "cgi",
        ],
        "ocean": [
            "ocean",
            "sea",
            "underwater",
            "water",
        ],
        "aviation": [
            "airplane",
            "aircraft",
            "aviation",
            "jet",
        ],
    }

    for keyword in keywords.get(style, []):
        if keyword in path_text:
            score += 3

    return score


def select_local_footage(
    style,
    count,
    state,
):
    files = list_local_footage()

    if not files:
        return []

    used = set(
        str(x)
        for x in state.get(
            "used_gameplay",
            [],
        )
    )

    ranked = sorted(
        files,
        key=lambda p: score_local_footage(
            p,
            style,
        ),
        reverse=True,
    )

    unused = [
        path
        for path in ranked
        if str(path) not in used
    ]

    if not unused:
        # Reset local usage when every file has been used.
        state["used_gameplay"] = []
        unused = ranked

    selected = unused[:count]

    return [
        {
            "path": path,
            "source_id": f"local:{hash_text(str(path))}",
            "source": "local",
            "query": style,
        }
        for path in selected
    ]


def select_footage(
    script,
    state,
):
    queries = script.get(
        "visual_search_queries",
        [],
    )

    scene_count = len(
        script.get("scenes", [])
    )

    required_count = min(
        max(3, scene_count),
        5,
    )

    coverr_clips = select_coverr_clips(
        queries,
        required_count,
        state,
    )

    if coverr_clips:
        print(
            f"[SpaceFacts] Coverr provided "
            f"{len(coverr_clips)} clips."
        )

    if len(coverr_clips) < required_count:

        print(
            f"[SpaceFacts] Coverr only returned "
            f"{len(coverr_clips)} clips. "
            f"Trying local fallback."
        )

        needed = (
            required_count
            - len(coverr_clips)
        )

        local_clips = select_local_footage(
            script.get(
                "footage_style",
                "general",
            ),
            needed,
            state,
        )

        coverr_clips.extend(
            local_clips
        )

    if not coverr_clips:
        raise RuntimeError(
            "No footage available. "
            "Add footage to the footage/ folder "
            "or fix COVERR_API_KEY."
        )

    print(
        f"[SpaceFacts] Using "
        f"{len(coverr_clips)} footage clips."
    )

    return coverr_clips


# ============================================================
# CAPTION IMAGE
# ============================================================

def make_caption_image(
    text,
    output_path,
):
    from PIL import ImageDraw, ImageFont

    image = Image.new(
        "RGBA",
        (VIDEO_W, 300),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype(
            CAPTION_FONT_PATH,
            82,
        )
    except Exception:
        font = ImageFont.load_default()

    text = text.upper()

    max_width = VIDEO_W - 120

    # Wrap caption manually
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = (
            f"{current} {word}"
            if current
            else word
        )

        bbox = draw.textbbox(
            (0, 0),
            test,
            font=font,
            stroke_width=3,
        )

        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    lines = lines[:3]

    line_heights = []

    for line in lines:
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=3,
        )

        line_heights.append(
            bbox[3] - bbox[1]
        )

    total_height = (
        sum(line_heights)
        + max(0, len(lines) - 1) * 12
    )

    y = (
        150
        - total_height / 2
    )

    for line, height in zip(
        lines,
        line_heights,
    ):
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=3,
        )

        width = bbox[2] - bbox[0]

        x = (
            VIDEO_W - width
        ) / 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=8,
            stroke_fill="black",
        )

        y += height + 12

    image.save(
        output_path,
        "PNG",
    )


# ============================================================
# VIDEO FOOTAGE PREPARATION
# ============================================================

def prepare_footage_clip(
    path,
    duration,
):
    clip = VideoFileClip(
        str(path)
    )

    # Remove audio from stock footage.
    # Narration is the primary audio.
    try:
        clip = clip.without_audio()
    except Exception:
        pass

    if clip.duration <= 0:
        raise ValueError(
            f"Invalid footage duration: {path}"
        )

    # If source clip is shorter than requested,
    # loop it.
    if clip.duration < duration:

        repeats = int(
            duration / clip.duration
        ) + 1

        copies = []

        for _ in range(repeats):
            copies.append(
                clip.copy()
            )

        prepared = concatenate_videoclips(
            copies,
            method="compose",
        )

        prepared = prepared.subclip(
            0,
            duration,
        )

        # Close the original after creating copies.
        try:
            clip.close()
        except Exception:
            pass

    else:
        max_start = max(
            0,
            clip.duration - duration,
        )

        if max_start > 0:
            start = random.uniform(
                0,
                max_start,
            )
        else:
            start = 0

        prepared = clip.subclip(
            start,
            start + duration,
        )

    # Crop source into a vertical 9:16 frame.
    source_ratio = (
        prepared.w
        / prepared.h
    )

    target_ratio = (
        VIDEO_W
        / VIDEO_H
    )

    if source_ratio > target_ratio:

        new_width = (
            prepared.h
            * target_ratio
        )

        x1 = (
            prepared.w
            - new_width
        ) / 2

        prepared = prepared.crop(
            x1=x1,
            x2=x1 + new_width,
        )

    else:

        new_height = (
            prepared.w
            / target_ratio
        )

        y1 = (
            prepared.h
            - new_height
        ) / 2

        prepared = prepared.crop(
            y1=y1,
            y2=y1 + new_height,
        )

    prepared = prepared.resize(
        newsize=(
            VIDEO_W,
            VIDEO_H,
        )
    )

    return prepared


# ============================================================
# BUILD VIDEO
# ============================================================

def build_video(
    script,
    footage,
    audio_files,
    work_dir,
):
    print(
        "[SpaceFacts] Building final vertical video..."
    )

    scenes = script["scenes"]

    audio_clips = []

    for audio_path in audio_files:
        audio = AudioFileClip(
            str(audio_path)
        )

        audio_clips.append(audio)

    # Determine scene durations from narration audio.
    scene_durations = [
        audio.duration
        for audio in audio_clips
    ]

    total_narration_duration = sum(
        scene_durations
    )

    # Keep Shorts between 30 and 45 seconds.
    target_duration = min(
        max(
            total_narration_duration,
            TARGET_MIN_SECONDS,
        ),
        TARGET_MAX_SECONDS,
    )

    # If narration somehow exceeds 45 seconds,
    # proportionally scale scene durations.
    if total_narration_duration > target_duration:
        scale = (
            target_duration
            / total_narration_duration
        )

        scene_durations = [
            d * scale
            for d in scene_durations
        ]

    print(
        f"[SpaceFacts] Final narration duration: "
        f"{target_duration:.2f}s"
    )

    video_scene_clips = []

    caption_dir = (
        work_dir
        / "captions"
    )

    caption_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for index, (
        scene,
        duration,
    ) in enumerate(
        zip(
            scenes,
            scene_durations,
        )
    ):

        footage_info = footage[
            index % len(footage)
        ]

        footage_path = Path(
            footage_info["path"]
        )

        print(
            f"[SpaceFacts] Preparing footage "
            f"{index + 1}/{len(scenes)}: "
            f"{footage_path.name}"
        )

        prepared = prepare_footage_clip(
            footage_path,
            duration,
        )

        caption_path = (
            caption_dir
            / f"caption_{index + 1:02d}.png"
        )

        make_caption_image(
            scene["caption"],
            caption_path,
        )

        caption_clip = (
            ImageClip(
                str(caption_path)
            )
            .set_duration(duration)
            .set_position(
                ("center", "center")
            )
        )

        composite = CompositeVideoClip(
            [
                prepared,
                caption_clip,
            ],
            size=(
                VIDEO_W,
                VIDEO_H,
            ),
        ).set_duration(duration)

        video_scene_clips.append(
            composite
        )

    final_video = concatenate_videoclips(
        video_scene_clips,
        method="compose",
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    current_time = 0

    positioned_audio = []

    for audio in audio_clips:

        remaining = (
            target_duration
            - current_time
        )

        if remaining <= 0:
            break

        duration = min(
            audio.duration,
            remaining,
        )

        audio_segment = (
            audio
            .subclip(
                0,
                duration,
            )
            .set_start(current_time)
        )

        positioned_audio.append(
            audio_segment
        )

        current_time += duration

    # Optional background music.
    bgm_clip = None

    if BGM_DIR.exists():

        bgm_files = [
            p
            for p in BGM_DIR.iterdir()
            if p.is_file()
            and p.suffix.lower()
            in {
                ".mp3",
                ".wav",
                ".m4a",
            }
        ]

        if bgm_files:

            try:
                selected_bgm = random.choice(
                    bgm_files
                )

                bgm_clip = AudioFileClip(
                    str(selected_bgm)
                )

                if bgm_clip.duration < target_duration:

                    repeats = int(
                        target_duration
                        / bgm_clip.duration
                    ) + 1

                    bgm_parts = [
                        bgm_clip.copy()
                        for _ in range(repeats)
                    ]

                    bgm_loop = concatenate_videoclips(
                        [],
                        method="compose",
                    ) if False else None

                    # Use audio clips directly.
                    from moviepy.audio.AudioClip import concatenate_audioclips

                    bgm_combined = (
                        concatenate_audioclips(
                            bgm_parts
                        )
                        .subclip(
                            0,
                            target_duration,
                        )
                    )

                    try:
                        bgm_clip.close()
                    except Exception:
                        pass

                    bgm_clip = bgm_combined

                else:
                    bgm_clip = bgm_clip.subclip(
                        0,
                        target_duration,
                    )

                bgm_clip = bgm_clip.volumex(
                    0.06
                )

                positioned_audio.append(
                    bgm_clip
                )

            except Exception as e:
                print(
                    f"[SpaceFacts] BGM failed: {e}"
                )

                bgm_clip = None

    if positioned_audio:

        final_audio = CompositeAudioClip(
            positioned_audio
        )

        final_video = final_video.set_audio(
            final_audio
        )

    output_name = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        f"_{slugify(script['title'])}.mp4"
    )

    output_path = (
        OUTPUT_DIR
        / output_name
    )

    print(
        f"[SpaceFacts] Rendering: {output_path}"
    )

    final_video.write_videofile(
        str(output_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        bitrate="8M",
        audio_bitrate="192k",
        threads=2,
        preset="medium",
        logger="bar",
    )

    # Cleanup
    try:
        final_video.close()
    except Exception:
        pass

    for clip in video_scene_clips:
        try:
            clip.close()
        except Exception:
            pass

    for audio in audio_clips:
        try:
            audio.close()
        except Exception:
            pass

    if bgm_clip:
        try:
            bgm_clip.close()
        except Exception:
            pass

    return output_path


# ============================================================
# DESCRIPTION
# ============================================================

def build_description(
    script,
    topic,
):
    hashtags = script.get(
        "hashtags",
        [],
    )

    hashtag_text = " ".join(
        hashtags
    )

    source_text = ""

    if topic.get("type") == "on_this_day":
        source_text = (
            "Source: Wikimedia / Wikipedia "
            "On This Day."
        )

    elif topic.get("type") == "trivia":
        source_text = (
            "Source: Open Trivia Database."
        )

    else:
        source_text = (
            "Source: General educational references."
        )

    return f"""Interesting facts, history, science and technology in under a minute.

{source_text}

Footage provided by Coverr.
{COVERR_BASE_URL}

{hashtag_text}
"""


# ============================================================
# UPLOAD
# ============================================================

def upload_to_youtube(
    video_path,
    script,
    topic,
):
    print(
        "[SpaceFacts] Uploading to YouTube..."
    )

    from youtube_upload import upload_video

    description = build_description(
        script,
        topic,
    )

    tags = [
        "shorts",
        "facts",
        "interesting facts",
        "history",
        "science",
        "trivia",
        "technology",
    ]

    # Add topic words as tags.
    topic_words = re.findall(
        r"[A-Za-z0-9]+",
        script["title"].lower(),
    )

    for word in topic_words:
        if len(word) >= 3 and word not in tags:
            tags.append(word)

    result = upload_video(
        video_path=str(video_path),
        title=script["title"],
        description=description,
        tags=tags,
        privacy_status="public",
    )

    return result


# ============================================================
# UPLOAD LOG
# ============================================================

def append_upload_log(
    video_path,
    script,
    topic,
    upload_result,
):
    entry = {
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "version": VERSION,
        "video": str(video_path),
        "title": script["title"],
        "topic": topic.get("topic"),
        "source_type": topic.get("type"),
        "source_id": topic.get("source_id"),
        "upload_result": upload_result,
    }

    with open(
        UPLOAD_LOG_FILE,
        "a",
        encoding="utf-8",
    ) as f:

        f.write(
            json.dumps(
                entry,
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )


# ============================================================
# STATE UPDATE
# ============================================================

def update_state_after_success(
    state,
    topic,
    script,
    footage,
):
    source_id = topic.get(
        "source_id"
    )

    if source_id:
        source_ids = state.setdefault(
            "used_source_ids",
            [],
        )

        if source_id not in source_ids:
            source_ids.append(
                source_id
            )

        # Keep state manageable.
        state["used_source_ids"] = (
            source_ids[-200:]
        )

    topic_key = topic.get(
        "topic_key"
    )

    if topic_key:
        topic_keys = state.setdefault(
            "used_topic_keys",
            [],
        )

        if topic_key not in topic_keys:
            topic_keys.append(
                topic_key
            )

        state["used_topic_keys"] = (
            topic_keys[-200:]
        )

    title = script.get(
        "title"
    )

    if title:
        recent_titles = state.setdefault(
            "recent_titles",
            [],
        )

        recent_titles.append(
            title
        )

        state["recent_titles"] = (
            recent_titles[-40:]
        )

    used_gameplay = state.setdefault(
        "used_gameplay",
        [],
    )

    for item in footage:

        if item.get("source") != "local":
            continue

        source_id = item.get(
            "source_id"
        )

        if (
            source_id
            and source_id not in used_gameplay
        ):
            used_gameplay.append(
                source_id
            )

    state["used_gameplay"] = (
        used_gameplay[-200:]
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print(
        f"SPACE FACTS PIPELINE {VERSION}"
    )
    print(
        "COVERR MULTI-CLIP SHORTS FORMAT"
    )
    print("=" * 60)

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured."
        )

    state = load_state()

    work_id = (
        datetime.now()
        .strftime("%Y%m%d_%H%M%S")
        + "_"
        + str(random.randint(1000, 9999))
    )

    work_dir = (
        OUTPUT_DIR
        / f"work_{work_id}"
    )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        # ----------------------------------------------------
        # 1. SELECT TOPIC
        # ----------------------------------------------------

        topic = select_topic(
            state
        )

        # ----------------------------------------------------
        # 2. GENERATE SCRIPT
        # ----------------------------------------------------

        script = generate_script(
            topic
        )

        # ----------------------------------------------------
        # 3. GET FOOTAGE
        # ----------------------------------------------------

        footage = select_footage(
            script,
            state,
        )

        # ----------------------------------------------------
        # 4. GENERATE TTS
        # ----------------------------------------------------

        audio_dir = (
            work_dir
            / "audio"
        )

        audio_files = generate_scene_audio(
            script["scenes"],
            audio_dir,
        )

        # ----------------------------------------------------
        # 5. BUILD VIDEO
        # ----------------------------------------------------

        video_path = build_video(
            script,
            footage,
            audio_files,
            work_dir,
        )

        # ----------------------------------------------------
        # 6. UPLOAD
        # ----------------------------------------------------

        upload_result = upload_to_youtube(
            video_path,
            script,
            topic,
        )

        print(
            "[SpaceFacts] YouTube upload completed."
        )

        # ----------------------------------------------------
        # 7. LOG SUCCESS
        # ----------------------------------------------------

        append_upload_log(
            video_path,
            script,
            topic,
            upload_result,
        )

        # ----------------------------------------------------
        # 8. ONLY NOW UPDATE STATE
        # ----------------------------------------------------

        update_state_after_success(
            state,
            topic,
            script,
            footage,
        )

        save_state(
            state
        )

        print(
            "[SpaceFacts] State saved after successful upload."
        )

        print("=" * 60)
        print(
            "[SpaceFacts] PIPELINE COMPLETED SUCCESSFULLY"
        )
        print("=" * 60)

    except Exception as e:

        print("=" * 60)
        print(
            "[SpaceFacts] PIPELINE FAILED"
        )
        print(
            f"[SpaceFacts] Error: {e}"
        )
        print("=" * 60)

        # Do NOT save state here.
        # This prevents failed videos from being marked
        # as successfully used topics.

        raise

    finally:

        # Remove temporary working files.
        # Keep the final MP4 in output_spacefacts.
        try:
            import shutil

            if work_dir.exists():
                shutil.rmtree(
                    work_dir,
                    ignore_errors=True,
                )

        except Exception as e:
            print(
                f"[SpaceFacts] Work directory cleanup "
                f"failed: {e}"
            )


if __name__ == "__main__":
    main()