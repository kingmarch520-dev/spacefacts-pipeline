"""
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v5)

Pipeline:
1. Fetch fresh "On This Day" historical events and/or trivia
2. Select a strong topic with Gemini
3. Generate a 30–45 second Shorts script
4. Generate short caption chunks designed for Shorts
5. Generate narration with Edge TTS
6. Fetch visuals from Pexels / Pollinations
7. Assemble a 1080x1920 Short
8. Upload to YouTube as public

No fixed topic pool is required for the daily history/trivia engine.

Existing infrastructure preserved:
- Gemini model discovery + fallback
- Pexels
- Pollinations
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import youtube_upload


# ==================================================================
# CONFIG
# ==================================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

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

STATE_FILE = Path("state_spacefacts.json")
UPLOAD_LOG_FILE = Path("upload_log.jsonl")

OUTPUT_DIR = Path("output_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)

VIDEO_W = 1080
VIDEO_H = 1920

CAPTION_FONT_PATH = str(
    Path(__file__).parent / "Anton-Regular.ttf"
)

BGM_DIR = Path(__file__).parent / "bgm"


# ==================================================================
# CONTENT MIX
# ==================================================================

# Fresh historical events are the main content source.
#
# The values don't have to total exactly 1.0, but they do here
# for clarity.

CONTENT_WEIGHTS = {
    "on_this_day": 0.50,
    "trivia": 0.25,
    "history": 0.15,
    "building": 0.10,
}


# ==================================================================
# EDGE TTS
# ==================================================================

TTS_VOICES = [
    "en-GB-RyanNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]


# ==================================================================
# GENERAL FALLBACK TOPICS
# ==================================================================

FALLBACK_TOPICS = [
    {
        "topic": "why the pyramids still stand after thousands of years",
        "category": "building",
    },
    {
        "topic": "how ancient Roman concrete could repair itself",
        "category": "building",
    },
    {
        "topic": "why the Antikythera mechanism was so advanced",
        "category": "history",
    },
    {
        "topic": "why the Voynich manuscript remains undecoded",
        "category": "history",
    },
    {
        "topic": "why space is silent",
        "category": "space",
    },
    {
        "topic": "why astronauts age slightly differently in orbit",
        "category": "space",
    },
]


# ==================================================================
# ENVIRONMENT
# ==================================================================

def validate_environment():

    missing = []

    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")

    if not PEXELS_API_KEY:
        missing.append("PEXELS_API_KEY")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
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
                f"Warning: Could not read state file: {e}"
            )

    return {
        "recent_titles": [],
        "used_source_ids": [],
        "used_topic_keys": [],
        "last_content_date": "",
    }


def save_state(state):

    STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_recent_titles():

    return load_state().get(
        "recent_titles",
        [],
    )


def record_used_title(title):

    state = load_state()

    recent = state.get(
        "recent_titles",
        [],
    )

    recent.append(title)

    state["recent_titles"] = recent[-40:]

    save_state(state)


def remember_source(source_id):

    state = load_state()

    used = state.get(
        "used_source_ids",
        [],
    )

    if source_id:
        used.append(str(source_id))

    state["used_source_ids"] = used[-300:]

    save_state(state)


def source_was_used(source_id):

    state = load_state()

    return str(source_id) in [
        str(x)
        for x in state.get(
            "used_source_ids",
            [],
        )
    ]


def remember_topic(topic_key):

    state = load_state()

    used = state.get(
        "used_topic_keys",
        [],
    )

    if topic_key:
        used.append(topic_key)

    state["used_topic_keys"] = used[-300:]

    save_state(state)


def topic_was_used(topic_key):

    state = load_state()

    return topic_key in state.get(
        "used_topic_keys",
        [],
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
        "url": f"https://youtu.be/{video_id}",
    }

    with open(
        UPLOAD_LOG_FILE,
        "a",
        encoding="utf-8",
    ) as f:

        f.write(
            json.dumps(entry)
            + "\n"
        )


# ==================================================================
# RETRY
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

    for attempt in range(retries):

        try:

            return fn(
                *args,
                **kwargs
            )

        except Exception as e:

            last_exc = e

            if should_retry is not None:

                try:
                    retryable = should_retry(e)
                except Exception:
                    retryable = False

                if not retryable:
                    raise

            if attempt >= retries - 1:
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
                f"      Retrying in {delay:.1f}s..."
            )

            time.sleep(delay)

    raise last_exc


# ==================================================================
# GEMINI ERROR DETECTION
# ==================================================================

def is_model_unavailable_error(e):

    msg = str(e).lower()

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
        marker in msg
        for marker in markers
    )


def is_gemini_retryable_error(e):

    msg = str(e).lower()

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
        marker in msg
        for marker in markers
    )


# ==================================================================
# WIKIMEDIA — ON THIS DAY
# ==================================================================

def fetch_on_this_day():

    today = datetime.now(
        timezone.utc
    )

    month = today.month
    day = today.day

    url = (
        "https://api.wikimedia.org/feed/v1/"
        f"wikipedia/en/onthisday/all/"
        f"{month:02d}/{day:02d}"
    )

    print(
        f"      Fetching Wikimedia events for "
        f"{month:02d}/{day:02d}..."
    )

    try:

        response = requests.get(
            url,
            headers={
                "User-Agent":
                    "SpaceFactsPipeline/5.0"
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

                title = page.get(
                    "title",
                    "",
                )

                if title:
                    page_titles.append(
                        title
                    )

            source_id = (
                f"wikimedia-{month:02d}-"
                f"{day:02d}-{year}-"
                f"{hash(text)}"
            )

            if source_was_used(
                source_id
            ):
                continue

            candidates.append(
                {
                    "source": "Wikimedia",
                    "source_id": source_id,
                    "date": f"{month:02d}/{day:02d}",
                    "year": year,
                    "text": text,
                    "pages": page_titles,
                    "category": "on_this_day",
                }
            )

        # Remove extremely long/weak entries.
        candidates = [
            x
            for x in candidates
            if 20 <= len(
                x["text"]
            ) <= 500
        ]

        random.shuffle(
            candidates
        )

        candidates = candidates[:25]

        print(
            f"      Found {len(candidates)} "
            "usable historical events."
        )

        return candidates

    except Exception as e:

        print(
            f"      Wikimedia request failed: {e}"
        )

        return []


# ==================================================================
# OPEN TRIVIA DATABASE
# ==================================================================

def clean_trivia_text(text):

    return html.unescape(
        re.sub(
            r"<[^>]+>",
            "",
            text,
        )
    ).strip()


def fetch_trivia():

    url = (
        "https://opentdb.com/api.php"
    )

    params = {
        "amount": 20,
        "type": "multiple",
    }

    print(
        "      Fetching general trivia..."
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

        for index, item in enumerate(
            results
        ):

            question = clean_trivia_text(
                item.get(
                    "question",
                    "",
                )
            )

            answer = clean_trivia_text(
                item.get(
                    "correct_answer",
                    "",
                )
            )

            if not question or not answer:
                continue

            candidates.append(
                {
                    "source": "OpenTDB",
                    "source_id": (
                        f"trivia-{hash(question)}"
                    ),
                    "question": question,
                    "answer": answer,
                    "category": "trivia",
                }
            )

        print(
            f"      Found {len(candidates)} "
            "trivia questions."
        )

        return candidates

    except Exception as e:

        print(
            f"      Trivia request failed: {e}"
        )

        return []


# ==================================================================
# GEMINI MODEL DISCOVERY
# ==================================================================

def get_available_gemini_models(client):

    print(
        "      Discovering available Gemini models..."
    )

    try:

        available = []

        for model_info in client.models.list():

            supported_actions = getattr(
                model_info,
                "supported_actions",
                [],
            ) or []

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

            model_id = model_name.split(
                "/"
            )[-1]

            available.append(
                model_id
            )

        if not available:

            print(
                "      Discovery returned no models."
            )

            return GEMINI_MODELS.copy()

        preferred = [
            model
            for model in GEMINI_MODELS
            if model in available
        ]

        additional = [
            model
            for model in available
            if (
                "flash" in model.lower()
                and model not in preferred
            )
        ]

        models = (
            preferred
            + additional
        )

        print(
            "      Available Flash models:"
        )

        for model in models:
            print(
                f"        - {model}"
            )

        return (
            models
            if models
            else GEMINI_MODELS.copy()
        )

    except Exception as e:

        print(
            f"      Model discovery failed: {e}"
        )

        print(
            "      Using configured fallback list."
        )

        return GEMINI_MODELS.copy()


# ==================================================================
# GEMINI GENERIC CALL
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

    models = get_available_gemini_models(
        client
    )

    last_error = None

    for model in models:

        print(
            f"\n      Trying Gemini model: {model}"
        )

        def _call():

            config = {
                "response_mime_type":
                    "application/json",
            }

            if temperature is not None:
                config["temperature"] = temperature

            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )

        try:

            response = retry_with_backoff(
                _call,
                retries=2,
                base_delay=8,
                should_retry=is_gemini_retryable_error,
            )

            if not response.text:
                raise RuntimeError(
                    "Gemini returned an empty response."
                )

            try:

                return json.loads(
                    response.text
                )

            except json.JSONDecodeError as e:

                print(
                    "      Invalid JSON from Gemini:"
                )

                print(
                    response.text[:3000]
                )

                raise RuntimeError(
                    "Gemini returned invalid JSON."
                ) from e

        except Exception as e:

            last_error = e

            print(
                f"      Model failed: {e}"
            )

            if (
                is_model_unavailable_error(e)
                or is_gemini_retryable_error(e)
            ):

                print(
                    "      Trying next Gemini model..."
                )

                continue

            print(
                "      Trying next model anyway..."
            )

    raise RuntimeError(
        "All available Gemini models failed. "
        f"Last error: {last_error}"
    )


# ==================================================================
# TOPIC SELECTION
# ==================================================================

TOPIC_SELECTOR_PROMPT = """
You are the topic editor for a YouTube Shorts channel.

