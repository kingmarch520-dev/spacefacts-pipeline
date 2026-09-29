"""
==================================================================
SPACE FACTS CHANNEL — AUTOMATED SHORTS PIPELINE (v3)
==================================================================
GitHub Actions / local Python pipeline.

One run:
1. Pick a topic
2. Generate a script with Gemini
3. Generate narration with Edge TTS
4. Source visuals from Pexels / Pollinations
5. Assemble the Short with MoviePy
6. Upload to YouTube as public

IMPORTANT:
- Uses the modern google-genai SDK.
- Gemini 429 errors are retried with exponential backoff.
- A topic is only marked as used AFTER Gemini successfully
  generates the script.
==================================================================
"""

import os
import json
import random
import asyncio
import time
import requests

from pathlib import Path

import youtube_upload


# ==================================================================
# CONFIG
# ==================================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# Change this if your Gemini project uses another available model.
GEMINI_MODEL = "gemini-3.6-flash"

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


# ------------------------------------------------------------------
# CATEGORY WEIGHTS
# ------------------------------------------------------------------

CATEGORY_WEIGHTS = {
    "space": 0.55,
    "history": 0.45,
}


# ------------------------------------------------------------------
# EDGE TTS VOICES
# ------------------------------------------------------------------

TTS_VOICES = [
    "en-GB-RyanNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]


# ==================================================================
# TOPICS
# ==================================================================

TOPIC_POOL = [
    # --------------------------------------------------------------
    # SPACE
    # --------------------------------------------------------------

    {
        "topic": "gravitational time dilation near a black hole",
        "category": "space",
    },
    {
        "topic": "what a neutron star's density actually means",
        "category": "space",
    },
    {
        "topic": "why the observable universe has an edge",
        "category": "space",
    },
    {
        "topic": "spaghettification near a black hole's event horizon",
        "category": "space",
    },
    {
        "topic": "how fast the Milky Way is actually moving",
        "category": "space",
    },
    {
        "topic": "what would happen if you fell into a wormhole",
        "category": "space",
    },
    {
        "topic": "why space is completely silent",
        "category": "space",
    },
    {
        "topic": "how close we've actually gotten to absolute zero",
        "category": "space",
    },
    {
        "topic": "the size of the largest known star compared to the sun",
        "category": "space",
    },
    {
        "topic": "why time moves slower for astronauts on the ISS",
        "category": "space",
    },
    {
        "topic": "what dark matter actually does to galaxies",
        "category": "space",
    },
    {
        "topic": "how a supernova could theoretically threaten Earth",
        "category": "space",
    },
    {
        "topic": "why Jupiter's Great Red Spot has lasted for centuries",
        "category": "space",
    },
    {
        "topic": "what a rogue planet drifting with no star actually looks like",
        "category": "space",
    },
    {
        "topic": "how astronauts' bodies actually change after months in orbit",
        "category": "space",
    },
    {
        "topic": "why Venus spins backward compared to almost every other planet",
        "category": "space",
    },
    {
        "topic": "what would really happen if the sun vanished for one second",
        "category": "space",
    },
    {
        "topic": "how close the nearest black hole actually is to Earth",
        "category": "space",
    },
    {
        "topic": "how big the largest known structure in the entire universe actually is",
        "category": "space",
    },
    {
        "topic": "how much of the periodic table can only be made inside a dying star",
        "category": "space",
    },

    # --------------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------------

    {
        "topic": "how the Antikythera mechanism baffled experts for a century",
        "category": "history",
    },
    {
        "topic": "how the pyramids at Giza were actually built without modern tools",
        "category": "history",
    },
    {
        "topic": "what really happened to the Library of Alexandria",
        "category": "history",
    },
    {
        "topic": "why the Voynich manuscript still hasn't been decoded",
        "category": "history",
    },
    {
        "topic": "how an entire Roman legion vanished without a trace",
        "category": "history",
    },
    {
        "topic": "what the Baghdad Battery might have actually been used for",
        "category": "history",
    },
    {
        "topic": "how ancient Rome's concrete outlasts modern concrete",
        "category": "history",
    },
    {
        "topic": "what the Dancing Plague of 1518 actually did to people",
        "category": "history",
    },
    {
        "topic": "how the Bronze Age Collapse wiped out multiple civilizations at once",
        "category": "history",
    },
    {
        "topic": "what really caused the Tunguska explosion",
        "category": "history",
    },
    {
        "topic": "how the Nazca Lines were made without ever being seen from above",
        "category": "history",
    },
    {
        "topic": "what happened to the lost colony of Roanoke",
        "category": "history",
    },
    {
        "topic": "how the Iron Pillar of Delhi has resisted rust for over 1,600 years",
        "category": "history",
    },
    {
        "topic": "why the Sutton Hoo ship burial rewrote what historians knew about early England",
        "category": "history",
    },
    {
        "topic": "what the Rosetta Stone actually took decades to fully decode",
        "category": "history",
    },
    {
        "topic": "how Greek fire's exact recipe was lost to history forever",
        "category": "history",
    },
    {
        "topic": "why the city of Petra was carved directly into solid rock",
        "category": "history",
    },
    {
        "topic": "how the Terracotta Army was hidden and undiscovered for over 2,000 years",
        "category": "history",
    },
    {
        "topic": "what really caused the sudden collapse of the Maya civilization",
        "category": "history",
    },
    {
        "topic": "why the Phaistos Disc's symbols still can't be translated",
        "category": "history",
    },
]


# ==================================================================
# VALIDATION
# ==================================================================

def validate_environment():
    """Check required environment variables before starting."""

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
# STATE HANDLING
# ==================================================================

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )
        except Exception as e:
            print(f"Warning: Could not read state file: {e}")

    return {
        "category_progress": {},
        "recent_titles": [],
    }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )


