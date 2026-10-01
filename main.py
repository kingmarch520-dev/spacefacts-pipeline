"""
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v9)

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
    1. Fetch fresh On This Day events / trivia / evergreen topics
    2. Gemini selects a strong topic
    3. Gemini writes a 30–45 second story
    4. Gemini generates visual search queries
    5. Coverr searches for multiple matching clips
    6. Edge TTS generates narration
    7. MoviePy creates a 1080x1920 Short
    8. Dynamic captions are added
    9. Video is uploaded to YouTube
   10. State is saved only after successful upload

REQUIRED ENVIRONMENT VARIABLES:
    GEMINI_API_KEY
    COVERR_API_KEY
    YT_CLIENT_ID
    YT_CLIENT_SECRET
    YT_REFRESH_TOKEN

OPTIONAL:
    FOOTAGE_DIR
    BGM_DIR
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# CONFIG
# ============================================================

VERSION = "v9"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
COVERR_API_KEY = os.environ.get("COVERR_API_KEY", "")

STATE_FILE = Path("state_spacefacts.json")
UPLOAD_LOG_FILE = Path("upload_log.jsonl")

OUTPUT_DIR = Path("output_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)

FOOTAGE_DIR = Path(
    os.environ.get("FOOTAGE_DIR", "footage")
)

GAMEPLAY_DIR = Path(
    os.environ.get("GAMEPLAY_DIR", "gameplay")
)

COVERR_DOWNLOAD_DIR = Path("downloaded_footage")
COVERR_DOWNLOAD_DIR.mkdir(exist_ok=True)

BGM_DIR = Path(
    os.environ.get("BGM_DIR", "bgm")
)

VIDEO_W = 1080
VIDEO_H = 1920

CAPTION_FONT_PATH = str(
    Path(__file__).parent / "Anton-Regular.ttf"
)

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
# TOPIC DATABASE
# ============================================================

EVERGREEN_TOPICS = [
    # HISTORY
    {
        "key": "history_roman_concrete",
        "category": "history",
        "topic": "Why Roman concrete survived for thousands of years",
    },
    {
        "key": "history_ancient_egypt_cats",
        "category": "history",
        "topic": "Why cats were important in ancient Egypt",
    },
    {
        "key": "history_viking_navigation",
        "category": "history",
        "topic": "How Vikings navigated without modern instruments",
    },
    {
        "key": "history_pompeii",
        "category": "history",
        "topic": "What happened to Pompeii during the eruption of Vesuvius",
    },
    {
        "key": "history_titanic",
        "category": "history",
        "topic": "Why the Titanic sank so quickly",
    },
    {
        "key": "history_telegraph",
        "category": "history",
        "topic": "How the telegraph changed communication",
    },
    {
        "key": "history_black_death",
        "category": "history",
        "topic": "How the Black Death changed medieval Europe",
    },
    {
        "key": "history_great_fire_london",
        "category": "history",
        "topic": "How the Great Fire of London spread",
    },

    # SCIENCE
    {
        "key": "science_lightning",
        "category": "science",
        "topic": "How lightning becomes hotter than the surface of the Sun",
    },
    {
        "key": "science_ocean_depth",
        "category": "science",
        "topic": "What happens to a human body at extreme ocean depth",
    },
    {
        "key": "science_black_holes",
        "category": "science",
        "topic": "What would happen near a black hole",
    },
    {
        "key": "science_banana_radiation",
        "category": "science",
        "topic": "Why bananas are slightly radioactive",
    },
    {
        "key": "science_sound_space",
        "category": "science",
        "topic": "Why sound cannot travel through empty space",
    },
    {
        "key": "science_sharks",
        "category": "science",
        "topic": "Why sharks can detect electrical signals",
    },
    {
        "key": "science_ant_strength",
        "category": "science",
        "topic": "Why ants can carry many times their own body weight",
    },
    {
        "key": "science_time_dilation",
        "category": "science",
        "topic": "How time changes at extremely high speeds",
    },

    # ENGINEERING
    {
        "key": "engineering_bridges",
        "category": "engineering",
        "topic": "How suspension bridges stay standing",
    },
    {
        "key": "engineering_tall_buildings",
        "category": "engineering",
        "topic": "How skyscrapers survive strong winds",
    },
    {
        "key": "engineering_dams",
        "category": "engineering",
        "topic": "How massive dams hold back millions of tons of water",
    },
    {
        "key": "engineering_tunnels",
        "category": "engineering",
        "topic": "How engineers build tunnels underground",
    },
    {
        "key": "engineering_cranes",
        "category": "engineering",
        "topic": "How tower cranes can lift enormous loads",
    },
    {
        "key": "engineering_bulldozers",
        "category": "engineering",
        "topic": "How bulldozers generate so much pushing force",
    },

    # TECHNOLOGY
    {
        "key": "technology_microchips",
        "category": "technology",
        "topic": "How billions of transistors fit inside a tiny chip",
    },
    {
        "key": "technology_fiber_optics",
        "category": "technology",
        "topic": "How fiber optic cables send data using light",
    },
    {
        "key": "technology_gps",
        "category": "technology",
        "topic": "How GPS knows where you are",
    },
    {
        "key": "technology_smartphones",
        "category": "technology",
        "topic": "How smartphones communicate with cell towers",
    },

    # TRANSPORT
    {
        "key": "transport_jet_engine",
        "category": "transport",
        "topic": "How a jet engine produces enormous thrust",
    },
    {
        "key": "transport_supersonic",
        "category": "transport",
        "topic": "What happens when an aircraft breaks the sound barrier",
    },
    {
        "key": "transport_train_brakes",
        "category": "transport",
        "topic": "How enormous trains stop safely",
    },
    {
        "key": "transport_container_ship",
        "category": "transport",
        "topic": "How container ships carry thousands of containers",
    },

    # ANIMALS / NATURE
    {
        "key": "nature_octopus",
        "category": "nature",
        "topic": "Why octopuses have three hearts",
    },
    {
        "key": "nature_crows",
        "category": "nature",
        "topic": "Why crows are surprisingly intelligent",
    },
    {
        "key": "nature_birds_migration",
        "category": "nature",
        "topic": "How birds navigate during long migrations",
    },
    {
        "key": "nature_volcanoes",
        "category": "nature",
        "topic": "What causes a volcano to erupt",
    },
    {
        "key": "nature_tornadoes",
        "category": "nature",
        "topic": "How powerful tornadoes form",
    },
    {
        "key": "nature_lightning",
        "category": "nature",
        "topic": "Why lightning strikes certain places more often",
    },
]


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def log(message: str) -> None:
    print(f"[SpaceFacts] {message}", flush=True)


def safe_json_loads(text: str) -> Any:
    """
    Attempts to recover JSON from Gemini responses.
    """
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL,
    )

    if match:
        return json.loads(match.group(0))

    raise ValueError("Could not extract valid JSON.")


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")[:80]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def run_command(
    command: List[str],
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


# ============================================================
# STATE
# ============================================================

def default_state() -> Dict[str, Any]:
    return {
        "recent_titles": [],
        "used_source_ids": [],
        "used_topic_keys": [],
        "used_gameplay": [],
    }


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return default_state()

    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return default_state()

        state = default_state()
        state.update(data)

        return state

    except Exception as exc:
        log(
            f"Could not load state file: {exc}"
        )
        return default_state()


def save_state(state: Dict[str, Any]) -> None:
    temp_file = STATE_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    temp_file.replace(STATE_FILE)


def remember_title(
    state: Dict[str, Any],
    title: str,
) -> None:
    titles = state.setdefault(
        "recent_titles",
        [],
    )

    titles.append(title)

    state["recent_titles"] = titles[-40:]


def remember_source(
    state: Dict[str, Any],
    source_id: str,
) -> None:
    if not source_id:
        return

    sources = state.setdefault(
        "used_source_ids",
        [],
    )

    if source_id not in sources:
        sources.append(source_id)

    state["used_source_ids"] = sources[-500:]


def remember_topic(
    state: Dict[str, Any],
    topic_key: str,
) -> None:
    if not topic_key:
        return

    topics = state.setdefault(
        "used_topic_keys",
        [],
    )

    if topic_key not in topics:
        topics.append(topic_key)

    state["used_topic_keys"] = topics[-500:]


def remember_footage(
    state: Dict[str, Any],
    path: str,
) -> None:
    if not path:
        return

    footage = state.setdefault(
        "used_gameplay",
        [],
    )

    if path not in footage:
        footage.append(path)

    state["used_gameplay"] = footage[-500:]


# ============================================================
# ENVIRONMENT
# ============================================================

def validate_environment() -> None:
    missing = []

    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")

    if not COVERR_API_KEY:
        missing.append("COVERR_API_KEY")

    if not os.environ.get("YT_CLIENT_ID"):
        missing.append("YT_CLIENT_ID")

    if not os.environ.get("YT_CLIENT_SECRET"):
        missing.append("YT_CLIENT_SECRET")

    if not os.environ.get("YT_REFRESH_TOKEN"):
        missing.append("YT_REFRESH_TOKEN")

    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )

    if not Path(CAPTION_FONT_PATH).exists():
        raise RuntimeError(
            f"Missing required font: "
            f"{CAPTION_FONT_PATH}"
        )


# ============================================================
# WIKIMEDIA ON THIS DAY
# ============================================================

def fetch_on_this_day() -> List[Dict[str, Any]]:
    """
    Fetches Wikimedia's On This Day events.

    Uses Wikipedia's REST API.
    """

    month = time.strftime("%m")
    day = time.strftime("%d")

    url = (
        "https://en.wikipedia.org/api/rest_v1/"
        f"feed/onthisday/events/{month}/{day}"
    )

    log(
        f"Fetching Wikimedia events for "
        f"{month}/{day}..."
    )

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                "SpaceFactsPipeline/9.0"
            },
        )

        response.raise_for_status()

        data = response.json()

        events = data.get(
            "events",
            [],
        )

        results = []

        for event in events:
            year = event.get("year")
            text = clean_text(
                event.get("text")
            )

            if not text:
                continue

            pages = event.get(
                "pages",
                [],
            )

            page_title = ""

            if pages:
                page_title = clean_text(
                    pages[0].get("title")
                )

            source_id = (
                f"wikimedia-{month}-"
                f"{day}-{year}-"
                f"{slugify(text)}"
            )

            results.append(
                {
                    "source_id": source_id,
                    "category": "history",
                    "year": year,
                    "topic": text,
                    "page_title": page_title,
                }
            )

        log(
            f"Found {len(results)} usable "
            f"historical events."
        )

        return results

    except Exception as exc:
        log(
            f"Wikimedia request failed: {exc}"
        )
        return []


# ============================================================
# OPEN TRIVIA DATABASE
# ============================================================

def fetch_trivia() -> List[Dict[str, Any]]:
    url = (
        "https://opentdb.com/api.php"
        "?amount=15"
        "&type=multiple"
    )

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                "SpaceFactsPipeline/9.0"
            },
        )

        response.raise_for_status()

        data = response.json()

        if data.get("response_code") != 0:
            return []

        import html

        results = []

        for index, item in enumerate(
            data.get("results", [])
        ):
            question = html.unescape(
                clean_text(
                    item.get("question")
                )
            )

            answer = html.unescape(
                clean_text(
                    item.get("correct_answer")
                )
            )

            category = clean_text(
                item.get("category")
            )

            if not question:
                continue

            results.append(
                {
                    "source_id": (
                        f"trivia-{slugify(question)}"
                    ),
                    "category": "trivia",
                    "topic": question,
                    "answer": answer,
                    "trivia_category": category,
                }
            )

        return results

    except Exception as exc:
        log(
            f"Trivia request failed: {exc}"
        )
        return []


# ============================================================
# TOPIC SELECTION
# ============================================================

def weighted_content_type() -> str:
    choices = list(
        CONTENT_WEIGHTS.keys()
    )

    weights = [
        CONTENT_WEIGHTS[x]
        for x in choices
    ]

    return random.choices(
        choices,
        weights=weights,
        k=1,
    )[0]


def build_candidates(
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:

    content_type = weighted_content_type()

    on_this_day = []
    trivia = []

    if content_type == "on_this_day":
        on_this_day = fetch_on_this_day()

    elif content_type == "trivia":
        trivia = fetch_trivia()

    evergreen = list(EVERGREEN_TOPICS)

    used_sources = set(
        state.get(
            "used_source_ids",
            [],
        )
    )

    used_topics = set(
        state.get(
            "used_topic_keys",
            [],
        )
    )

    candidates = []

    for item in on_this_day:
        if (
            item["source_id"]
            not in used_sources
        ):
            candidates.append(item)

    for item in trivia:
        if (
            item["source_id"]
            not in used_sources
        ):
            candidates.append(item)

    for item in evergreen:
        if (
            item["key"]
            not in used_topics
        ):
            candidates.append(
                {
                    "source_id": item["key"],
                    "category": item[
                        "category"
                    ],
                    "topic": item["topic"],
                    "source_type": "evergreen",
                }
            )

    if len(candidates) < 5:
        candidates.extend(
            on_this_day
        )

        candidates.extend(
            trivia
        )

        candidates.extend(
            [
                {
                    "source_id": item["key"],
                    "category": item[
                        "category"
                    ],
                    "topic": item["topic"],
                    "source_type": "evergreen",
                }
                for item in evergreen
            ]
        )

    random.shuffle(candidates)

    unique = []
    seen = set()

    for candidate in candidates:
        key = candidate.get(
            "source_id"
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

        if len(unique) >= 30:
            break

    return unique


TOPIC_SELECTOR_PROMPT = """
You are selecting a topic for a YouTube Shorts channel.