Today's content candidates are below.

Your job is to select ONE topic that has the strongest potential
for a broad audience.

Prioritize:

1. Immediate curiosity
2. Easy-to-understand premise
3. A surprising fact or reversal
4. Strong visual possibilities
5. Enough substance for 30–45 seconds
6. A story that can be understood without prior knowledge
7. Factual reliability

Avoid:

- Extremely obscure subjects with no clear hook
- Topics requiring lots of dates or names
- Political persuasion
- Unverified conspiracy theories
- Repetitive topics
- Generic trivia with an obvious answer
- Clickbait that the facts cannot support

Do not explain your choice.

Return ONLY JSON:

{
  "selected_index": 0,
  "topic": "short topic description",
  "category": "on_this_day",
  "angle": "the specific story angle",
  "source_summary": "brief factual basis"
}

CANDIDATES:

{candidates}
"""


def select_topic(candidates):

    if not candidates:
        raise RuntimeError(
            "No topic candidates available."
        )

    compact = []

    for i, item in enumerate(
        candidates
    ):

        compact.append(
            {
                "index": i,
                **item,
            }
        )

    prompt = TOPIC_SELECTOR_PROMPT.format(
        candidates=json.dumps(
            compact,
            ensure_ascii=False,
            indent=2,
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
        index = int(index)
    except Exception:
        index = 0

    if index < 0 or index >= len(
        candidates
    ):
        index = 0

    selected = candidates[index]

    selected = dict(
        selected
    )

    selected["topic"] = result.get(
        "topic",
        selected.get(
            "text",
            selected.get(
                "question",
                "interesting historical fact",
            ),
        ),
    )

    selected["angle"] = result.get(
        "angle",
        "",
    )

    selected["source_summary"] = result.get(
        "source_summary",
        "",
    )

    return selected


# ==================================================================
# DYNAMIC TOPIC INGESTION
# ==================================================================

def get_dynamic_topic():

    weighted_source = random.choices(
        [
            "on_this_day",
            "trivia",
        ],
        weights=[
            0.70,
            0.30,
        ],
        k=1,
    )[0]

    candidates = []

    if weighted_source == "on_this_day":

        candidates = fetch_on_this_day()

        if candidates:

            return select_topic(
                candidates
            )

        print(
            "      Falling back to trivia."
        )

        candidates = fetch_trivia()

        if candidates:
            return select_topic(
                candidates
            )

    else:

        candidates = fetch_trivia()

        if candidates:

            return select_topic(
                candidates
            )

        print(
            "      Falling back to On This Day."
        )

        candidates = fetch_on_this_day()

        if candidates:
            return select_topic(
                candidates
            )

    # --------------------------------------------------------------
    # Last-resort static topic.
    # --------------------------------------------------------------

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
            f"fallback-{hash(fallback['topic'])}"
        ),
        "topic": fallback["topic"],
        "category": fallback["category"],
        "angle": "",
        "source_summary": "",
    }


# ==================================================================
# SCRIPT PROMPT
# ==================================================================

SCRIPT_PROMPT = """
You are the lead writer for a high-quality YouTube Shorts channel.