def get_category_topics(category: str) -> list:
    return [
        t
        for t in TOPIC_POOL
        if t["category"] == category
    ]


def get_next_topic():
    """
    Select the next topic.

    IMPORTANT:
    This function does NOT save progress.

    The topic is only marked as used after Gemini successfully
    generates a script.
    """

    state = load_state()

    state.setdefault("category_progress", {})

    categories = list(CATEGORY_WEIGHTS.keys())

    weights = [
        CATEGORY_WEIGHTS[c]
        for c in categories
    ]

    chosen_category = random.choices(
        categories,
        weights=weights,
        k=1,
    )[0]

    category_topics = get_category_topics(
        chosen_category
    )

    if not category_topics:
        raise RuntimeError(
            f"No topics found for category: {chosen_category}"
        )

    progress = state["category_progress"].get(
        chosen_category
    )

    if (
        not progress
        or "order" not in progress
        or "position" not in progress
        or progress["position"] >= len(progress["order"])
    ):
        order = list(
            range(len(category_topics))
        )

        random.shuffle(order)

        progress = {
            "order": order,
            "position": 0,
        }

    topic_index = progress["order"][
        progress["position"]
    ]

    topic_entry = category_topics[topic_index]

    return (
        topic_entry,
        chosen_category,
        progress,
    )


def commit_topic_progress(
    category: str,
    progress: dict,
):
    """
    Mark the selected topic as used.

    Called ONLY after successful script generation.
    """

    state = load_state()

    state.setdefault(
        "category_progress",
        {},
    )

    progress["position"] += 1

    state["category_progress"][category] = progress

    save_state(state)


def record_used_title(title: str):
    state = load_state()

    recent = state.get(
        "recent_titles",
        [],
    )

    recent.append(title)

    state["recent_titles"] = recent[-40:]

    save_state(state)


def get_recent_titles() -> list:
    return load_state().get(
        "recent_titles",
        [],
    )


