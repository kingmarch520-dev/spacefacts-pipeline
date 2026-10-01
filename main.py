"""
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v8)

FORMAT:
    Random interesting footage
    +
    Interesting history / trivia / science narration
    +
    Dynamic captions
    +
    Consistent male narrator

PIPELINE:
1. Fetch fresh On This Day events / trivia
2. Mix in broader evergreen topics
3. Select a strong topic with Gemini
4. Generate a 30–45 second story
5. Generate narration with Edge TTS
6. Select matching random footage
7. Crop footage to 1080x1920
8. Add dynamic captions
9. Assemble the Short
10. Upload to YouTube

FOOTAGE FOLDER:

footage/
├── construction/
├── machines/
├── cars/
├── nature/
├── satisfying/
├── sports/
├── animation/
├── ocean/
├── aviation/
└── general/

Supported:
.mp4
.mov
.webm
.mkv

BACKWARD COMPATIBILITY:

If footage/ does not exist, the program will also check:

gameplay/

Existing infrastructure:
- Gemini
- Wikimedia On This Day
- Open Trivia Database
- Edge TTS
- MoviePy
- YouTube upload
- state_spacefacts.json
- upload_log.jsonl
- Anton-Regular.ttf
"""

import os
import json
import random
import asyncio
import time
import html
import re

from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import requests
import youtube_upload


# ==================================================================
# CONFIG
# ==================================================================

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "",
)

STATE_FILE = Path(
    "state_spacefacts.json"
)

UPLOAD_LOG_FILE = Path(
    "upload_log.jsonl"
)

OUTPUT_DIR = Path(
    "output_spacefacts"
)

OUTPUT_DIR.mkdir(
    exist_ok=True
)


# New footage directory.
FOOTAGE_DIR = Path(
    os.environ.get(
        "FOOTAGE_DIR",
        "footage",
    )
)


# Old directory retained for compatibility.
GAMEPLAY_DIR = Path(
    os.environ.get(
        "GAMEPLAY_DIR",
        "gameplay",
    )
)


VIDEO_W = 1080
VIDEO_H = 1920


CAPTION_FONT_PATH = str(
    Path(__file__).parent
    / "Anton-Regular.ttf"
)


BGM_DIR = Path(
    os.environ.get(
        "BGM_DIR",
        "bgm",
    )
)


# ==================================================================
# STANDARD MALE VOICE
# ==================================================================

# One voice for the entire channel.
#
# This is intentionally NOT randomized.
TTS_VOICE = "en-US-AndrewMultilingualNeural"


# ==================================================================
# GEMINI MODELS
# ==================================================================

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


# ==================================================================
# CONTENT MIX
# ==================================================================

CONTENT_WEIGHTS = {
    "on_this_day": 0.45,
    "trivia": 0.25,
    "evergreen": 0.30,
}


# ==================================================================
# FOOTAGE STYLES
# ==================================================================

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


# ==================================================================
# EVERGREEN TOPICS
# ==================================================================

EVERGREEN_TOPICS = [

    # --------------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------------

    {
        "topic": (
            "how the pyramids were built "
            "without modern machinery"
        ),
        "category": "history",
    },

    {
        "topic": (
            "how Roman concrete survived "
            "for thousands of years"
        ),
        "category": "history",
    },

    {
        "topic": (
            "the mysterious Antikythera mechanism"
        ),
        "category": "history",
    },

    {
        "topic": (
            "why the Voynich manuscript "
            "is still so mysterious"
        ),
        "category": "history",
    },

    {
        "topic": (
            "the ancient city of Pompeii "
            "and its final day"
        ),
        "category": "history",
    },

    {
        "topic": (
            "why medieval castles were "
            "so difficult to attack"
        ),
        "category": "history",
    },

    {
        "topic": (
            "how ancient Egyptians "
            "moved enormous stones"
        ),
        "category": "history",
    },

    {
        "topic": (
            "the strange history of the "
            "first mechanical clocks"
        ),
        "category": "history",
    },

    {
        "topic": (
            "why Vikings used surprisingly "
            "advanced navigation"
        ),
        "category": "history",
    },

    {
        "topic": (
            "the ancient city that disappeared "
            "under the sea"
        ),
        "category": "history",
    },

    # --------------------------------------------------------------
    # SCIENCE
    # --------------------------------------------------------------

    {
        "topic": (
            "why astronauts age slightly "
            "differently in space"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why lightning can create glass "
            "in the ground"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why humans cannot hear "
            "all frequencies of sound"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why the sky changes color "
            "during sunset"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why some metals can remember "
            "their original shape"
        ),
        "category": "science",
    },

    {
        "topic": (
            "how octopuses can change "
            "their appearance"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why boiling water can freeze "
            "under certain conditions"
        ),
        "category": "science",
    },

    {
        "topic": (
            "how airplanes stay in the air"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why the Moon is slowly "
            "moving away from Earth"
        ),
        "category": "science",
    },

    {
        "topic": (
            "why humans get goosebumps"
        ),
        "category": "science",
    },

    # --------------------------------------------------------------
    # ENGINEERING
    # --------------------------------------------------------------

    {
        "topic": (
            "how skyscrapers survive "
            "strong winds"
        ),
        "category": "engineering",
    },

    {
        "topic": (
            "how suspension bridges "
            "support enormous weight"
        ),
        "category": "engineering",
    },

    {
        "topic": (
            "how tunnels are built "
            "under cities"
        ),
        "category": "engineering",
    },

    {
        "topic": (
            "how massive cranes can "
            "lift incredible weights"
        ),
        "category": "engineering",
    },

    {
        "topic": (
            "how dams hold back "
            "millions of tons of water"
        ),
        "category": "engineering",
    },

    {
        "topic": (
            "how trains can stop "
            "such enormous masses"
        ),
        "category": "engineering",
    },

    # --------------------------------------------------------------
    # MYSTERIES
    # --------------------------------------------------------------

    {
        "topic": (
            "the strange disappearance "
            "of the Mary Celeste"
        ),
        "category": "mystery",
    },

    {
        "topic": (
            "why the Tunguska explosion "
            "flattened such a huge area"
        ),
        "category": "science",
    },

    {
        "topic": (
            "the mystery of the "
            "Dancing Plague of 1518"
        ),
        "category": "history",
    },

    {
        "topic": (
            "why some ancient civilizations "
            "built enormous stone structures"
        ),
        "category": "history",
    },

    # --------------------------------------------------------------
    # ANIMALS / NATURE
    # --------------------------------------------------------------

    {
        "topic": (
            "how tardigrades can survive "
            "extreme conditions"
        ),
        "category": "nature",
    },

    {
        "topic": (
            "why sharks are older "
            "than trees"
        ),
        "category": "nature",
    },

    {
        "topic": (
            "how ants can build living bridges"
        ),
        "category": "nature",
    },

    {
        "topic": (
            "how birds can navigate "
            "across enormous distances"
        ),
        "category": "nature",
    },

    {
        "topic": (
            "why octopuses have three hearts"
        ),
        "category": "nature",
    },

    # --------------------------------------------------------------
    # TECHNOLOGY
    # --------------------------------------------------------------

    {
        "topic": (
            "how the first computers "
            "filled entire rooms"
        ),
        "category": "technology",
    },

    {
        "topic": (
            "how GPS can calculate "
            "your location"
        ),
        "category": "technology",
    },

    {
        "topic": (
            "why computer chips are "
            "so incredibly small"
        ),
        "category": "technology",
    },

    {
        "topic": (
            "how hard drives store "
            "billions of tiny bits"
        ),
        "category": "technology",
    },

    {
        "topic": (
            "how satellites communicate "
            "with Earth"
        ),
        "category": "technology",
    },

    # --------------------------------------------------------------
    # TRANSPORT
    # --------------------------------------------------------------

    {
        "topic": (
            "why Formula 1 cars "
            "can corner so quickly"
        ),
        "category": "transport",
    },

    {
        "topic": (
            "why modern airplanes "
            "can fly for so long"
        ),
        "category": "transport",
    },

    {
        "topic": (
            "how bullet trains "
            "reach incredible speeds"
        ),
        "category": "transport",
    },

    {
        "topic": (
            "why race cars have "
            "such unusual shapes"
        ),
        "category": "transport",
    },

    {
        "topic": (
            "how ships stay afloat "
            "despite weighing thousands of tons"
        ),
        "category": "transport",
    },
]