Write a 30–45 second factual Short.

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

Your job is NOT to write like a documentary.

Write like a smart person telling a friend something they genuinely
wouldn't expect.

STORY STRUCTURE:

1. HOOK — first 1–2 sentences
   Immediately reveal the strange, surprising, or useful part.

2. CONTEXT
   Give only the minimum information needed to understand the story.

3. ESCALATION
   Introduce the detail that makes the story more interesting.

4. PAYOFF
   Give the strongest fact near the end.

5. ENDING
   Make the final sentence either:
   - naturally loop into the beginning, OR
   - deliver a short relevant punchline.

STYLE:

- Conversational.
- Natural contractions.
- Short sentences mixed with occasional longer ones.
- No "Did you know?"
- No "Prepare to have your mind blown."
- No "This isn't science fiction..."
- No fake suspense.
- No repetitive "But here's the crazy part."
- No unnecessary dates.
- No unnecessary names.
- No exaggerated claims.
- No unsupported claims.
- Never invent facts.
- Avoid sounding like AI.
- Avoid repeating the title in the narration.

The first sentence must be strong enough to stop someone scrolling.

The entire narration should normally be about 80–110 words.

CAPTIONS:

For every scene, provide 2–5 short caption chunks.

Each chunk should contain only a few words.

Bad:
"Ancient Roman engineers built aqueducts that transported water
across enormous distances."