def log_upload(
    video_id: str,
    title: str,
    category: str,
    ending_style: str,
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
# RETRY HELPER
# ==================================================================

def retry_with_backoff(
    fn,
    *args,
    retries=4,
    base_delay=20,
    should_retry=None,
    **kwargs,
):
    """
    Retry a function using exponential backoff.

    Default:
        20s
        40s
        80s

    This is intentionally slower than the old 3/6/12 second
    strategy because Gemini free-tier 429s can require a longer
    wait before the request becomes available again.
    """

    last_exc = None

    for attempt in range(retries):

        try:
            return fn(*args, **kwargs)

        except Exception as e:

            last_exc = e

            if should_retry is not None:

                try:
                    retryable = should_retry(e)
                except Exception:
                    retryable = False

                if not retryable:
                    print(
                        f"      Not retrying error: {e}"
                    )
                    raise

            if attempt >= retries - 1:
                break

            delay = (
                base_delay
                * (2 ** attempt)
            )

            # Small random component prevents synchronized
            # retries if multiple GitHub jobs are running.
            delay += random.uniform(0, 3)

            print(
                f"      Request failed: {e}"
            )

            print(
                f"      Retrying in "
                f"{delay:.1f}s..."
            )

            time.sleep(delay)

    raise last_exc


# ==================================================================
# GEMINI SCRIPT GENERATION
# ==================================================================

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
     a mental reference for.
  2. Lead with a specific number or stat before any setup.
  3. Direct address framed as a personal stake.
  4. False premise, immediate correction.
  5. Blunt, ominous fact fragment, no lead-in at all.

Prefer pattern 1 when a genuinely apt comparison exists.

Do NOT use generic hook filler like "did you know" or
"here's a fact that will blow your mind."

ENDING:
- If ending_style is "loop": the FINAL scene must end mid-thought or
  lead seamlessly into the very first word of the hook, so the video
  loops endlessly with no visible seam.
- If ending_style is "joke": the FINAL scene must be a short joke or
  pun directly related to the fact. One line, genuinely funny, not a
  generic dad joke.

TITLE:
- Use curiosity-gap framing.
- Under 60 characters.
- No misleading clickbait.
- Avoid "terrifying", "insane", "shocking" in the title.

SCENES:
Break the script into scenes.

Each scene is one or two sentences of narration.

For each scene provide a visual.

visual_type:
- "literal" if real stock footage exists.
- "abstract" if it is a concept with no suitable real footage.

visual_query:
- For "literal": 3-6 word stock footage search term.
- For "abstract": descriptive AI image generation prompt.

Return ONLY valid JSON.

Exact shape:

{{
  "title": "short punchy YouTube title, under 60 characters",
  "hook": "the first scene's narration",
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


def is_gemini_retryable_error(e) -> bool:
    """
    Gemini API errors.

    429 / RESOURCE_EXHAUSTED:
        Retry.

    Other API/network errors:
        Also retry because transient network/API failures can recover.
    """

    msg = str(e).lower()

    if (
        "429" in msg
        or "resource_exhausted" in msg
        or "quota" in msg
        or "rate limit" in msg
    ):
        print(
            "      Gemini quota/rate limit detected."
        )

    return True


def generate_script(
    topic: str,
    ending_style: str,
    recent_titles: list = None,
) -> dict:

    if recent_titles:

        titles_list = "\n".join(
            f"- {t}"
            for t in recent_titles
        )

        recent_titles_block = (
            "AVOID RESEMBLING RECENT VIDEOS — "
            "these titles were made recently "
            "on this channel. Even if today's "
            "topic is technically different, "
            "do not produce a hook, angle, or "
            "framing that would feel like a "
            "repeat to a viewer:\n"
            + titles_list
        )

    else:
        recent_titles_block = ""

    prompt = SCRIPT_SYSTEM_PROMPT.format(
        topic=topic,
        ending_style=ending_style,
        recent_titles_block=recent_titles_block,
    )

    # --------------------------------------------------------------
    # Modern Gemini SDK
    # --------------------------------------------------------------

    from google import genai

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    def _call_gemini():

        return client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            },
        )

    response = retry_with_backoff(
        _call_gemini,
        retries=4,
        base_delay=20,
        should_retry=is_gemini_retryable_error,
    )

    if not response.text:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    try:
        data = json.loads(
            response.text
        )

    except json.JSONDecodeError as e:

        print(
            "Gemini returned invalid JSON:"
        )

        print(response.text)

        raise RuntimeError(
            "Gemini response was not valid JSON."
        ) from e

    # --------------------------------------------------------------
    # Validate response
    # --------------------------------------------------------------

    if "title" not in data:
        raise RuntimeError(
            "Gemini response has no title."
        )

    if "scenes" not in data:
        raise RuntimeError(
            "Gemini response has no scenes."
        )

    if not data["scenes"]:
        raise RuntimeError(
            "Gemini returned zero scenes."
        )

    for scene in data["scenes"]:

        if "narration" not in scene:
            raise RuntimeError(
                "Scene is missing narration."
            )

        if "visual_type" not in scene:
            raise RuntimeError(
                "Scene is missing visual_type."
            )

        if "visual_query" not in scene:
            raise RuntimeError(
                "Scene is missing visual_query."
            )

        if scene["visual_type"] not in (
            "literal",
            "abstract",
        ):
            raise RuntimeError(
                "Invalid visual_type: "
                + str(scene["visual_type"])
            )

    return data


# ==================================================================
# EDGE TTS
# ==================================================================

async def _synthesize(
    text: str,
    voice: str,
    out_path: Path,
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
    scenes: list,
    run_dir: Path,
) -> list:

    from moviepy import AudioFileClip

    voice = random.choice(
        TTS_VOICES
    )

    print(
        f"      Voice: {voice}"
    )

    results = []

    for i, scene in enumerate(scenes):

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
    query: str,
    out_path: Path,
) -> Path | None:

    if not PEXELS_API_KEY:
        print(
            "      PEXELS_API_KEY missing."
        )
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
        "per_page": 5,
    }

    try:

        r = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20,
        )

        r.raise_for_status()

        videos = r.json().get(
            "videos",
            [],
        )

        if not videos:
            return None

        video = random.choice(
            videos[
                : min(3, len(videos))
            ]
        )

        files = sorted(
            video["video_files"],
            key=lambda f: f.get(
                "width",
                0,
            ),
        )

        chosen = next(
            (
                f
                for f in files
                if f.get("width", 0)
                >= 720
            ),
            files[-1],
        )

        video_data = requests.get(
            chosen["link"],
            timeout=30,
        ).content

        out_path.write_bytes(
            video_data
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

def _fetch_pollinations_image_once(
    prompt: str,
    out_path: Path,
) -> Path:

    import urllib.parse

    encoded = urllib.parse.quote(
        prompt
    )

    url = (
        "https://image.pollinations.ai/"
        f"prompt/{encoded}"
        "?width=1080"
        "&height=1920"
        "&nologo=true"
    )

    r = requests.get(
        url,
        timeout=60,
    )

    r.raise_for_status()

    content_type = r.headers.get(
        "content-type",
        "",
    )

    if not content_type.startswith(
        "image/"
    ):
        raise RuntimeError(
            "Pollinations did not return "
            "an image. "
            f"Content-Type: {content_type}"
        )

    out_path.write_bytes(
        r.content
    )

    return out_path


def _generate_fallback_image(
    prompt: str,
    out_path: Path,
) -> Path:

    from PIL import (
        Image,
        ImageDraw,
        ImageFont,
    )

    import textwrap

    img = Image.new(
        "RGB",
        (
            VIDEO_W,
            VIDEO_H,
        ),
        color=(10, 10, 20),
    )

    draw = ImageDraw.Draw(img)

    for y in range(VIDEO_H):

        shade = int(
            10
            + (
                y
                / VIDEO_H
            )
            * 40
        )

        draw.line(
            [
                (0, y),
                (VIDEO_W, y),
            ],
            fill=(
                shade,
                shade,
                shade + 15,
            ),
        )

    try:

        font = ImageFont.truetype(
            CAPTION_FONT_PATH,
            60,
        )

    except Exception:

        font = ImageFont.load_default()

    wrapped = textwrap.fill(
        prompt,
        width=28,
    )

    draw.multiline_text(
        (
            80,
            VIDEO_H // 2 - 150,
        ),
        wrapped,
        fill=(
            220,
            220,
            220,
        ),
        font=font,
        spacing=16,
    )

    img.save(
        out_path
    )

    return out_path


def fetch_pollinations_image(
    prompt: str,
    out_path: Path,
) -> Path:

    try:

        return retry_with_backoff(
            _fetch_pollinations_image_once,
            prompt,
            out_path,
            retries=3,
            base_delay=5,
        )

    except Exception as e:

        print(
            "      Pollinations failed "
            "after retries."
        )

        print(
            f"      Using local fallback: {e}"
        )

        return _generate_fallback_image(
            prompt,
            out_path,
        )


# ==================================================================
# VISUAL SELECTION
# ==================================================================

def fetch_visual_for_scene(
    scene: dict,
    index: int,
    run_dir: Path,
) -> dict:

    if scene["visual_type"] == "literal":

        out_path = (
            run_dir
            / f"visual_{index}.mp4"
        )

        result = fetch_pexels_video(
            scene["visual_query"],
            out_path,
        )

        if result:

            return {
                "type": "video",
                "path": result,
            }

        print(
            "      No Pexels video found."
        )

        print(
            "      Falling back to Pollinations."
        )

        fallback_path = (
            run_dir
            / f"visual_{index}.jpg"
        )

        fetch_pollinations_image(
            scene["visual_query"],
            fallback_path,
        )

        return {
            "type": "image",
            "path": fallback_path,
        }

    else:

        out_path = (
            run_dir
            / f"visual_{index}.jpg"
        )

        fetch_pollinations_image(
            scene["visual_query"],
            out_path,
        )

        return {
            "type": "image",
            "path": out_path,
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

    bgm_files = list(
        BGM_DIR.glob("*.mp3")
    )

    if not bgm_files:
        return final_clip

    bgm_path = random.choice(
        bgm_files
    )

    bgm = AudioFileClip(
        str(bgm_path)
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
            afx.MultiplyVolume(0.10)
        ]
    )

    combined_audio = CompositeAudioClip(
        [
            final_clip.audio,
            bgm,
        ]
    )

    return final_clip.with_audio(
        combined_audio
    )


# ==================================================================
# VIDEO ASSEMBLY
# ==================================================================

def build_video(
    script: dict,
    audio_clips: list,
    visuals: list,
    run_dir: Path,
) -> Path:

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
            "Caption font does not exist:\n"
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
        # VIDEO VISUAL
        # ----------------------------------------------------------

        if visual["type"] == "video":

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

        # ----------------------------------------------------------
        # IMAGE VISUAL
        # ----------------------------------------------------------

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
        # RESIZE
        # ----------------------------------------------------------

        clip = clip.with_effects(
            [
                vfx.Resize(
                    height=VIDEO_H
                )
            ]
        ).with_position(
            "center"
        )

        # ----------------------------------------------------------
        # CAPTIONS
        # ----------------------------------------------------------

        caption = TextClip(
            font=CAPTION_FONT_PATH,
            text=scene["narration"],
            font_size=54,
            color="yellow",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(
                VIDEO_W - 120,
                None,
            ),
            text_align="center",
            duration=duration,
        ).with_position(
            (
                "center",
                "center",
            )
        )

        composite = CompositeVideoClip(
            [
                clip,
                caption,
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
    # BACKGROUND MUSIC
    # --------------------------------------------------------------

    final = add_background_music(
        final
    )

    # --------------------------------------------------------------
    # WRITE VIDEO
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
    )

    # Clean up MoviePy resources.
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

    # --------------------------------------------------------------
    # SELECT TOPIC
    # --------------------------------------------------------------

    (
        topic_entry,
        category,
        progress,
    ) = get_next_topic()

    topic = topic_entry["topic"]

    ending_style = random.choice(
        [
            "loop",
            "joke",
        ]
    )

    print(
        "\n=================================================="
    )

    print(
        "SPACE FACTS PIPELINE"
    )

    print(
        "=================================================="
    )

    print(
        f"Topic: {topic}"
    )

    print(
        f"Category: {category}"
    )

    print(
        f"Ending: {ending_style}"
    )

    # --------------------------------------------------------------
    # 1. GEMINI
    # --------------------------------------------------------------

    print(
        "\n[1/5] Generating script..."
    )

    recent_titles = get_recent_titles()

    try:

        script = generate_script(
            topic,
            ending_style,
            recent_titles=recent_titles,
        )

    except Exception as e:

        print(
            "\n=================================================="
        )

        print(
            "GEMINI FAILED"
        )

        print(
            "=================================================="
        )

        print(
            str(e)
        )

        print(
            "\nThe topic was NOT marked as used."
        )

        print(
            "The next successful run can retry it."
        )

        raise

    # --------------------------------------------------------------
    # IMPORTANT:
    # Commit topic only AFTER Gemini succeeds.
    # --------------------------------------------------------------

    commit_topic_progress(
        category,
        progress,
    )

    print(
        f"      Title: {script['title']}"
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
        )[:40]
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
            script,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------------
    # 2. AUDIO
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
    # 3. VISUALS
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
            f"{scene['visual_type']}"
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
    # 4. VIDEO
    # --------------------------------------------------------------

    print(
        "\n[4/5] Assembling final video..."
    )

    final_path = build_video(
        script,
        audio_clips,
        visuals,
        run_dir,
    )

    # --------------------------------------------------------------
    # 5. YOUTUBE
    # --------------------------------------------------------------

    print(
        "\n[5/5] Uploading to YouTube..."
    )

    description = (
        f"{script.get('hook', '')}"
        f"\n\n"
        f"{' '.join(script['hashtags'])}"
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
                for h in script[
                    "hashtags"
                ]
            ],
            privacy_status="public",
        )
    )

    video_id = upload_result["id"]

    log_upload(
        video_id,
        script["title"],
        category,
        ending_style,
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