# ==================================================================
# ENVIRONMENT
# ==================================================================

def validate_environment():

    missing = []

    if not GEMINI_API_KEY:

        missing.append(
            "GEMINI_API_KEY"
        )

    footage_exists = (
        FOOTAGE_DIR.exists()
        or GAMEPLAY_DIR.exists()
    )

    if not footage_exists:

        print(
            "WARNING: No footage directory "
            "was found."
        )

        print(
            "Create footage/ and add "
            "licensed footage."
        )

    if not Path(
        CAPTION_FONT_PATH
    ).exists():

        print(
            "WARNING: Anton-Regular.ttf "
            "was not found."
        )

    if missing:

        raise RuntimeError(
            "Missing required environment "
            "variables: "
            + ", ".join(missing)
        )


# ==================================================================
# STATE
# ==================================================================

def load_state():

    if STATE_FILE.exists():

        try:

            state = json.loads(
                STATE_FILE.read_text(
                    encoding="utf-8"
                )
            )

            # Add new fields if this is
            # an older state file.
            state.setdefault(
                "recent_titles",
                [],
            )

            state.setdefault(
                "used_source_ids",
                [],
            )

            state.setdefault(
                "used_topic_keys",
                [],
            )

            state.setdefault(
                "used_gameplay",
                [],
            )

            return state

        except Exception as e:

            print(
                "Warning: Could not read "
                f"state file: {e}"
            )

    return {
        "recent_titles": [],
        "used_source_ids": [],
        "used_topic_keys": [],
        "used_gameplay": [],
    }


def save_state(state):

    STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def get_recent_titles():

    state = load_state()

    return state.get(
        "recent_titles",
        [],
    )


def record_used_title(
    title
):

    state = load_state()

    recent = state.get(
        "recent_titles",
        [],
    )

    recent.append(
        title
    )

    state["recent_titles"] = (
        recent[-40:]
    )

    save_state(
        state
    )


def remember_source(
    source_id
):

    if not source_id:
        return

    state = load_state()

    used = state.get(
        "used_source_ids",
        [],
    )

    used.append(
        str(source_id)
    )

    state["used_source_ids"] = (
        used[-300:]
    )

    save_state(
        state
    )


def source_was_used(
    source_id
):

    if not source_id:
        return False

    state = load_state()

    used = [
        str(x)
        for x in state.get(
            "used_source_ids",
            [],
        )
    ]

    return (
        str(source_id)
        in used
    )


def remember_topic(
    topic_key
):

    if not topic_key:
        return

    state = load_state()

    used = state.get(
        "used_topic_keys",
        [],
    )

    used.append(
        str(topic_key)
    )

    state["used_topic_keys"] = (
        used[-300:]
    )

    save_state(
        state
    )


def topic_was_used(
    topic_key
):

    if not topic_key:
        return False

    state = load_state()

    used = [
        str(x)
        for x in state.get(
            "used_topic_keys",
            [],
        )
    ]

    return (
        str(topic_key)
        in used
    )


def normalize_topic_key(
    topic
):

    text = str(
        topic or ""
    ).lower().strip()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text,
    )

    return text.strip("-")


# ==================================================================
# FOOTAGE STATE
# ==================================================================

def get_used_footage():

    state = load_state()

    return [
        str(x)
        for x in state.get(
            "used_gameplay",
            [],
        )
    ]


def remember_footage(
    footage_path
):

    state = load_state()

    used = state.get(
        "used_gameplay",
        [],
    )

    path_string = str(
        footage_path
    )

    used.append(
        path_string
    )

    state["used_gameplay"] = (
        used[-1000:]
    )

    save_state(
        state
    )


def reset_used_footage():

    state = load_state()

    state["used_gameplay"] = []

    save_state(
        state
    )


# ==================================================================
# UPLOAD LOG
# ==================================================================

def log_upload(
    video_id,
    title,
    category,
    ending_style,
    footage_style,
    footage_path,
):

    entry = {
        "video_id": video_id,
        "title": title,
        "category": category,
        "ending_style": ending_style,
        "footage_style": footage_style,
        "footage": str(
            footage_path
        ),
        "url": (
            f"https://youtu.be/{video_id}"
        ),
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
            )
            + "\n"
        )


# ==================================================================
# RETRY SYSTEM
# ==================================================================

def retry_with_backoff(
    fn,
    *args,
    retries=3,
    base_delay=8,
    should_retry=None,
    **kwargs,
):

    last_exc = None

    for attempt in range(
        retries
    ):

        try:

            return fn(
                *args,
                **kwargs,
            )

        except Exception as e:

            last_exc = e

            if should_retry:

                try:

                    retryable = (
                        should_retry(e)
                    )

                except Exception:

                    retryable = False

                if not retryable:

                    raise

            if (
                attempt
                >= retries - 1
            ):

                break

            delay = (
                base_delay
                * (2 ** attempt)
            )

            delay += random.uniform(
                0,
                3,
            )

            print(
                f"      Request failed: {e}"
            )

            print(
                f"      Retrying in "
                f"{delay:.1f}s..."
            )

            time.sleep(
                delay
            )

    raise last_exc