Good:
"ROMAN ENGINEERS"
"BUILT AQUEDUCTS"
"THAT MOVED WATER"
"FOR MILES"

Caption chunks should be:
- easy to read instantly
- visually punchy
- synchronized naturally with narration
- maximum 6 words
- normally 2–5 words
- written in uppercase

VISUALS:

Each scene needs a visual.

Use "literal" when stock footage is likely to exist.

Use "abstract" when an AI-generated image is better.

For literal visuals:
visual_query must be 3–6 words.

For abstract visuals:
visual_query must be a detailed cinematic vertical-image prompt.

Return ONLY valid JSON.

Exact structure:

{{
  "title": "under 60 characters",
  "hook": "first narration sentence",
  "ending_style": "loop",
  "scenes": [
    {{
      "narration": "scene narration",
      "caption_chunks": [
        "SHORT CAPTION",
        "CHUNK HERE"
      ],
      "visual_type": "literal",
      "visual_query": "3-6 word search"
    }}
  ],
  "hashtags": [
    "#shorts",
    "#history",
    "#facts"
  ]
}}

IMPORTANT:
The narration across all scenes must form one continuous story.

Do not make every scene feel like a separate fact.
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

    recent_text = (
        "\n".join(
            f"- {title}"
            for title in recent_titles
        )
        if recent_titles
        else "None"
    )

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

    validate_script(data)

    return data