The channel makes 30–45 second videos about:
- strange history
- surprising science
- engineering
- technology
- transportation
- animals
- unusual real-world events
- fascinating facts

Choose ONE candidate.

The topic should:
- have a strong curiosity hook
- be understandable quickly
- have enough factual material for 85–115 spoken words
- work with stock video footage
- avoid politics unless the event itself is historically important
- avoid conspiracy theories
- avoid invented facts
- avoid fake quotations

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


def get_gemini_client():
    from google import genai

    return genai.Client(
        api_key=GEMINI_API_KEY
    )


def discover_gemini_model(
    client,
) -> str:

    preferred = [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]

    try:
        available = []

        for model in client.models.list():
            name = getattr(
                model,
                "name",
                "",
            )

            if name:
                available.append(name)

        for wanted in preferred:
            for available_name in available:
                if wanted in available_name:
                    log(
                        f"Using Gemini model: "
                        f"{available_name}"
                    )
                    return available_name

    except Exception as exc:
        log(
            f"Could not discover Gemini "
            f"models: {exc}"
        )

    return preferred[-2]


def gemini_generate(
    client,
    model: str,
    prompt: str,
    retries: int = 3,
) -> str:

    for attempt in range(
        1,
        retries + 1,
    ):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )

            text = getattr(
                response,
                "text",
                None,
            )

            if text:
                return text.strip()

            raise RuntimeError(
                "Gemini returned empty text."
            )

        except Exception as exc:
            error_text = str(exc)

            log(
                f"Gemini attempt "
                f"{attempt}/{retries} failed: "
                f"{error_text[:300]}"
            )

            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED"
                in error_text
                or "quota" in error_text.lower()
            ):
                if attempt < retries:
                    time.sleep(
                        6 * attempt
                    )
                    continue

            if attempt < retries:
                time.sleep(
                    3 * attempt
                )
            else:
                raise