# ==================================================================
# GEMINI ERROR DETECTION
# ==================================================================

def is_model_unavailable_error(
    error
):

    message = str(
        error
    ).lower()

    markers = [
        "404",
        "not found",
        "unsupported",
        "model not found",
        "unknown model",
        "model is not available",
        "not available for your project",
        "does not exist",
    ]

    return any(
        marker in message
        for marker in markers
    )


def is_gemini_retryable_error(
    error
):

    message = str(
        error
    ).lower()

    markers = [
        "429",
        "resource_exhausted",
        "quota",
        "rate limit",
        "too many requests",
        "500",
        "internal server error",
        "502",
        "bad gateway",
        "503",
        "service unavailable",
        "high demand",
        "temporarily unavailable",
        "overloaded",
        "504",
        "deadline exceeded",
        "timeout",
        "timed out",
        "connection reset",
        "connection error",
    ]

    return any(
        marker in message
        for marker in markers
    )


# ==================================================================
# WIKIMEDIA ON THIS DAY
# ==================================================================

def fetch_on_this_day():

    today = datetime.now(
        ZoneInfo(
            "Africa/Harare"
        )
    )

    month = today.month
    day = today.day

    url = (
        "https://api.wikimedia.org/"
        "feed/v1/wikipedia/en/"
        "onthisday/all/"
        f"{month:02d}/{day:02d}"
    )

    print(
        f"      Fetching Wikimedia "
        f"events for "
        f"{month:02d}/{day:02d}..."
    )

    try:

        response = requests.get(
            url,
            headers={
                "User-Agent":
                    "SpaceFactsPipeline/8.0"
            },
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        events = data.get(
            "events",
            [],
        )

        candidates = []

        for event in events:

            year = event.get(
                "year"
            )

            text = event.get(
                "text",
                "",
            ).strip()

            pages = event.get(
                "pages",
                [],
            )

            if not text:
                continue

            page_titles = []

            for page in pages[:3]:

                page_title = page.get(
                    "title",
                    "",
                )

                if page_title:

                    page_titles.append(
                        page_title
                    )

            source_id = (
                f"wikimedia-"
                f"{month:02d}-"
                f"{day:02d}-"
                f"{year}-"
                f"{text[:100]}"
            )

            source_id = re.sub(
                r"\s+",
                "-",
                source_id.lower(),
            )

            if source_was_used(
                source_id
            ):

                continue

            candidates.append(
                {
                    "source": "Wikimedia",
                    "source_id": source_id,
                    "date": (
                        f"{month:02d}/"
                        f"{day:02d}"
                    ),
                    "year": year,
                    "text": text,
                    "pages": page_titles,
                    "category": (
                        "on_this_day"
                    ),
                }
            )

        candidates = [
            item
            for item in candidates
            if 20
            <= len(
                item["text"]
            )
            <= 500
        ]

        random.shuffle(
            candidates
        )

        candidates = candidates[
            :30
        ]

        print(
            f"      Found "
            f"{len(candidates)} "
            "usable historical "
            "events."
        )

        return candidates

    except Exception as e:

        print(
            "      Wikimedia request "
            f"failed: {e}"
        )

        return []


# ==================================================================
# OPEN TRIVIA DATABASE
# ==================================================================

def clean_trivia_text(
    text
):

    return html.unescape(
        re.sub(
            r"<[^>]+>",
            "",
            str(text),
        )
    ).strip()


def fetch_trivia():

    url = (
        "https://opentdb.com/"
        "api.php"
    )

    params = {
        "amount": 30,
        "type": "multiple",
    }

    print(
        "      Fetching general "
        "trivia..."
    )

    try:

        response = requests.get(
            url,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        results = data.get(
            "results",
            [],
        )

        candidates = []

        for item in results:

            question = (
                clean_trivia_text(
                    item.get(
                        "question",
                        "",
                    )
                )
            )

            answer = (
                clean_trivia_text(
                    item.get(
                        "correct_answer",
                        "",
                    )
                )
            )

            if (
                not question
                or not answer
            ):

                continue

            source_id = (
                "trivia-"
                + re.sub(
                    r"\s+",
                    "-",
                    question.lower(),
                )[:150]
            )

            if source_was_used(
                source_id
            ):

                continue

            candidates.append(
                {
                    "source": "OpenTDB",
                    "source_id": source_id,
                    "question": question,
                    "answer": answer,
                    "category": "trivia",
                }
            )

        print(
            f"      Found "
            f"{len(candidates)} "
            "trivia questions."
        )

        return candidates

    except Exception as e:

        print(
            "      Trivia request "
            f"failed: {e}"
        )

        return []


# ==================================================================
# EVERGREEN CANDIDATES
# ==================================================================

def get_evergreen_candidates():

    candidates = []

    shuffled = (
        EVERGREEN_TOPICS.copy()
    )

    random.shuffle(
        shuffled
    )

    for item in shuffled:

        topic_key = (
            normalize_topic_key(
                item["topic"]
            )
        )

        if topic_was_used(
            topic_key
        ):

            continue

        candidates.append(
            {
                "source": "Evergreen",
                "source_id": (
                    "evergreen-"
                    + topic_key
                ),
                "topic": item[
                    "topic"
                ],
                "text": item[
                    "topic"
                ],
                "category": item[
                    "category"
                ],
            }
        )

    return candidates


# ==================================================================
# GEMINI MODEL DISCOVERY
# ==================================================================

def get_available_gemini_models(
    client
):

    print(
        "      Discovering "
        "available Gemini models..."
    )

    try:

        available = []

        for model_info in (
            client.models.list()
        ):

            supported_actions = (
                getattr(
                    model_info,
                    "supported_actions",
                    [],
                )
                or []
            )

            if (
                "generateContent"
                not in supported_actions
            ):

                continue

            model_name = getattr(
                model_info,
                "name",
                "",
            )

            if not model_name:
                continue

            model_id = (
                model_name
                .split("/")[-1]
            )

            available.append(
                model_id
            )

        if not available:

            print(
                "      Discovery "
                "returned no models."
            )

            return (
                GEMINI_MODELS.copy()
            )

        preferred = [
            model
            for model in GEMINI_MODELS
            if model in available
        ]

        additional = [
            model
            for model in available
            if (
                "flash"
                in model.lower()
                and model
                not in preferred
            )
        ]

        models = (
            preferred
            + additional
        )

        print(
            "      Available Flash "
            "models:"
        )

        for model in models:

            print(
                f"        - {model}"
            )

        if models:

            return models

        return (
            GEMINI_MODELS.copy()
        )

    except Exception as e:

        print(
            "      Model discovery "
            f"failed: {e}"
        )

        return (
            GEMINI_MODELS.copy()
        )


# ==================================================================
# GEMINI JSON CALL
# ==================================================================

def call_gemini_json(
    prompt,
    *,
    temperature=None,
):

    from google import genai

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    models = (
        get_available_gemini_models(
            client
        )
    )

    last_error = None

    for model in models:

        print(
            f"\n      Trying Gemini "
            f"model: {model}"
        )

        def make_request():

            config = {
                "response_mime_type":
                    "application/json",
            }

            if temperature is not None:

                config[
                    "temperature"
                ] = temperature

            return (
                client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
            )

        try:

            response = (
                retry_with_backoff(
                    make_request,
                    retries=2,
                    base_delay=8,
                    should_retry=(
                        is_gemini_retryable_error
                    ),
                )
            )

            response_text = getattr(
                response,
                "text",
                None,
            )

            if not response_text:

                raise RuntimeError(
                    "Gemini returned "
                    "an empty response."
                )

            try:

                return json.loads(
                    response_text
                )

            except json.JSONDecodeError as e:

                print(
                    "      Invalid JSON "
                    "from Gemini:"
                )

                print(
                    response_text[:3000]
                )

                raise RuntimeError(
                    "Gemini returned "
                    "invalid JSON."
                ) from e

        except Exception as e:

            last_error = e

            print(
                f"      Model failed: {e}"
            )

            if (
                is_model_unavailable_error(
                    e
                )
                or is_gemini_retryable_error(
                    e
                )
            ):

                print(
                    "      Trying next "
                    "Gemini model..."
                )

                continue

            print(
                "      Trying next "
                "model anyway..."
            )

    raise RuntimeError(
        "All available Gemini "
        "models failed. "
        f"Last error: {last_error}"
    )


# ==================================================================
# TOPIC SELECTOR
# ==================================================================

TOPIC_SELECTOR_PROMPT = """
You are the topic editor for a high-retention YouTube Shorts channel.

Select ONE candidate for a broad-audience short.

The channel can cover:

- history
- strange historical events
- science
- engineering
- inventions
- technology
- transportation
- nature
- animals
- mysteries
- unusual human events
- surprising trivia

Prioritize:

- immediate curiosity
- simple premise
- surprising detail
- strong storytelling potential
- factual reliability
- a story that can be explained in 30–45 seconds
- topics that work for a worldwide audience

Avoid:

- generic boring trivia
- obscure details with no interesting angle
- conspiracy theories
- political persuasion
- unsupported claims
- repetitive subjects
- topics that need a long explanation

For historical events:
Prefer something strange, unexpected, impressive,
dangerous, mysterious, clever, or counterintuitive.

For trivia:
Prefer facts that create an immediate
"wait, really?" reaction.

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


def select_topic(
    candidates
):

    if not candidates:

        raise RuntimeError(
            "No topic candidates "
            "available."
        )

    compact = []

    for index, item in enumerate(
        candidates
    ):

        compact.append(
            {
                "index": index,
                **item,
            }
        )

    prompt = (
        TOPIC_SELECTOR_PROMPT.format(
            candidates=json.dumps(
                compact,
                ensure_ascii=False,
                indent=2,
            )
        )
    )

    result = call_gemini_json(
        prompt,
        temperature=0.65,
    )

    index = result.get(
        "selected_index"
    )

    try:

        index = int(
            index
        )

    except Exception:

        index = 0

    if (
        index < 0
        or index >= len(candidates)
    ):

        index = 0

    selected = dict(
        candidates[index]
    )

    selected["topic"] = (
        result.get(
            "topic",
            selected.get(
                "text",
                selected.get(
                    "question",
                    "interesting fact",
                ),
            ),
        )
    )

    selected["angle"] = (
        result.get(
            "angle",
            "",
        )
    )

    selected["source_summary"] = (
        result.get(
            "source_summary",
            "",
        )
    )

    return selected


# ==================================================================
# DYNAMIC TOPIC
# ==================================================================

def get_dynamic_topic():

    source = random.choices(
        [
            "on_this_day",
            "trivia",
            "evergreen",
        ],
        weights=[
            CONTENT_WEIGHTS[
                "on_this_day"
            ],
            CONTENT_WEIGHTS[
                "trivia"
            ],
            CONTENT_WEIGHTS[
                "evergreen"
            ],
        ],
        k=1,
    )[0]

    candidates = []

    if source == "on_this_day":

        candidates = (
            fetch_on_this_day()
        )

        if not candidates:

            candidates = (
                fetch_trivia()
            )

    elif source == "trivia":

        candidates = (
            fetch_trivia()
        )

        if not candidates:

            candidates = (
                fetch_on_this_day()
            )

    else:

        candidates = (
            get_evergreen_candidates()
        )

    # Add some evergreen choices to
    # live candidates when possible.
    #
    # This prevents the channel from
    # becoming too dependent on today's
    # available events.
    evergreen = (
        get_evergreen_candidates()
    )

    if candidates:

        candidates.extend(
            random.sample(
                evergreen,
                min(
                    8,
                    len(evergreen),
                ),
            )
        )

        random.shuffle(
            candidates
        )

        return select_topic(
            candidates[:40]
        )

    if evergreen:

        return select_topic(
            evergreen[:30]
        )

    print(
        "      APIs unavailable."
    )

    # Final emergency fallback.
    fallback = random.choice(
        [
            {
                "topic": (
                    "why the pyramids "
                    "still stand today"
                ),
                "category": "history",
            },
            {
                "topic": (
                    "how Roman concrete "
                    "could last for centuries"
                ),
                "category": "history",
            },
            {
                "topic": (
                    "why sharks are "
                    "older than trees"
                ),
                "category": "nature",
            },
        ]
    )

    return {
        "source": "fallback",
        "source_id": (
            "fallback-"
            + normalize_topic_key(
                fallback["topic"]
            )
        ),
        "topic": fallback[
            "topic"
        ],
        "category": fallback[
            "category"
        ],
        "angle": "",
        "source_summary": "",
    }


# ==================================================================
# STORY GENERATION PROMPT
# ==================================================================

SCRIPT_PROMPT = """
You are the lead writer for a high-retention YouTube Shorts channel.

Write ONE continuous 30–45 second story.

The background video is unrelated footage.

The narration must therefore carry the entertainment.

TOPIC:
{topic}

CATEGORY:
{category}

ANGLE:
{angle}

SOURCE INFORMATION:
{source_summary}

SOURCE MATERIAL:
{source_material}

RECENT VIDEO TITLES:
{recent_titles}

STORY REQUIREMENTS:

The first sentence must immediately create curiosity.

Do NOT start with:

- "Did you know?"
- "Have you ever wondered?"
- "Imagine this..."
- "This is crazy..."
- "You won't believe..."
- "Prepare to have your mind blown."

Instead, begin with a concrete surprising statement.

Example:

"People once spent days dancing in the streets of a European city."

Then explain why.

STRUCTURE:

1. HOOK
   One strong sentence.

2. CONTEXT
   Explain what happened.

3. ESCALATION
   Introduce the strangest or most surprising detail.

4. PAYOFF
   Give the strongest factual detail near the end.

5. ENDING
   Either naturally loop into the hook or finish with a short punchline.

STYLE:

- conversational
- fast
- natural
- confident
- factual
- easy to understand
- short sentences
- occasional longer sentence for rhythm
- contractions are encouraged
- no filler
- no fake quotes
- no fake dialogue
- no invented facts
- no unsupported claims
- no conspiracy theories
- no political persuasion
- no repetitive phrases

Target 85–115 spoken words.

IMPORTANT:

Do NOT describe the footage.

Do NOT pretend the footage is connected to the story.

FOOTAGE:

Choose ONE footage category that would visually retain attention
while the narration plays.

Available categories:

"construction"
"machines"
"cars"
"nature"
"satisfying"
"sports"
"animation"
"ocean"
"aviation"
"general"

The footage does NOT need to literally depict the story.

Prefer visually dynamic footage.

CAPTIONS:

Break the narration into short caption chunks.

Each scene should contain 2–5 chunks.

Each chunk should normally be 2–5 words.

Maximum 6 words.

Captions MUST be uppercase.

Examples:

"THIS HAPPENED"
"OVER 500 YEARS AGO"

or:

"THEY STARTED DANCING"
"FOR DAYS"
"AND NOBODY KNEW WHY"

Return ONLY valid JSON.

Exact structure:

{{
  "title": "under 60 characters",
  "hook": "first narration sentence",
  "ending_style": "loop",
  "footage_style": "construction",
  "scenes": [
    {{
      "narration": "scene narration",
      "caption_chunks": [
        "THIS HAPPENED",
        "CENTURIES AGO"
      ]
    }}
  ],
  "hashtags": [
    "#shorts",
    "#facts",
    "#history"
  ]
}}

IMPORTANT:

The narration across all scenes must form ONE continuous story.

Do not make each scene a separate fact.
"""


# ==================================================================
# SCRIPT GENERATION
# ==================================================================

def generate_script(
    topic_data,
    recent_titles,
):

    source_material = json.dumps(
        topic_data,
        ensure_ascii=False,
        indent=2,
    )

    if recent_titles:

        recent_text = "\n".join(
            f"- {title}"
            for title in recent_titles
        )

    else:

        recent_text = "None"

    prompt = SCRIPT_PROMPT.format(
        topic=topic_data.get(
            "topic",
            "",
        ),
        category=topic_data.get(
            "category",
            "",
        ),
        angle=topic_data.get(
            "angle",
            "",
        ),
        source_summary=topic_data.get(
            "source_summary",
            "",
        ),
        source_material=source_material,
        recent_titles=recent_text,
    )

    data = call_gemini_json(
        prompt,
        temperature=0.8,
    )

    validate_script(
        data
    )

    return data


# ==================================================================
# SCRIPT VALIDATION
# ==================================================================

def validate_script(
    data
):

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "Gemini script is "
            "not an object."
        )

    title = data.get(
        "title",
        "",
    )

    if not isinstance(
        title,
        str,
    ):

        raise RuntimeError(
            "Title is not a string."
        )

    title = title.strip()

    if not title:

        raise RuntimeError(
            "Empty title."
        )

    if len(title) > 60:

        title = (
            title[:57]
            .rstrip()
            + "..."
        )

    data["title"] = title

    scenes = data.get(
        "scenes"
    )

    if (
        not isinstance(
            scenes,
            list,
        )
        or not scenes
    ):

        raise RuntimeError(
            "No scenes returned."
        )

    if len(scenes) > 10:

        raise RuntimeError(
            "Too many scenes."
        )

    for scene in scenes:

        if not isinstance(
            scene,
            dict,
        ):

            raise RuntimeError(
                "Invalid scene."
            )

        narration = scene.get(
            "narration",
            "",
        )

        if (
            not isinstance(
                narration,
                str,
            )
            or not narration.strip()
        ):

            raise RuntimeError(
                "Scene has no narration."
            )

        scene[
            "narration"
        ] = narration.strip()

        chunks = scene.get(
            "caption_chunks"
        )

        if (
            not isinstance(
                chunks,
                list,
            )
            or not chunks
        ):

            words = narration.split()

            chunks = []

            for start in range(
                0,
                len(words),
                4,
            ):

                chunks.append(
                    " ".join(
                        words[
                            start:start + 4
                        ]
                    )
                )

        cleaned = []

        for chunk in chunks:

            chunk = str(
                chunk
            ).strip()

            if not chunk:

                continue

            chunk = re.sub(
                r"\s+",
                " ",
                chunk,
            )

            cleaned.append(
                chunk.upper()
            )

        if not cleaned:

            raise RuntimeError(
                "Scene has no captions."
            )

        scene[
            "caption_chunks"
        ] = cleaned

    footage_style = data.get(
        "footage_style",
        "general",
    )

    if not isinstance(
        footage_style,
        str,
    ):

        footage_style = "general"

    footage_style = (
        footage_style.lower().strip()
    )

    if (
        footage_style
        not in FOOTAGE_STYLES
    ):

        footage_style = "general"

    data[
        "footage_style"
    ] = footage_style

    hashtags = data.get(
        "hashtags",
        [],
    )

    if not isinstance(
        hashtags,
        list,
    ):

        hashtags = []

    if not hashtags:

        hashtags = [
            "#shorts",
            "#facts",
        ]

    data["hashtags"] = [
        str(x)
        for x in hashtags[:6]
    ]

    ending_style = data.get(
        "ending_style",
        "loop",
    )

    if ending_style not in (
        "loop",
        "joke",
    ):

        ending_style = "loop"

    data[
        "ending_style"
    ] = ending_style


# ==================================================================
# EDGE TTS
# ==================================================================

async def _synthesize(
    text,
    voice,
    out_path,
):

    import edge_tts

    communicate = (
        edge_tts.Communicate(
            text,
            voice,
        )
    )

    await communicate.save(
        str(out_path)
    )


def synthesize_scene_audio(
    scenes,
    run_dir,
):

    from moviepy import (
        AudioFileClip,
    )

    # IMPORTANT:
    # The voice is fixed.
    voice = TTS_VOICE

    print(
        f"      Voice: {voice}"
    )

    results = []

    for i, scene in enumerate(
        scenes
    ):

        out_path = (
            run_dir
            / f"scene_{i}.mp3"
        )

        asyncio.run(
            _synthesize(
                scene["narration"],
                voice,
                out_path,
            )
        )

        audio = AudioFileClip(
            str(out_path)
        )

        duration = audio.duration

        audio.close()

        results.append(
            {
                "path": out_path,
                "duration": duration,
            }
        )

        print(
            f"      Scene {i + 1}: "
            f"{duration:.2f}s"
        )

    return results


# ==================================================================
# FOOTAGE DISCOVERY
# ==================================================================

def get_footage_root():

    if FOOTAGE_DIR.exists():

        return FOOTAGE_DIR

    if GAMEPLAY_DIR.exists():

        print(
            "      Using legacy "
            "gameplay/ directory."
        )

        return GAMEPLAY_DIR

    return FOOTAGE_DIR


def get_footage_files():

    root = get_footage_root()

    if not root.exists():

        return []

    allowed_extensions = {
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
    }

    files = []

    for path in root.rglob(
        "*"
    ):

        if not path.is_file():

            continue

        if (
            path.suffix.lower()
            not in allowed_extensions
        ):

            continue

        files.append(
            path
        )

    return files


# ==================================================================
# FOOTAGE STYLE DETECTION
# ==================================================================

def detect_footage_style(
    path
):

    parts = [
        part.lower()
        for part in path.parts
    ]

    filename = (
        path.stem.lower()
    )

    combined = " ".join(
        parts
        + [filename]
    )

    # Order matters.
    if any(
        word in combined
        for word in [
            "construction",
            "building",
            "build",
            "bridge",
            "architecture",
        ]
    ):

        return "construction"

    if any(
        word in combined
        for word in [
            "machine",
            "factory",
            "industrial",
            "manufacturing",
            "robot",
        ]
    ):

        return "machines"

    if any(
        word in combined
        for word in [
            "car",
            "cars",
            "racing",
            "race",
            "f1",
            "formula",
            "drift",
        ]
    ):

        return "cars"

    if any(
        word in combined
        for word in [
            "nature",
            "animal",
            "wildlife",
            "forest",
            "mountain",
            "landscape",
        ]
    ):

        return "nature"

    if any(
        word in combined
        for word in [
            "satisfying",
            "oddly",
            "asmr",
            "cleaning",
            "restoration",
            "process",
        ]
    ):

        return "satisfying"

    if any(
        word in combined
        for word in [
            "sport",
            "sports",
            "football",
            "soccer",
            "basketball",
            "skate",
            "skating",
            "parkour",
        ]
    ):

        return "sports"

    if any(
        word in combined
        for word in [
            "animation",
            "animated",
            "cartoon",
        ]
    ):

        return "animation"

    if any(
        word in combined
        for word in [
            "ocean",
            "sea",
            "underwater",
            "ship",
            "submarine",
            "water",
        ]
    ):

        return "ocean"

    if any(
        word in combined
        for word in [
            "aviation",
            "airplane",
            "aircraft",
            "plane",
            "airport",
            "flight",
        ]
    ):

        return "aviation"

    # Legacy Minecraft/Roblox
    # footage can still be used.
    if (
        "minecraft"
        in combined
        or "roblox"
        in combined
    ):

        return "general"

    return "general"


# ==================================================================
# FOOTAGE SELECTION
# ==================================================================

def select_footage(
    style=None
):

    files = get_footage_files()

    if not files:

        raise RuntimeError(
            "\nNo footage videos "
            "were found.\n\n"
            "Create a footage/ "
            "folder and add videos.\n\n"
            "Example:\n"
            "footage/construction/"
            "building01.mp4\n"
            "footage/cars/"
            "racing01.mp4\n"
            "footage/nature/"
            "nature01.mp4\n"
        )

    style = (
        str(style or "general")
        .lower()
        .strip()
    )

    print(
        f"      Requested footage "
        f"style: {style}"
    )

    # --------------------------------------------------------------
    # FIRST: MATCH STYLE
    # --------------------------------------------------------------

    style_matches = []

    for path in files:

        detected = (
            detect_footage_style(
                path
            )
        )

        if detected == style:

            style_matches.append(
                path
            )

    # --------------------------------------------------------------
    # SECOND: GENERAL FOOTAGE
    # --------------------------------------------------------------

    if not style_matches:

        style_matches = [
            path
            for path in files
            if (
                detect_footage_style(
                    path
                )
                == "general"
            )
        ]

    # --------------------------------------------------------------
    # THIRD: ANY FOOTAGE
    # --------------------------------------------------------------

    if not style_matches:

        style_matches = files.copy()

    # --------------------------------------------------------------
    # AVOID RECENTLY USED FOOTAGE
    # --------------------------------------------------------------

    used = set(
        get_used_footage()
    )

    unused_matches = [
        path
        for path in style_matches
        if str(path) not in used
    ]

    # If every matching clip has
    # already been used, reset only
    # the footage pool.
    if not unused_matches:

        print(
            "      All matching footage "
            "has been used."
        )

        print(
            "      Resetting footage "
            "rotation for this category."
        )

        unused_matches = (
            style_matches
        )

        # If everything globally has
        # been used, clear the pool.
        if not unused_matches:

            reset_used_footage()

            unused_matches = files

    selected = random.choice(
        unused_matches
    )

    detected_style = (
        detect_footage_style(
            selected
        )
    )

    print(
        f"      Footage: {selected}"
    )

    print(
        f"      Detected style: "
        f"{detected_style}"
    )

    return selected


# ==================================================================
# CAPTION TIMING
# ==================================================================

def build_caption_timing(
    narration,
    caption_chunks,
    duration,
):

    if not narration.strip():

        return []

    chunks = []

    for chunk in caption_chunks:

        chunk = str(
            chunk
        ).strip()

        if not chunk:

            continue

        words = chunk.split()

        chunks.append(
            {
                "text": chunk.upper(),
                "words": max(
                    1,
                    len(words),
                ),
            }
        )

    if not chunks:

        return [
            {
                "text": narration.upper(),
                "start": 0.0,
                "end": duration,
            }
        ]

    total_words = sum(
        item["words"]
        for item in chunks
    )

    result = []

    current = 0.0

    for index, chunk in enumerate(
        chunks
    ):

        if (
            index
            == len(chunks) - 1
        ):

            end = duration

        else:

            fraction = (
                chunk["words"]
                / total_words
            )

            end = (
                current
                + duration
                * fraction
            )

        result.append(
            {
                "text": chunk["text"],
                "start": current,
                "end": end,
            }
        )

        current = end

    return result


# ==================================================================
# BACKGROUND MUSIC
# ==================================================================

def add_background_music(
    final_clip
):

    from moviepy import (
        AudioFileClip,
        CompositeAudioClip,
        afx,
    )

    if not BGM_DIR.exists():

        return final_clip

    files = list(
        BGM_DIR.glob(
            "*.mp3"
        )
    )

    if not files:

        return final_clip

    music_path = random.choice(
        files
    )

    print(
        f"      BGM: {music_path}"
    )

    bgm = AudioFileClip(
        str(music_path)
    )

    if (
        bgm.duration
        < final_clip.duration
    ):

        bgm = bgm.with_effects(
            [
                afx.AudioLoop(
                    duration=(
                        final_clip.duration
                    )
                )
            ]
        )

    else:

        bgm = bgm.subclipped(
            0,
            final_clip.duration,
        )

    bgm = bgm.with_effects(
        [
            afx.MultiplyVolume(
                0.06
            )
        ]
    )

    if final_clip.audio:

        return final_clip.with_audio(
            CompositeAudioClip(
                [
                    final_clip.audio,
                    bgm,
                ]
            )
        )

    return final_clip.with_audio(
        bgm
    )


# ==================================================================
# VIDEO PREPARATION
# ==================================================================

def prepare_footage_clip(
    footage_path,
    duration,
):

    from moviepy import (
        VideoFileClip,
        vfx,
    )

    print(
        "      Loading footage..."
    )

    clip = VideoFileClip(
        str(footage_path)
    ).without_audio()

    if not clip.duration:

        clip.close()

        raise RuntimeError(
            "Footage video has "
            "no usable duration."
        )

    # --------------------------------------------------------------
    # LOOP IF TOO SHORT
    # --------------------------------------------------------------

    if (
        clip.duration
        < duration
    ):

        print(
            "      Footage is shorter "
            "than the Short."
        )

        print(
            "      Looping footage "
            "to fill duration."
        )

        clip = clip.with_effects(
            [
                vfx.Loop(
                    duration=duration
                )
            ]
        )

    else:

        max_start = max(
            0,
            clip.duration
            - duration,
        )

        if max_start > 1:

            start = random.uniform(
                0,
                max_start,
            )

        else:

            start = 0

        clip = clip.subclipped(
            start,
            start + duration,
        )

    # --------------------------------------------------------------
    # CROP TO 9:16
    # --------------------------------------------------------------

    source_ratio = (
        clip.w
        / clip.h
    )

    target_ratio = (
        VIDEO_W
        / VIDEO_H
    )

    if (
        source_ratio
        > target_ratio
    ):

        new_width = (
            clip.h
            * target_ratio
        )

        clip = clip.with_effects(
            [
                vfx.Crop(
                    x_center=(
                        clip.w / 2
                    ),
                    width=new_width,
                )
            ]
        )

    elif (
        source_ratio
        < target_ratio
    ):

        new_height = (
            clip.w
            / target_ratio
        )

        clip = clip.with_effects(
            [
                vfx.Crop(
                    y_center=(
                        clip.h / 2
                    ),
                    height=new_height,
                )
            ]
        )

    # --------------------------------------------------------------
    # RESIZE
    # --------------------------------------------------------------

    clip = clip.with_effects(
        [
            vfx.Resize(
                height=VIDEO_H
            )
        ]
    )

    # Final width adjustment.
    if clip.w > VIDEO_W:

        clip = clip.with_effects(
            [
                vfx.Crop(
                    x_center=(
                        clip.w / 2
                    ),
                    width=VIDEO_W,
                )
            ]
        )

    elif clip.w < VIDEO_W:

        clip = clip.with_effects(
            [
                vfx.Resize(
                    width=VIDEO_W
                )
            ]
        )

    return clip.with_position(
        "center"
    )


# ==================================================================
# CAPTION CREATION
# ==================================================================

def create_caption_clip(
    text,
    start,
    duration,
):

    from moviepy import TextClip

    try:

        txt = TextClip(
            font=CAPTION_FONT_PATH,
            text=text,
            font_size=82,
            color="white",
            stroke_color="black",
            stroke_width=6,
            method="caption",
            size=(
                VIDEO_W - 160,
                320,
            ),
            text_align="center",
        )

    except TypeError:

        txt = TextClip(
            font=CAPTION_FONT_PATH,
            text=text,
            font_size=82,
            color="white",
            stroke_color="black",
            stroke_width=6,
            method="caption",
            size=(
                VIDEO_W - 160,
                None,
            ),
            text_align="center",
        )

    # Slightly higher than v7 so captions
    # don't sit too close to the bottom.
    return (
        txt
        .with_start(
            start
        )
        .with_duration(
            max(
                0.12,
                duration,
            )
        )
        .with_position(
            (
                "center",
                1120,
            )
        )
    )


# ==================================================================
# BUILD VIDEO
# ==================================================================

def build_video(
    script,
    audio_clips,
    footage_path,
    run_dir,
):

    from moviepy import (
        AudioFileClip,
        CompositeVideoClip,
        CompositeAudioClip,
    )

    if not Path(
        CAPTION_FONT_PATH
    ).exists():

        raise FileNotFoundError(
            "Missing caption font: "
            f"{CAPTION_FONT_PATH}"
        )

    # --------------------------------------------------------------
    # TOTAL DURATION
    # --------------------------------------------------------------

    total_duration = sum(
        item["duration"]
        for item in audio_clips
    )

    print(
        f"      Total duration: "
        f"{total_duration:.2f}s"
    )

    if total_duration < 20:

        print(
            "WARNING: Generated "
            "narration is unusually short."
        )

    if total_duration > 55:

        print(
            "WARNING: Generated "
            "narration is unusually long."
        )

    # --------------------------------------------------------------
    # FOOTAGE
    # --------------------------------------------------------------

    footage = (
        prepare_footage_clip(
            footage_path,
            total_duration,
        )
    )

    # --------------------------------------------------------------
    # CAPTIONS
    # --------------------------------------------------------------

    caption_layers = []

    current_time = 0.0

    for index, scene in enumerate(
        script["scenes"]
    ):

        if index >= len(
            audio_clips
        ):

            break

        scene_duration = (
            audio_clips[
                index
            ]["duration"]
        )

        timing = (
            build_caption_timing(
                scene[
                    "narration"
                ],
                scene[
                    "caption_chunks"
                ],
                scene_duration,
            )
        )

        for caption in timing:

            caption_duration = (
                caption["end"]
                - caption["start"]
            )

            txt = (
                create_caption_clip(
                    caption["text"],
                    current_time
                    + caption["start"],
                    caption_duration,
                )
            )

            caption_layers.append(
                txt
            )

        current_time += (
            scene_duration
        )

    # --------------------------------------------------------------
    # NARRATION AUDIO
    # --------------------------------------------------------------

    audio_layers = []

    current_time = 0.0

    for item in audio_clips:

        audio = AudioFileClip(
            str(item["path"])
        )

        audio = audio.with_start(
            current_time
        )

        audio_layers.append(
            audio
        )

        current_time += (
            item["duration"]
        )

    narration_audio = (
        CompositeAudioClip(
            audio_layers
        )
    )

    # --------------------------------------------------------------
    # VIDEO COMPOSITE
    # --------------------------------------------------------------

    final = CompositeVideoClip(
        [
            footage,
            *caption_layers,
        ],
        size=(
            VIDEO_W,
            VIDEO_H,
        ),
    )

    final = final.with_audio(
        narration_audio
    )

    # --------------------------------------------------------------
    # BACKGROUND MUSIC
    # --------------------------------------------------------------

    final = add_background_music(
        final
    )

    # --------------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------------

    out_path = (
        run_dir
        / "final_video.mp4"
    )

    print(
        "\n      Rendering video..."
    )

    final.write_videofile(
        str(out_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        preset="medium",
    )

    # --------------------------------------------------------------
    # CLEANUP
    # --------------------------------------------------------------

    try:
        footage.close()
    except Exception:
        pass

    try:
        narration_audio.close()
    except Exception:
        pass

    try:
        final.close()
    except Exception:
        pass

    for audio in audio_layers:

        try:
            audio.close()
        except Exception:
            pass

    return out_path


# ==================================================================
# MAIN PIPELINE
# ==================================================================

def run_pipeline():

    validate_environment()

    print(
        "\n=================================================="
    )

    print(
        "SPACE FACTS PIPELINE v8"
    )

    print(
        "RANDOM TOPIC + RANDOM FOOTAGE FORMAT"
    )

    print(
        "=================================================="
    )

    # --------------------------------------------------------------
    # 1. TOPIC
    # --------------------------------------------------------------

    print(
        "\nFetching a fresh random topic..."
    )

    topic_data = (
        get_dynamic_topic()
    )

    topic = topic_data.get(
        "topic",
        "interesting historical fact",
    )

    category = topic_data.get(
        "category",
        "history",
    )

    source_id = topic_data.get(
        "source_id",
        "",
    )

    print(
        f"\nTopic: {topic}"
    )

    print(
        f"Category: {category}"
    )

    print(
        "Source: "
        + str(
            topic_data.get(
                "source",
                "unknown",
            )
        )
    )

    # --------------------------------------------------------------
    # 2. SCRIPT
    # --------------------------------------------------------------

    print(
        "\n[1/6] Generating story..."
    )

    recent_titles = (
        get_recent_titles()
    )

    script = generate_script(
        topic_data,
        recent_titles,
    )

    print(
        f"\n      Title: "
        f"{script['title']}"
    )

    print(
        f"      Scenes: "
        f"{len(script['scenes'])}"
    )

    print(
        "      Footage style: "
        + script[
            "footage_style"
        ]
    )

    print(
        "      Voice: "
        + TTS_VOICE
    )

    # --------------------------------------------------------------
    # 3. FOOTAGE
    # --------------------------------------------------------------

    print(
        "\n[2/6] Selecting footage..."
    )

    footage_path = (
        select_footage(
            script.get(
                "footage_style",
                "general",
            )
        )
    )

    # --------------------------------------------------------------
    # RUN DIRECTORY
    # --------------------------------------------------------------

    safe_title = "".join(
        character
        for character in script[
            "title"
        ]
        if (
            character.isalnum()
            or character in (
                " ",
                "_",
                "-",
            )
        )
    )

    safe_title = (
        safe_title.strip()
        .replace(
            " ",
            "_",
        )
    )

    if not safe_title:

        safe_title = "short"

    run_dir = (
        OUTPUT_DIR
        / safe_title[:50]
    )

    if run_dir.exists():

        run_dir = (
            OUTPUT_DIR
            / (
                safe_title[:40]
                + "_"
                + datetime.now(
                    ZoneInfo(
                        "Africa/Harare"
                    )
                ).strftime(
                    "%Y%m%d_%H%M%S"
                )
            )
        )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------------
    # SAVE METADATA
    # --------------------------------------------------------------

    (
        run_dir
        / "script.json"
    ).write_text(
        json.dumps(
            {
                "topic": topic_data,
                "script": script,
                "footage": str(
                    footage_path
                ),
                "voice": TTS_VOICE,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------------
    # 4. AUDIO
    # --------------------------------------------------------------

    print(
        "\n[3/6] Synthesizing narration..."
    )

    audio_clips = (
        synthesize_scene_audio(
            script["scenes"],
            run_dir,
        )
    )

    # --------------------------------------------------------------
    # 5. VIDEO
    # --------------------------------------------------------------

    print(
        "\n[4/6] Building Short..."
    )

    final_path = build_video(
        script,
        audio_clips,
        footage_path,
        run_dir,
    )

    # --------------------------------------------------------------
    # 6. YOUTUBE
    # --------------------------------------------------------------

    print(
        "\n[5/6] Uploading to YouTube..."
    )

    hashtags = script.get(
        "hashtags",
        [
            "#shorts",
            "#facts",
        ],
    )

    description = (
        script.get(
            "hook",
            "",
        )
        + "\n\n"
        + " ".join(
            hashtags
        )
    )

    upload_result = (
        youtube_upload.upload_video(
            file_path=str(
                final_path
            ),
            title=script[
                "title"
            ],
            description=description,
            tags=[
                hashtag.replace(
                    "#",
                    "",
                )
                for hashtag
                in hashtags
            ],
            privacy_status="public",
        )
    )

    video_id = (
        upload_result["id"]
    )

    # --------------------------------------------------------------
    # ONLY MARK AS USED AFTER
    # SUCCESSFUL UPLOAD
    # --------------------------------------------------------------

    if source_id:

        remember_source(
            source_id
        )

    topic_key = (
        normalize_topic_key(
            topic
        )
    )

    if topic_key:

        remember_topic(
            topic_key
        )

    record_used_title(
        script["title"]
    )

    remember_footage(
        footage_path
    )

    log_upload(
        video_id,
        script["title"],
        category,
        script.get(
            "ending_style",
            "loop",
        ),
        script.get(
            "footage_style",
            "general",
        ),
        footage_path,
    )

    print(
        "\n[6/6] Saving state..."
    )

    print(
        "\n=================================================="
    )

    print(
        "DONE"
    )

    print(
        "=================================================="
    )

    print(
        f"Topic: {topic}"
    )

    print(
        f"Footage: {footage_path}"
    )

    print(
        f"Voice: {TTS_VOICE}"
    )

    print(
        f"Video: {final_path}"
    )

    print(
        f"YouTube: "
        f"https://youtu.be/{video_id}"
    )

    return final_path


# ==================================================================
# ENTRY POINT
# ==================================================================

if __name__ == "__main__":

    try:

        run_pipeline()

    except KeyboardInterrupt:

        print(
            "\nPipeline cancelled."
        )

        raise

    except Exception as e:

        print(
            "\n=================================================="
        )

        print(
            "PIPELINE FAILED"
        )

        print(
            "=================================================="
        )

        print(
            str(e)
        )

        raise