# ==================================================================
# SCRIPT VALIDATION
# ==================================================================

def validate_script(data):

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "Gemini script is not an object."
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

    data["title"] = title[:100]

    scenes = data.get(
        "scenes"
    )

    if not isinstance(
        scenes,
        list,
    ):

        raise RuntimeError(
            "Scenes is not a list."
        )

    if not scenes:

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

        if not isinstance(
            narration,
            str,
        ) or not narration.strip():

            raise RuntimeError(
                "Scene has no narration."
            )

        scene[
            "narration"
        ] = narration.strip()

        visual_type = scene.get(
            "visual_type"
        )

        if visual_type not in (
            "literal",
            "abstract",
        ):

            raise RuntimeError(
                "Invalid visual_type."
            )

        visual_query = scene.get(
            "visual_query",
            "",
        )

        if not str(
            visual_query
        ).strip():

            raise RuntimeError(
                "Scene has no visual query."
            )

        scene[
            "visual_query"
        ] = str(
            visual_query
        ).strip()

        chunks = scene.get(
            "caption_chunks"
        )

        if not isinstance(
            chunks,
            list,
        ) or not chunks:

            # Safe fallback if Gemini forgets.
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
                    ).upper()
                )

        cleaned_chunks = []

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

            cleaned_chunks.append(
                chunk.upper()
            )

        if not cleaned_chunks:

            raise RuntimeError(
                "Scene has no usable captions."
            )

        scene[
            "caption_chunks"
        ] = cleaned_chunks

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

    if data.get(
        "ending_style"
    ) not in (
        "loop",
        "joke",
    ):

        data["ending_style"] = "loop"


# ==================================================================
# EDGE TTS
# ==================================================================

async def _synthesize(
    text,
    voice,
    out_path,
):

    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        voice,
    )

    await communicate.save(
        str(out_path)
    )


def synthesize_scene_audio(
    scenes,
    run_dir,
):

    from moviepy import AudioFileClip

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

    return results


# ==================================================================
# PEXELS
# ==================================================================

