"""
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v7)

FORMAT:
    Minecraft / Roblox / satisfying gameplay
    +
    Interesting history / trivia narration
    +
    Dynamic captions

PIPELINE:
1. Fetch fresh "On This Day" historical events and/or trivia
2. Select a strong topic with Gemini
3. Generate a 30–45 second story
4. Generate narration with Edge TTS
5. Select gameplay footage from gameplay/
6. Crop gameplay to 1080x1920
7. Add dynamic captions
8. Assemble the Short
9. Upload to YouTube

GAMEPLAY FOLDER:

gameplay/
├── minecraft/
│   ├── build01.mp4
│   ├── build02.mp4
│   └── gameplay01.mp4
│
├── roblox/
│   ├── build01.mp4
│   └── gameplay01.mp4
│
└── satisfying/
    ├── parkour01.mp4
    └── build01.mp4

The pipeline recursively searches gameplay/ for:
.mp4, .mov, .webm, .mkv

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
    "on_this_day": 0.70,
    "trivia": 0.30,
}


# ==================================================================
# TEXT TO SPEECH
# ==================================================================

TTS_VOICES = [
    "en-GB-RyanNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]


# ==================================================================
# FALLBACK TOPICS
# ==================================================================

FALLBACK_TOPICS = [
    {
        "topic": (
            "why the pyramids still stand "
            "after thousands of years"
        ),
        "category": "history",
    },
    {
        "topic": (
            "how ancient Roman concrete "
            "could repair itself"
        ),
        "category": "history",
    },
    {
        "topic": (
            "why the Antikythera mechanism "
            "was so advanced"
        ),
        "category": "history",
    },
    {
        "topic": (
            "why the Voynich manuscript "
            "remains undecoded"
        ),
        "category": "history",
    },
    {
        "topic": (
            "why astronauts experience "
            "slightly different aging"
        ),
        "category": "science",
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

    if not GAMEPLAY_DIR.exists():

        print(
            f"WARNING: Gameplay directory "
            f"does not exist: {GAMEPLAY_DIR}"
        )

        print(
            "Create gameplay/ and add "
            "your gameplay videos."
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

            return json.loads(
                STATE_FILE.read_text(
                    encoding="utf-8"
                )
            )

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


# ==================================================================
# UPLOAD LOG
# ==================================================================

def log_upload(
    video_id,
    title,
    category,
    ending_style,
):

    entry = {
        "video_id": video_id,
        "title": title,
        "category": category,
        "ending_style": ending_style,
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

    # Zimbabwe local date.
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
                    "SpaceFactsPipeline/7.0"
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
        "amount": 20,
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
You are the topic editor for a YouTube Shorts channel.

Select ONE candidate for a broad-audience short.

Prioritize:

- immediate curiosity
- simple premise
- surprising detail
- strong storytelling potential
- factual reliability
- a story that can be explained in 30–45 seconds

Avoid:

- generic boring trivia
- obscure details with no interesting angle
- conspiracy theories
- political persuasion
- unsupported claims
- repetitive subjects
- topics that need a long explanation

For historical events:
Prefer events involving something strange, unexpected, impressive,
dangerous, mysterious, clever, or counterintuitive.

For trivia:
Prefer facts that create an immediate "wait, really?" reaction.

Return ONLY valid JSON.

{{
  "selected_index": 0,
  "topic": "short topic description",
  "category": "on_this_day",
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
        temperature=0.5,
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
        ],
        weights=[
            CONTENT_WEIGHTS[
                "on_this_day"
            ],
            CONTENT_WEIGHTS[
                "trivia"
            ],
        ],
        k=1,
    )[0]

    if (
        source
        == "on_this_day"
    ):

        candidates = (
            fetch_on_this_day()
        )

        if candidates:

            return select_topic(
                candidates
            )

        candidates = (
            fetch_trivia()
        )

        if candidates:

            return select_topic(
                candidates
            )

    else:

        candidates = (
            fetch_trivia()
        )

        if candidates:

            return select_topic(
                candidates
            )

        candidates = (
            fetch_on_this_day()
        )

        if candidates:

            return select_topic(
                candidates
            )

    print(
        "      APIs unavailable."
    )

    print(
        "      Using fallback topic."
    )

    fallback = random.choice(
        FALLBACK_TOPICS
    )

    return {
        "source": "fallback",
        "source_id": (
            "fallback-"
            + fallback["topic"]
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

The video uses Minecraft, Roblox, building, parkour, or satisfying
gameplay as the background.

The gameplay is NOT related to the story.

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

Do NOT describe the gameplay.

Do NOT pretend the gameplay is connected to the story.

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

GAMEPLAY:

The program automatically chooses the gameplay.

Choose the general gameplay style that would work best:

"building"
"parkour"
"satisfying"
"adventure"

Return ONLY valid JSON.

Exact structure:

{{
  "title": "under 60 characters",
  "hook": "first narration sentence",
  "ending_style": "loop",
  "gameplay_style": "building",
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

    # YouTube title target:
    # under 60 characters.
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

    gameplay_style = data.get(
        "gameplay_style",
        "building",
    )

    allowed_styles = [
        "building",
        "parkour",
        "satisfying",
        "adventure",
    ]

    if (
        gameplay_style
        not in allowed_styles
    ):

        gameplay_style = "building"

    data[
        "gameplay_style"
    ] = gameplay_style

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
            "#history",
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

    voice = random.choice(
        TTS_VOICES
    )

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
# GAMEPLAY DISCOVERY
# ==================================================================

def get_gameplay_files():

    if not GAMEPLAY_DIR.exists():

        return []

    allowed_extensions = {
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
    }

    files = []

    for path in GAMEPLAY_DIR.rglob(
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


def detect_gameplay_style(
    path
):

    parts = [
        part.lower()
        for part in path.parts
    ]

    filename = path.stem.lower()

    combined = " ".join(
        parts
        + [filename]
    )

    if "roblox" in combined:

        return "roblox"

    if "minecraft" in combined:

        return "minecraft"

    if "parkour" in combined:

        return "parkour"

    if "build" in combined:

        return "building"

    if "satisfying" in combined:

        return "satisfying"

    return "general"


def select_gameplay(
    style=None
):

    files = get_gameplay_files()

    if not files:

        raise RuntimeError(
            "\nNo gameplay videos "
            "were found.\n\n"
            "Create a gameplay/ "
            "folder and add your "
            "videos.\n\n"
            "Example:\n"
            "gameplay/minecraft/"
            "build01.mp4\n"
            "gameplay/roblox/"
            "build01.mp4\n"
        )

    # Try to match the style.
    if style:

        style_matches = []

        for path in files:

            detected = (
                detect_gameplay_style(
                    path
                )
            )

            # Minecraft and Roblox
            # are both treated as
            # building/general footage.
            if (
                style.lower()
                in detected.lower()
                or detected.lower()
                in style.lower()
            ):

                style_matches.append(
                    path
                )

            elif (
                style == "building"
                and detected
                in (
                    "minecraft",
                    "roblox",
                    "building",
                )
            ):

                style_matches.append(
                    path
                )

        if style_matches:

            files = style_matches

    selected = random.choice(
        files
    )

    print(
        f"      Gameplay: "
        f"{selected}"
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
# GAMEPLAY VIDEO PREPARATION
# ==================================================================

def prepare_gameplay_clip(
    gameplay_path,
    duration,
):

    from moviepy import (
        VideoFileClip,
        vfx,
    )

    print(
        "      Loading gameplay..."
    )

    clip = VideoFileClip(
        str(gameplay_path)
    ).without_audio()

    if not clip.duration:

        clip.close()

        raise RuntimeError(
            "Gameplay video has "
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
            "      Gameplay is shorter "
            "than the Short."
        )

        print(
            "      Looping gameplay "
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
                1230,
            )
        )
    )


# ==================================================================
# BUILD VIDEO
# ==================================================================

def build_video(
    script,
    audio_clips,
    gameplay_path,
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
    # GAMEPLAY
    # --------------------------------------------------------------

    gameplay = (
        prepare_gameplay_clip(
            gameplay_path,
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
            gameplay,
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
        gameplay.close()
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
        "SPACE FACTS PIPELINE v7"
    )

    print(
        "GAMEPLAY SHORTS FORMAT"
    )

    print(
        "=================================================="
    )

    # --------------------------------------------------------------
    # 1. TOPIC
    # --------------------------------------------------------------

    print(
        "\nFetching a fresh topic..."
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
        "\n[1/5] Generating story..."
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
        "      Gameplay style: "
        + script[
            "gameplay_style"
        ]
    )

    # --------------------------------------------------------------
    # 3. GAMEPLAY
    # --------------------------------------------------------------

    print(
        "\n[2/5] Selecting gameplay..."
    )

    gameplay_path = (
        select_gameplay(
            script.get(
                "gameplay_style",
                "building",
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

    # Prevent accidental collision.
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

    # Save metadata.
    (
        run_dir
        / "script.json"
    ).write_text(
        json.dumps(
            {
                "topic": topic_data,
                "script": script,
                "gameplay": str(
                    gameplay_path
                ),
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
        "\n[3/5] Synthesizing narration..."
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
        "\n[4/5] Building gameplay Short..."
    )

    final_path = build_video(
        script,
        audio_clips,
        gameplay_path,
        run_dir,
    )

    # --------------------------------------------------------------
    # 6. YOUTUBE
    # --------------------------------------------------------------

    print(
        "\n[5/5] Uploading to YouTube..."
    )

    hashtags = script.get(
        "hashtags",
        [
            "#shorts",
            "#facts",
            "#history",
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
    # ONLY MARK TOPIC USED AFTER SUCCESSFUL UPLOAD
    # --------------------------------------------------------------

    if source_id:

        remember_source(
            source_id
        )

    remember_topic(
        topic
    )

    record_used_title(
        script["title"]
    )

    log_upload(
        video_id,
        script["title"],
        category,
        script.get(
            "ending_style",
            "loop",
        ),
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
        f"Gameplay: {gameplay_path}"
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