def select_topic(
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:

    if not candidates:
        raise RuntimeError(
            "No topic candidates available."
        )

    client = get_gemini_client()

    model = discover_gemini_model(
        client
    )

    formatted = []

    for index, candidate in enumerate(
        candidates
    ):
        formatted.append(
            {
                "index": index,
                **candidate,
            }
        )

    prompt = TOPIC_SELECTOR_PROMPT.format(
        candidates=json.dumps(
            formatted,
            indent=2,
            ensure_ascii=False,
        )
    )

    raw = gemini_generate(
        client,
        model,
        prompt,
    )

    result = safe_json_loads(raw)

    index = int(
        result.get(
            "selected_index",
            0,
        )
    )

    index = max(
        0,
        min(
            index,
            len(candidates) - 1,
        ),
    )

    selected = dict(
        candidates[index]
    )

    selected.update(
        {
            "topic": result.get(
                "topic",
                selected.get("topic", ""),
            ),
            "category": result.get(
                "category",
                selected.get(
                    "category",
                    "general",
                ),
            ),
            "angle": result.get(
                "angle",
                "",
            ),
            "source_summary": result.get(
                "source_summary",
                "",
            ),
        }
    )

    return selected


def get_dynamic_topic(
    state: Dict[str, Any],
) -> Dict[str, Any]:

    candidates = build_candidates(
        state
    )

    return select_topic(
        candidates
    )


# ============================================================
# SCRIPT GENERATION
# ============================================================

SCRIPT_PROMPT = """
You write scripts for an addictive YouTube Shorts channel.

Create a factual 30–45 second story.

TARGET:
85–115 spoken words.

STYLE:
- Immediate hook.
- Short sentences.
- Natural spoken English.
- Escalate the information.
- Give a satisfying payoff.
- End with a memorable final line.
- Do not waste words introducing the topic.

FACTUALITY:
- Use only information supported by the supplied topic.
- Do not invent statistics.
- Do not invent quotations.
- Do not create fake dialogue.
- Do not claim uncertain information as fact.
- Do not use conspiracy theories as facts.
- Do not use political persuasion.

VISUALS:
The video will use Coverr stock footage.

Create 3–5 visual search queries that describe footage
that could visually accompany the story.

Search queries should be:
- short
- concrete
- stock-footage friendly
- 2–5 words
- visually searchable

Example:
"construction machinery"
"tower crane"
"workers building"

CAPTIONS:
Every scene must have a caption.
Captions should be 2–5 words.
Maximum 6 words.
Use uppercase.

Return ONLY JSON in this exact structure:

{{
  "title": "under 60 characters",
  "hook": "first narration sentence",
  "ending_style": "loop",
  "footage_style": "construction",
  "visual_search_queries": [
    "construction machinery",
    "building site",
    "tower crane"
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

ENDING_STYLE:
Use one of:
- "loop"
- "question"
- "punchline"

FOOTAGE_STYLE:
Choose one:
- construction
- machines
- cars
- nature
- satisfying
- sports
- animation
- ocean
- aviation
- general

TOPIC:
{topic}

CATEGORY:
{category}

ANGLE:
{angle}

SOURCE SUMMARY:
{source_summary}
"""


def generate_script(
    topic_data: Dict[str, Any],
) -> Dict[str, Any]:

    client = get_gemini_client()

    model = discover_gemini_model(
        client
    )

    prompt = SCRIPT_PROMPT.format(
        topic=topic_data.get(
            "topic",
            "",
        ),
        category=topic_data.get(
            "category",
            "general",
        ),
        angle=topic_data.get(
            "angle",
            "",
        ),
        source_summary=topic_data.get(
            "source_summary",
            "",
        ),
    )

    raw = gemini_generate(
        client,
        model,
        prompt,
    )

    script = safe_json_loads(raw)

    validate_script(script)

    return script


def validate_script(
    script: Dict[str, Any],
) -> None:

    required = [
        "title",
        "hook",
        "scenes",
        "hashtags",
    ]

    for key in required:
        if key not in script:
            raise ValueError(
                f"Script missing: {key}"
            )

    title = clean_text(
        script["title"]
    )

    if not title:
        raise ValueError(
            "Empty title."
        )

    if len(title) > 60:
        script["title"] = title[:57] + "..."

    scenes = script.get(
        "scenes",
        [],
    )

    if not isinstance(
        scenes,
        list,
    ):
        raise ValueError(
            "Scenes must be a list."
        )

    if not scenes:
        raise ValueError(
            "No scenes generated."
        )

    if len(scenes) > MAX_SCENES:
        script["scenes"] = scenes[
            :MAX_SCENES
        ]

    footage_style = clean_text(
        script.get(
            "footage_style",
            "general",
        )
    ).lower()

    if footage_style not in FOOTAGE_STYLES:
        footage_style = "general"

    script["footage_style"] = footage_style

    queries = script.get(
        "visual_search_queries",
        [],
    )

    if not isinstance(
        queries,
        list,
    ):
        queries = []

    queries = [
        clean_text(x)
        for x in queries
        if clean_text(x)
    ]

    if not queries:
        queries = [
            footage_style,
            "interesting footage",
            "cinematic b roll",
        ]

    script["visual_search_queries"] = (
        queries[:5]
    )

    for scene in script["scenes"]:
        narration = clean_text(
            scene.get(
                "narration",
                "",
            )
        )

        caption = clean_text(
            scene.get(
                "caption",
                "",
            )
        )

        if not narration:
            raise ValueError(
                "Scene has empty narration."
            )

        if not caption:
            words = narration.split()

            caption = " ".join(
                words[:4]
            )

        caption = caption.upper()

        caption_words = caption.split()

        if len(caption_words) > 6:
            caption = " ".join(
                caption_words[:6]
            )

        scene["narration"] = narration
        scene["caption"] = caption

    hashtags = script.get(
        "hashtags",
        [],
    )

    if not isinstance(
        hashtags,
        list,
    ):
        hashtags = []

    hashtags = [
        clean_text(tag)
        for tag in hashtags
        if clean_text(tag)
    ]

    if "#shorts" not in [
        tag.lower()
        for tag in hashtags
    ]:
        hashtags.insert(
            0,
            "#shorts",
        )

    script["hashtags"] = hashtags[
        :8
    ]

    ending_style = clean_text(
        script.get(
            "ending_style",
            "loop",
        )
    ).lower()

    if ending_style not in {
        "loop",
        "question",
        "punchline",
    }:
        ending_style = "loop"

    script["ending_style"] = ending_style


# ============================================================
# TEXT / WORD TIMING
# ============================================================

def total_narration_words(
    script: Dict[str, Any],
) -> int:

    text = " ".join(
        scene["narration"]
        for scene in script["scenes"]
    )

    return len(text.split())


def estimate_scene_durations(
    script: Dict[str, Any],
    total_audio_duration: float,
) -> List[float]:

    scenes = script["scenes"]

    weights = []

    for scene in scenes:
        words = len(
            scene["narration"].split()
        )

        weights.append(
            max(words, 1)
        )

    total_weight = sum(weights)

    if total_weight <= 0:
        return [
            total_audio_duration
            / len(scenes)
        ] * len(scenes)

    durations = [
        total_audio_duration
        * (
            weight / total_weight
        )
        for weight in weights
    ]

    return durations


# ============================================================
# TTS
# ============================================================

def synthesize_scene_audio(
    narration: str,
    output_path: Path,
) -> None:

    import asyncio
    import edge_tts

    async def generate():
        communicate = edge_tts.Communicate(
            narration,
            TTS_VOICE,
            rate="+2%",
            pitch="+0Hz",
        )

        await communicate.save(
            str(output_path)
        )

    asyncio.run(generate())


def synthesize_all_audio(
    script: Dict[str, Any],
    run_dir: Path,
) -> Tuple[List[Path], float]:

    audio_dir = run_dir / "audio"
    audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = []

    for index, scene in enumerate(
        script["scenes"]
    ):
        path = (
            audio_dir
            / f"scene_{index:02d}.mp3"
        )

        log(
            f"Synthesizing scene "
            f"{index + 1}/{len(script['scenes'])}"
        )

        synthesize_scene_audio(
            scene["narration"],
            path,
        )

        paths.append(path)

    clips = []

    try:
        for path in paths:
            clip = AudioFileClip(
                str(path)
            )

            clips.append(clip)

        total_duration = sum(
            clip.duration
            for clip in clips
        )

    finally:
        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass

    return paths, total_duration


# ============================================================
# COVERR API
# ============================================================

def coverr_headers() -> Dict[str, str]:
    return {
        "x-api-key": COVERR_API_KEY,
        "Accept": "application/json",
        "User-Agent":
            "SpaceFactsPipeline/9.0",
    }


def search_coverr_videos(
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:

    query = clean_text(query)

    if not query:
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
            params=params,
            headers=coverr_headers(),
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            log(
                "Coverr rate limit reached."
            )
            return []

        response.raise_for_status()

        data = response.json()

        hits = data.get(
            "hits",
            [],
        )

        if not isinstance(
            hits,
            list,
        ):
            return []

        return hits

    except Exception as exc:
        log(
            f"Coverr search failed for "
            f"'{query}': {exc}"
        )
        return []


def get_coverr_video_details(
    video_id: str,
) -> Dict[str, Any]:

    if not video_id:
        return {}

    url = (
        f"https://api.coverr.co/videos/"
        f"{video_id}"
    )

    try:
        response = requests.get(
            url,
            headers=coverr_headers(),
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return {}

        data = response.json()

        if isinstance(data, dict):
            if isinstance(
                data.get("video"),
                dict,
            ):
                return data["video"]

            return data

    except Exception as exc:
        log(
            f"Coverr detail lookup failed: "
            f"{exc}"
        )

    return {}


def recursive_urls(
    value: Any,
) -> List[str]:

    found = []

    if isinstance(
        value,
        str,
    ):
        lower = value.lower()

        if (
            lower.startswith("http://")
            or lower.startswith("https://")
        ):
            found.append(value)

        return found

    if isinstance(
        value,
        dict,
    ):
        for key, child in value.items():

            key_lower = str(
                key
            ).lower()

            if (
                "thumbnail"
                in key_lower
            ):
                continue

            found.extend(
                recursive_urls(child)
            )

        return found

    if isinstance(
        value,
        list,
    ):
        for child in value:
            found.extend(
                recursive_urls(child)
            )

    return found


def choose_media_url(
    video: Dict[str, Any],
) -> Optional[str]:

    """
    Coverr's API schema can expose media through
    video details/variants. We inspect the returned
    object instead of assuming a single field name.
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

    def search_dict(
        obj: Any,
    ) -> Optional[str]:

        if isinstance(
            obj,
            dict,
        ):
            for key in preferred_keys:
                value = obj.get(key)

                if isinstance(
                    value,
                    str,
                ):
                    low = value.lower()

                    if (
                        low.startswith(
                            "http://"
                        )
                        or low.startswith(
                            "https://"
                        )
                    ) and (
                        ".mp4" in low
                        or "video" in low
                        or "cdn" in low
                        or "download" in low
                    ):
                        return value

            for child in obj.values():
                result = search_dict(child)

                if result:
                    return result

        elif isinstance(
            obj,
            list,
        ):
            for child in obj:
                result = search_dict(child)

                if result:
                    return result

        return None

    result = search_dict(video)

    if result:
        return result

    urls = recursive_urls(video)

    video_urls = []

    for url in urls:
        lower = url.lower()

        if (
            ".mp4" in lower
            or ".webm" in lower
            or ".mov" in lower
            or "video" in lower
            or "download" in lower
        ):
            video_urls.append(url)

    if video_urls:
        return video_urls[0]

    return None


def get_coverr_video_url(
    video: Dict[str, Any],
) -> Optional[str]:

    direct = choose_media_url(
        video
    )

    if direct:
        return direct

    video_id = str(
        video.get("id", "")
    )

    if not video_id:
        return None

    details = get_coverr_video_details(
        video_id
    )

    if details:
        direct = choose_media_url(
            details
        )

        if direct:
            return direct

    return None


def download_coverr_video(
    video: Dict[str, Any],
) -> Optional[Path]:

    video_id = str(
        video.get(
            "id",
            "",
        )
    )

    if not video_id:
        return None

    safe_id = slugify(video_id)

    output_path = (
        COVERR_DOWNLOAD_DIR
        / f"coverr_{safe_id}.mp4"
    )

    if (
        output_path.exists()
        and output_path.stat().st_size > 100_000
    ):
        log(
            f"Using cached Coverr clip: "
            f"{output_path.name}"
        )
        return output_path

    url = get_coverr_video_url(
        video
    )

    if not url:
        log(
            f"No downloadable media URL "
            f"found for Coverr video "
            f"{video_id}"
        )
        return None

    temp_path = (
        output_path.with_suffix(
            ".download"
        )
    )

    try:
        log(
            f"Downloading Coverr clip: "
            f"{video.get('title', video_id)}"
        )

        with requests.get(
            url,
            headers={
                "User-Agent":
                    "SpaceFactsPipeline/9.0",
            },
            stream=True,
            timeout=REQUEST_TIMEOUT,
        ) as response:

            response.raise_for_status()

            with open(
                temp_path,
                "wb",
            ) as file:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        file.write(chunk)

        if (
            not temp_path.exists()
            or temp_path.stat().st_size
            < 100_000
        ):
            raise RuntimeError(
                "Downloaded file is too small."
            )

        temp_path.replace(
            output_path
        )

        return output_path

    except Exception as exc:
        log(
            f"Coverr download failed: "
            f"{exc}"
        )

        try:
            temp_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        return None


def coverr_source_id(
    video: Dict[str, Any],
) -> str:

    return (
        "coverr-"
        + str(
            video.get(
                "id",
                "",
            )
        )
    )


def select_coverr_clips(
    queries: List[str],
    state: Dict[str, Any],
    number_of_clips: int,
) -> List[Dict[str, Any]]:

    used_sources = set(
        state.get(
            "used_source_ids",
            [],
        )
    )

    candidates = []

    seen_ids = set()

    for query in queries:

        results = search_coverr_videos(
            query,
            limit=10,
        )

        random.shuffle(results)

        for video in results:

            video_id = str(
                video.get(
                    "id",
                    "",
                )
            )

            if not video_id:
                continue

            source_id = coverr_source_id(
                video
            )

            if source_id in used_sources:
                continue

            if video_id in seen_ids:
                continue

            seen_ids.add(video_id)

            candidate = dict(video)

            candidate["_query"] = query

            candidates.append(
                candidate
            )

    if not candidates:
        return []

    vertical = [
        item
        for item in candidates
        if item.get(
            "is_vertical",
            False,
        )
    ]

    horizontal = [
        item
        for item in candidates
        if not item.get(
            "is_vertical",
            False,
        )
    ]

    ordered = (
        vertical
        + horizontal
    )

    selected = []

    for candidate in ordered:

        if len(selected) >= number_of_clips:
            break

        path = download_coverr_video(
            candidate
        )

        if not path:
            continue

        selected.append(
            {
                "path": str(path),
                "provider": "Coverr",
                "source_id":
                    coverr_source_id(
                        candidate
                    ),
                "source_url":
                    candidate.get(
                        "url",
                        COVERR_BASE_URL,
                    ),
                "query":
                    candidate.get(
                        "_query",
                        "",
                    ),
                "title":
                    candidate.get(
                        "title",
                        "",
                    ),
            }
        )

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


def get_footage_root() -> Path:

    if FOOTAGE_DIR.exists():
        return FOOTAGE_DIR

    if GAMEPLAY_DIR.exists():
        return GAMEPLAY_DIR

    return FOOTAGE_DIR


def get_footage_files() -> List[Path]:

    root = get_footage_root()

    if not root.exists():
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


def detect_footage_style(
    path: Path,
) -> str:

    lower = str(
        path
    ).lower()

    for style in FOOTAGE_STYLES:
        if style in lower:
            return style

    return "general"


def select_local_footage(
    style: str,
    state: Dict[str, Any],
    number_of_clips: int,
) -> List[Dict[str, Any]]:

    files = get_footage_files()

    if not files:
        return []

    preferred = [
        path
        for path in files
        if detect_footage_style(path)
        == style
    ]

    general = [
        path
        for path in files
        if path not in preferred
    ]

    pool = (
        preferred
        + general
    )

    used = set(
        state.get(
            "used_gameplay",
            [],
        )
    )

    random.shuffle(pool)

    selected = []

    for path in pool:

        if len(selected) >= number_of_clips:
            break

        path_str = str(path)

        if path_str in used:
            continue

        selected.append(
            {
                "path": path_str,
                "provider": "Local",
                "source_id": "",
                "source_url": "",
                "query": style,
                "title": path.name,
            }
        )

    if not selected and pool:
        for path in pool[
            :number_of_clips
        ]:
            selected.append(
                {
                    "path": str(path),
                    "provider": "Local",
                    "source_id": "",
                    "source_url": "",
                    "query": style,
                    "title": path.name,
                }
            )

    return selected


def select_footage(
    style: str,
    visual_search_queries: List[str],
    state: Dict[str, Any],
    number_of_clips: int,
) -> List[Dict[str, Any]]:

    queries = list(
        visual_search_queries
    )

    if not queries:
        queries = [
            style,
            "cinematic footage",
            "interesting footage",
        ]

    queries = queries[
        :5
    ]

    log(
        f"Searching Coverr for "
        f"{number_of_clips} clips..."
    )

    clips = select_coverr_clips(
        queries,
        state,
        number_of_clips,
    )

    if len(clips) >= number_of_clips:
        log(
            f"Found {len(clips)} Coverr clips."
        )
        return clips

    log(
        f"Coverr only returned "
        f"{len(clips)} clips. "
        f"Trying local fallback."
    )

    local = select_local_footage(
        style,
        state,
        number_of_clips
        - len(clips),
    )

    return clips + local


# ============================================================
# VIDEO PREPARATION
# ============================================================

def crop_to_vertical(
    clip: VideoFileClip,
) -> VideoFileClip:

    width = clip.w
    height = clip.h

    target_ratio = (
        VIDEO_W / VIDEO_H
    )

    source_ratio = (
        width / height
        if height
        else target_ratio
    )

    if source_ratio > target_ratio:

        new_width = int(
            height * target_ratio
        )

        x1 = int(
            (width - new_width)
            / 2
        )

        return clip.crop(
            x1=x1,
            x2=x1 + new_width,
        )

    new_height = int(
        width / target_ratio
    )

    y1 = int(
        (height - new_height)
        / 2
    )

    return clip.crop(
        y1=y1,
        y2=y1 + new_height,
    )


def prepare_footage_clip(
    path: str,
    duration: float,
) -> VideoFileClip:

    clip = VideoFileClip(
        path
    )

    if clip.duration <= 0:
        clip.close()

        raise RuntimeError(
            f"Invalid video duration: "
            f"{path}"
        )

    if clip.duration >= duration:

        max_start = max(
            0,
            clip.duration
            - duration,
        )

        start = (
            random.uniform(
                0,
                max_start,
            )
            if max_start > 0
            else 0
        )

        prepared = clip.subclip(
            start,
            start + duration,
        )

    else:

        repeats = int(
            duration
            // clip.duration
        ) + 1

        pieces = [
            clip
            for _ in range(repeats)
        ]

        prepared = concatenate_videoclips(
            pieces,
            method="compose",
        ).subclip(
            0,
            duration,
        )

    prepared = crop_to_vertical(
        prepared
    )

    prepared = prepared.resize(
        newsize=(
            VIDEO_W,
            VIDEO_H,
        )
    )

    prepared = prepared.set_duration(
        duration
    )

    return prepared


# ============================================================
# CAPTIONS
# ============================================================

def get_caption_font(
    size: int = 82,
):
    return ImageFont.truetype(
        CAPTION_FONT_PATH,
        size=size,
    )


def make_caption_image(
    text: str,
    width: int = 920,
    height: int = 320,
    font_size: int = 82,
) -> Image.Image:

    image = Image.new(
        "RGBA",
        (
            width,
            height,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )

    draw = ImageDraw.Draw(
        image
    )

    font = get_caption_font(
        font_size
    )

    words = text.upper().split()

    lines = []
    current = ""

    for word in words:

        test = (
            word
            if not current
            else current + " " + word
        )

        bbox = draw.textbbox(
            (0, 0),
            test,
            font=font,
            stroke_width=5,
        )

        if (
            bbox[2] - bbox[0]
            <= width - 50
        ):
            current = test
        else:
            if current:
                lines.append(
                    current
                )

            current = word

    if current:
        lines.append(
            current
        )

    lines = lines[:3]

    line_heights = []

    for line in lines:
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=5,
        )

        line_heights.append(
            bbox[3] - bbox[1]
        )

    total_height = (
        sum(line_heights)
        + max(
            0,
            len(lines) - 1,
        )
        * 12
    )

    y = (
        height
        - total_height
    ) / 2

    for index, line in enumerate(
        lines
    ):

        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=6,
        )

        text_width = (
            bbox[2] - bbox[0]
        )

        x = (
            width
            - text_width
        ) / 2

        draw.text(
            (
                x,
                y,
            ),
            line,
            font=font,
            fill="white",
            stroke_width=6,
            stroke_fill="black",
        )

        y += (
            line_heights[index]
            + 12
        )

    return image


def save_caption_images(
    script: Dict[str, Any],
    run_dir: Path,
) -> List[Path]:

    caption_dir = (
        run_dir / "captions"
    )

    caption_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = []

    for index, scene in enumerate(
        script["scenes"]
    ):

        image = make_caption_image(
            scene["caption"]
        )

        path = (
            caption_dir
            / f"caption_{index:02d}.png"
        )

        image.save(
            path
        )

        paths.append(path)

    return paths


# ============================================================
# BGM
# ============================================================

def find_bgm() -> Optional[Path]:

    if not BGM_DIR.exists():
        return None

    files = [
        path
        for path in BGM_DIR.rglob("*")
        if path.is_file()
        and path.suffix.lower()
        in {
            ".mp3",
            ".wav",
            ".m4a",
        }
    ]

    if not files:
        return None

    return random.choice(
        files
    )


# ============================================================
# VIDEO BUILD
# ============================================================

def build_video(
    script: Dict[str, Any],
    footage_items: List[Dict[str, Any]],
    audio_paths: List[Path],
    total_duration: float,
    run_dir: Path,
) -> Path:

    log(
        "Building final vertical video..."
    )

    scene_durations = (
        estimate_scene_durations(
            script,
            total_duration,
        )
    )

    if not footage_items:
        raise RuntimeError(
            "No footage available."
        )

    prepared_clips = []

    try:

        for index, duration in enumerate(
            scene_durations
        ):

            footage = footage_items[
                index
                % len(footage_items)
            ]

            log(
                f"Preparing footage "
                f"{index + 1}/"
                f"{len(scene_durations)}: "
                f"{footage.get('title', '')}"
            )

            clip = prepare_footage_clip(
                footage["path"],
                duration,
            )

            prepared_clips.append(
                clip
            )

        background = concatenate_videoclips(
            prepared_clips,
            method="compose",
        )

        background = background.set_duration(
            total_duration
        )

        # ----------------------------------------------------
        # Narration audio
        # ----------------------------------------------------

        narration_clips = []

        for path in audio_paths:
            narration_clips.append(
                AudioFileClip(
                    str(path)
                )
            )

        narration = concatenate_audio(
            narration_clips
        )

        # ----------------------------------------------------
        # Captions
        # ----------------------------------------------------

        caption_images = save_caption_images(
            script,
            run_dir,
        )

        caption_layers = []

        current_time = 0.0

        for index, duration in enumerate(
            scene_durations
        ):

            caption = (
                ImageClipCompat(
                    caption_images[index]
                )
                .set_start(
                    current_time
                )
                .set_duration(
                    duration
                )
                .set_position(
                    (
                        "center",
                        1120,
                    )
                )
            )

            caption_layers.append(
                caption
            )

            current_time += duration

        # ----------------------------------------------------
        # Composite
        # ----------------------------------------------------

        final_video = CompositeVideoClip(
            [
                background,
                *caption_layers,
            ],
            size=(
                VIDEO_W,
                VIDEO_H,
            ),
        )

        # ----------------------------------------------------
        # Background music
        # ----------------------------------------------------

        bgm_path = find_bgm()

        if bgm_path:
            try:
                bgm = AudioFileClip(
                    str(bgm_path)
                )

                if bgm.duration < total_duration:

                    repeats = int(
                        total_duration
                        // bgm.duration
                    ) + 1

                    bgm_parts = [
                        bgm
                        for _ in range(
                            repeats
                        )
                    ]

                    bgm = concatenate_audio(
                        bgm_parts
                    )

                bgm = bgm.subclip(
                    0,
                    total_duration,
                )

                bgm = bgm.volumex(
                    0.06
                )

                final_audio = CompositeAudioClip(
                    [
                        narration,
                        bgm,
                    ]
                )

                final_video = (
                    final_video
                    .set_audio(
                        final_audio
                    )
                )

            except Exception as exc:
                log(
                    f"BGM skipped: {exc}"
                )

                final_video = (
                    final_video
                    .set_audio(
                        narration
                    )
                )

        else:
            final_video = (
                final_video
                .set_audio(
                    narration
                )
            )

        output_path = (
            OUTPUT_DIR
            / (
                "spacefacts_"
                + time.strftime(
                    "%Y%m%d_%H%M%S"
                )
                + "_"
                + uuid.uuid4().hex[:6]
                + ".mp4"
            )
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

        return output_path

    finally:

        for clip in prepared_clips:
            try:
                clip.close()
            except Exception:
                pass


def concatenate_audio(
    clips: List[AudioFileClip],
):
    if not clips:
        raise RuntimeError(
            "No audio clips."
        )

    if len(clips) == 1:
        return clips[0]

    return CompositeAudioClip(
        [
            clip.set_start(
                sum(
                    c.duration
                    for c in clips[:index]
                )
            )
            for index, clip in enumerate(
                clips
            )
        ]
    )


# ============================================================
# IMAGE CLIP COMPATIBILITY
# ============================================================

def ImageClipCompat(
    path: Path,
):
    from moviepy.editor import ImageClip

    return ImageClip(
        str(path)
    )


# ============================================================
# YOUTUBE
# ============================================================

def build_description(
    script: Dict[str, Any],
    footage_items: List[Dict[str, Any]],
) -> str:

    hook = clean_text(
        script.get(
            "hook",
            "",
        )
    )

    hashtags = script.get(
        "hashtags",
        [],
    )

    description = (
        hook
        + "\n\n"
        + " ".join(
            hashtags
        )
    )

    coverr_items = [
        item
        for item in footage_items
        if item.get(
            "provider"
        ) == "Coverr"
    ]

    if coverr_items:

        description += (
            "\n\n"
            "Footage provided by Coverr."
            "\n"
            "https://coverr.co/"
        )

        seen = set()

        for item in coverr_items:

            source_url = clean_text(
                item.get(
                    "source_url",
                    "",
                )
            )

            if (
                source_url
                and source_url not in seen
            ):
                description += (
                    "\nSource: "
                    + source_url
                )

                seen.add(
                    source_url
                )

    return description


def upload_to_youtube(
    video_path: Path,
    script: Dict[str, Any],
    footage_items: List[Dict[str, Any]],
) -> Any:

    """
    Uses the existing youtube_upload.py.

    The existing uploader is intentionally not
    duplicated or modified here.
    """

    from youtube_upload import upload_video

    title = clean_text(
        script.get(
            "title",
            "Amazing Fact",
        )
    )

    description = build_description(
        script,
        footage_items,
    )

    hashtags = script.get(
        "hashtags",
        [],
    )

    tags = []

    for hashtag in hashtags:
        tag = hashtag.lstrip(
            "#"
        ).strip()

        if tag:
            tags.append(tag)

    return upload_video(
        video_path=str(video_path),
        title=title,
        description=description,
        tags=tags,
        privacy_status="public",
    )


# ============================================================
# UPLOAD LOG
# ============================================================

def log_upload(
    video_path: Path,
    script: Dict[str, Any],
    topic_data: Dict[str, Any],
    footage_items: List[Dict[str, Any]],
    upload_result: Any,
) -> None:

    entry = {
        "timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        "video": str(
            video_path
        ),
        "title": script.get(
            "title",
            "",
        ),
        "topic": topic_data.get(
            "topic",
            "",
        ),
        "category": topic_data.get(
            "category",
            "",
        ),
        "upload_result": upload_result,
        "footage": [
            {
                "provider": item.get(
                    "provider",
                    "",
                ),
                "source_id": item.get(
                    "source_id",
                    "",
                ),
                "source_url": item.get(
                    "source_url",
                    "",
                ),
                "query": item.get(
                    "query",
                    "",
                ),
                "title": item.get(
                    "title",
                    "",
                ),
            }
            for item in footage_items
        ],
    }

    with open(
        UPLOAD_LOG_FILE,
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                entry,
                ensure_ascii=False,
            )
            + "\n"
        )


# ============================================================
# METADATA
# ============================================================

def save_run_metadata(
    run_dir: Path,
    topic_data: Dict[str, Any],
    script: Dict[str, Any],
    footage_items: List[Dict[str, Any]],
) -> None:

    metadata = {
        "version": VERSION,
        "timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        "topic": topic_data,
        "script": script,
        "footage": footage_items,
    }

    (
        run_dir / "script.json"
    ).write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline() -> None:

    print()
    print("=" * 70)
    print(
        f"SPACE FACTS PIPELINE {VERSION}"
    )
    print(
        "COVERR MULTI-CLIP SHORTS FORMAT"
    )
    print("=" * 70)
    print()

    validate_environment()

    state = load_state()

    # --------------------------------------------------------
    # TOPIC
    # --------------------------------------------------------

    log(
        "Fetching a fresh topic..."
    )

    topic_data = get_dynamic_topic(
        state
    )

    log(
        f"Selected topic: "
        f"{topic_data.get('topic', '')}"
    )

    # --------------------------------------------------------
    # SCRIPT
    # --------------------------------------------------------

    log(
        "Generating Shorts script..."
    )

    script = generate_script(
        topic_data
    )

    word_count = total_narration_words(
        script
    )

    log(
        f"Generated {word_count} narration words."
    )

    log(
        f"Title: {script.get('title', '')}"
    )

    log(
        "Visual queries: "
        + ", ".join(
            script.get(
                "visual_search_queries",
                [],
            )
        )
    )

    # --------------------------------------------------------
    # RUN DIRECTORY
    # --------------------------------------------------------

    run_id = (
        time.strftime(
            "%Y%m%d_%H%M%S"
        )
        + "_"
        + uuid.uuid4().hex[:6]
    )

    run_dir = (
        OUTPUT_DIR / run_id
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # FOOTAGE
    # --------------------------------------------------------

    scene_count = len(
        script["scenes"]
    )

    footage_items = select_footage(
        style=script.get(
            "footage_style",
            "general",
        ),
        visual_search_queries=script.get(
            "visual_search_queries",
            [],
        ),
        state=state,
        number_of_clips=min(
            max(
                scene_count,
                3,
            ),
            5,
        ),
    )

    if not footage_items:
        raise RuntimeError(
            "No footage could be obtained."
        )

    log(
        f"Using {len(footage_items)} "
        f"footage clips."
    )

    # --------------------------------------------------------
    # SAVE METADATA
    # --------------------------------------------------------

    save_run_metadata(
        run_dir,
        topic_data,
        script,
        footage_items,
    )

    # --------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------

    audio_paths, total_duration = (
        synthesize_all_audio(
            script,
            run_dir,
        )
    )

    total_duration = clamp(
        total_duration,
        TARGET_MIN_SECONDS,
        TARGET_MAX_SECONDS,
    )

    log(
        f"Final narration duration: "
        f"{total_duration:.2f}s"
    )

    # --------------------------------------------------------
    # VIDEO
    # --------------------------------------------------------

    video_path = build_video(
        script=script,
        footage_items=footage_items,
        audio_paths=audio_paths,
        total_duration=total_duration,
        run_dir=run_dir,
    )

    log(
        f"Video created: "
        f"{video_path}"
    )

    # --------------------------------------------------------
    # UPLOAD
    # --------------------------------------------------------

    log(
        "Uploading to YouTube..."
    )

    upload_result = upload_to_youtube(
        video_path,
        script,
        footage_items,
    )

    log(
        "YouTube upload completed."
    )

    # --------------------------------------------------------
    # ONLY AFTER SUCCESSFUL UPLOAD:
    # UPDATE STATE
    # --------------------------------------------------------

    remember_title(
        state,
        script.get(
            "title",
            "",
        ),
    )

    source_id = topic_data.get(
        "source_id",
        "",
    )

    if source_id:
        remember_source(
            state,
            source_id,
        )

    topic_key = topic_data.get(
        "key",
        topic_data.get(
            "source_id",
            "",
        ),
    )

    if topic_key:
        remember_topic(
            state,
            topic_key,
        )

    for footage in footage_items:

        path = footage.get(
            "path",
            "",
        )

        remember_footage(
            state,
            path,
        )

        footage_source = footage.get(
            "source_id",
            "",
        )

        if footage_source:
            remember_source(
                state,
                footage_source,
            )

    save_state(
        state
    )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    log_upload(
        video_path,
        script,
        topic_data,
        footage_items,
        upload_result,
    )

    print()
    print("=" * 70)
    print("UPLOAD SUCCESSFUL")
    print(
        f"Title: {script.get('title', '')}"
    )
    print(
        f"Duration: {total_duration:.2f}s"
    )
    print(
        f"Footage clips: {len(footage_items)}"
    )
    print("=" * 70)
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        run_pipeline()

    except KeyboardInterrupt:
        print(
            "\nPipeline interrupted."
        )
        sys.exit(130)

    except Exception as exc:

        print()
        print("=" * 70)
        print("PIPELINE FAILED")
        print("=" * 70)

        print(
            f"{type(exc).__name__}: {exc}"
        )

        import traceback

        traceback.print_exc()

        print("=" * 70)

        sys.exit(1)