def fetch_pexels_video(
    query,
    out_path,
):

    if not PEXELS_API_KEY:
        return None

    headers = {
        "Authorization": PEXELS_API_KEY
    }

    url = (
        "https://api.pexels.com/videos/search"
    )

    params = {
        "query": query,
        "orientation": "portrait",
        "per_page": 8,
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        videos = response.json().get(
            "videos",
            [],
        )

        if not videos:
            return None

        # Prefer videos with useful dimensions.
        valid = []

        for video in videos:

            files = video.get(
                "video_files",
                [],
            )

            if files:
                valid.append(
                    video
                )

        if not valid:
            return None

        video = random.choice(
            valid[
                :min(5, len(valid))
            ]
        )

        files = video.get(
            "video_files",
            [],
        )

        files = sorted(
            files,
            key=lambda f: (
                f.get(
                    "width",
                    0,
                )
                * f.get(
                    "height",
                    0,
                )
            ),
            reverse=True,
        )

        chosen = None

        for file_info in files:

            width = file_info.get(
                "width",
                0,
            )

            height = file_info.get(
                "height",
                0,
            )

            if (
                width >= 720
                or height >= 720
            ):

                chosen = file_info
                break

        if chosen is None:
            chosen = files[0]

        link = chosen.get(
            "link"
        )

        if not link:
            return None

        video_response = requests.get(
            link,
            timeout=45,
        )

        video_response.raise_for_status()

        out_path.write_bytes(
            video_response.content
        )

        return out_path

    except Exception as e:

        print(
            f"      Pexels failed: {e}"
        )

        return None


# ==================================================================
# POLLINATIONS
# ==================================================================

def fetch_pollinations_image_once(
    prompt,
    out_path,
):

    encoded = quote(
        prompt
    )

    url = (
        "https://image.pollinations.ai/"
        f"prompt/{encoded}"
        "?width=1080"
        "&height=1920"
        "&nologo=true"
    )

    response = requests.get(
        url,
        timeout=90,
    )

    response.raise_for_status()

    content_type = response.headers.get(
        "content-type",
        "",
    )

    if not content_type.startswith(
        "image/"
    ):

        raise RuntimeError(
            "Pollinations did not return an image."
        )

    out_path.write_bytes(
        response.content
    )

    return out_path


def generate_fallback_image(
    prompt,
    out_path,
):

    from PIL import (
        Image,
        ImageDraw,
        ImageFont,
    )

    img = Image.new(
        "RGB",
        (
            VIDEO_W,
            VIDEO_H,
        ),
        (8, 8, 18),
    )

    draw = ImageDraw.Draw(
        img
    )

    for y in range(
        VIDEO_H
    ):

        ratio = y / VIDEO_H

        value = int(
            8 + ratio * 42
        )

        draw.line(
            [
                (0, y),
                (VIDEO_W, y),
            ],
            fill=(
                value,
                value,
                min(
                    255,
                    value + 18,
                ),
            ),
        )

    try:

        font = ImageFont.truetype(
            CAPTION_FONT_PATH,
            58,
        )

    except Exception:

        font = ImageFont.load_default()

    text = str(
        prompt
    )

    draw.multiline_text(
        (
            80,
            VIDEO_H // 2 - 150,
        ),
        text[:500],
        font=font,
        fill=(230, 230, 230),
        spacing=16,
    )

    img.save(
        out_path
    )

    return out_path


def fetch_pollinations_image(
    prompt,
    out_path,
):

    try:

        return retry_with_backoff(
            fetch_pollinations_image_once,
            prompt,
            out_path,
            retries=2,
            base_delay=5,
        )

    except Exception as e:

        print(
            f"      Pollinations failed: {e}"
        )

        print(
            "      Using local fallback image."
        )

        return generate_fallback_image(
            prompt,
            out_path,
        )


# ==================================================================
# VISUALS
# ==================================================================

def fetch_visual_for_scene(
    scene,
    index,
    run_dir,
):

    if scene[
        "visual_type"
    ] == "literal":

        path = (
            run_dir
            / f"visual_{index}.mp4"
        )

        result = fetch_pexels_video(
            scene["visual_query"],
            path,
        )

        if result:

            return {
                "type": "video",
                "path": result,
            }

        print(
            "      Pexels unavailable."
        )

        print(
            "      Using AI visual instead."
        )

    path = (
        run_dir
        / f"visual_{index}.jpg"
    )

    fetch_pollinations_image(
        scene["visual_query"],
        path,
    )

    return {
        "type": "image",
        "path": path,
    }


# ==================================================================
# BACKGROUND MUSIC
# ==================================================================

def add_background_music(
    final_clip,
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

    path = random.choice(
        files
    )

    bgm = AudioFileClip(
        str(path)
    )

    if bgm.duration < final_clip.duration:

        bgm = bgm.with_effects(
            [
                afx.AudioLoop(
                    duration=final_clip.duration
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
                0.08
            )
        ]
    )

    return final_clip.with_audio(
        CompositeAudioClip(
            [
                final_clip.audio,
                bgm,
            ]
        )
    )


# ==================================================================
# CAPTION TIMING
# ==================================================================

def build_caption_timing(
    narration,
    caption_chunks,
    duration,
):

    words = narration.split()

    if not words:
        return []

    total_words = len(
        words
    )

    chunks = []

    for chunk in caption_chunks:

        chunk_words = chunk.split()

        if chunk_words:
            chunks.append(
                {
                    "text": chunk,
                    "words": len(
                        chunk_words
                    ),
                }
            )

    if not chunks:

        return [
            {
                "text": narration.upper(),
                "start": 0,
                "end": duration,
            }
        ]

    total_chunk_words = sum(
        x["words"]
        for x in chunks
    )

    if total_chunk_words <= 0:
        total_chunk_words = total_words

    result = []

    current = 0.0

    for index, chunk in enumerate(
        chunks
    ):

        if index == len(chunks) - 1:

            end = duration

        else:

            fraction = (
                chunk["words"]
                / total_chunk_words
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
# VIDEO ASSEMBLY
# ==================================================================

def build_video(
    script,
    audio_clips,
    visuals,
    run_dir,
):

    from moviepy import (
        AudioFileClip,
        ImageClip,
        VideoFileClip,
        CompositeVideoClip,
        TextClip,
        concatenate_videoclips,
        vfx,
    )

    if not Path(
        CAPTION_FONT_PATH
    ).exists():

        raise FileNotFoundError(
            "Missing caption font:\n"
            f"{CAPTION_FONT_PATH}\n\n"
            "Commit Anton-Regular.ttf to the "
            "repository root."
        )

    scene_clips = []

    for i, scene in enumerate(
        script["scenes"]
    ):

        audio = AudioFileClip(
            str(
                audio_clips[i]["path"]
            )
        )

        duration = audio.duration

        visual = visuals[i]

        # ----------------------------------------------------------
        # VISUAL
        # ----------------------------------------------------------

        if visual[
            "type"
        ] == "video":

            clip = VideoFileClip(
                str(
                    visual["path"]
                )
            ).without_audio()

            if clip.duration < duration:

                clip = clip.with_effects(
                    [
                        vfx.Loop(
                            duration=duration
                        )
                    ]
                )

            else:

                clip = clip.subclipped(
                    0,
                    duration,
                )

        else:

            clip = (
                ImageClip(
                    str(
                        visual["path"]
                    )
                )
                .with_duration(
                    duration
                )
            )

        # ----------------------------------------------------------
        # FILL VERTICAL FRAME
        # ----------------------------------------------------------

        clip = clip.with_effects(
            [
                vfx.Resize(
                    height=VIDEO_H
                )
            ]
        )

        # Crop any width overflow.
        if clip.w > VIDEO_W:

            clip = clip.with_effects(
                [
                    vfx.Crop(
                        x_center=clip.w / 2,
                        width=VIDEO_W,
                    )
                ]
            )

        clip = clip.with_position(
            "center"
        )

        # ----------------------------------------------------------
        # CAPTION CHUNKS
        # ----------------------------------------------------------

        caption_timing = build_caption_timing(
            scene["narration"],
            scene["caption_chunks"],
            duration,
        )

        caption_clips = []

        for caption in caption_timing:

            text = caption["text"]

            try:

                txt = TextClip(
                    font=CAPTION_FONT_PATH,
                    text=text,
                    font_size=78,
                    color="white",
                    stroke_color="black",
                    stroke_width=5,
                    method="caption",
                    size=(
                        VIDEO_W - 180,
                        300,
                    ),
                    text_align="center",
                )

            except TypeError:

                txt = TextClip(
                    font=CAPTION_FONT_PATH,
                    text=text,
                    font_size=78,
                    color="white",
                    stroke_color="black",
                    stroke_width=5,
                    method="caption",
                    size=(
                        VIDEO_W - 180,
                        None,
                    ),
                    text_align="center",
                )

            txt = (
                txt
                .with_start(
                    caption["start"]
                )
                .with_duration(
                    max(
                        0.1,
                        caption["end"]
                        - caption["start"],
                    )
                )
                .with_position(
                    (
                        "center",
                        1250,
                    )
                )
            )

            caption_clips.append(
                txt
            )

        # ----------------------------------------------------------
        # SCENE COMPOSITE
        # ----------------------------------------------------------

        composite = CompositeVideoClip(
            [
                clip,
                *caption_clips,
            ],
            size=(
                VIDEO_W,
                VIDEO_H,
            ),
        )

        composite = composite.with_audio(
            audio
        )

        scene_clips.append(
            composite
        )

    # --------------------------------------------------------------
    # CONCATENATE
    # --------------------------------------------------------------

    final = concatenate_videoclips(
        scene_clips,
        method="compose",
    )

    # --------------------------------------------------------------
    # MUSIC
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

    final.write_videofile(
        str(out_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=2,
    )

    try:
        final.close()
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
        "SPACE FACTS PIPELINE v5"
    )

    print(
        "=================================================="
    )

    print(
        "Fetching a fresh topic..."
    )

    # --------------------------------------------------------------
    # 1. TOPIC
    # --------------------------------------------------------------

    topic_data = get_dynamic_topic()

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
        f"Source: {topic_data.get('source', 'unknown')}"
    )

    # --------------------------------------------------------------
    # 2. SCRIPT
    # --------------------------------------------------------------

    print(
        "\n[1/5] Generating story..."
    )

    recent_titles = get_recent_titles()

    try:

        script = generate_script(
            topic_data,
            recent_titles,
        )

    except Exception as e:

        print(
            "\n=================================================="
        )

        print(
            "SCRIPT GENERATION FAILED"
        )

        print(
            "=================================================="
        )

        print(
            str(e)
        )

        print(
            "\nThe source topic was NOT marked as used."
        )

        raise

    print(
        f"\n      Title: {script['title']}"
    )

    print(
        f"      Scenes: {len(script['scenes'])}"
    )

    # --------------------------------------------------------------
    # Mark topic used ONLY after successful script generation.
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

    # --------------------------------------------------------------
    # RUN DIRECTORY
    # --------------------------------------------------------------

    safe_title = "".join(
        c
        for c in script["title"]
        if c.isalnum()
        or c in (
            " ",
            "_",
            "-",
        )
    )

    run_dir = (
        OUTPUT_DIR
        / safe_title.replace(
            " ",
            "_",
        )[:50]
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        run_dir
        / "script.json"
    ).write_text(
        json.dumps(
            {
                "topic": topic_data,
                "script": script,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------------
    # 3. AUDIO
    # --------------------------------------------------------------

    print(
        "\n[2/5] Synthesizing narration..."
    )

    audio_clips = (
        synthesize_scene_audio(
            script["scenes"],
            run_dir,
        )
    )

    # --------------------------------------------------------------
    # 4. VISUALS
    # --------------------------------------------------------------

    print(
        "\n[3/5] Fetching visuals..."
    )

    visuals = []

    for i, scene in enumerate(
        script["scenes"]
    ):

        print(
            f"      Scene {i + 1}/"
            f"{len(script['scenes'])}: "
            f"{scene['visual_type']} — "
            f"{scene['visual_query']}"
        )

        visual = fetch_visual_for_scene(
            scene,
            i,
            run_dir,
        )

        visuals.append(
            visual
        )

    # --------------------------------------------------------------
    # 5. VIDEO
    # --------------------------------------------------------------

    print(
        "\n[4/5] Assembling Short..."
    )

    final_path = build_video(
        script,
        audio_clips,
        visuals,
        run_dir,
    )

    # --------------------------------------------------------------
    # 6. YOUTUBE
    # --------------------------------------------------------------

    print(
        "\n[5/5] Uploading to YouTube..."
    )

    description = (
        script.get(
            "hook",
            "",
        )
        + "\n\n"
        + " ".join(
            script["hashtags"]
        )
    )

    upload_result = (
        youtube_upload.upload_video(
            file_path=str(
                final_path
            ),
            title=script["title"],
            description=description,
            tags=[
                h.replace(
                    "#",
                    "",
                )
                for h in script["hashtags"]
            ],
            privacy_status="public",
        )
    )

    video_id = upload_result["id"]

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
        f"Video: {final_path}"
    )

    print(
        f"YouTube: https://youtu.be/{video_id}"
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