"""
==================================================================
SPACE/PHYSICS + HISTORY FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab / GitHub Actions.

TWO LANES ONLY — space/physics and history.

TARGET LENGTH: 20-30 seconds (60-75 words, 4 scenes).

GEMINI MODEL CHAIN: tries each model in order. Each has its own
quota pool, so when one is exhausted the next usually has room.
Model-unavailable (404) errors also fall through to the next model
instead of failing the run.

REQUIRED INSTALLS (Colab + GitHub Actions pip line):
    !pip install google-generativeai edge-tts moviepy pillow requests --quiet
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
print(f"DEBUG — key prefix: {GEMINI_API_KEY[:8]}...")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "PASTE_YOUR_KEY_HERE")

STATE_FILE = Path("state_spacefacts.json")
OUTPUT_DIR = Path("output_spacefacts")
OUTPUT_DIR.mkdir(exist_ok=True)

BGM_DIR = Path(__file__).parent / "bgm"

VIDEO_W, VIDEO_H = 1080, 1920

CAPTION_FONT_PATH = str(Path(__file__).parent / "Anton-Regular.ttf")

TTS_VOICES = [
    "en-GB-RyanNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
]

CATEGORY_WEIGHTS = {
    "space": 0.55,
    "history": 0.45,
}

PUBLIC_PUBLISH_CHANCE = 0.5

# Models tried in order. Each model has its own per-project quota
# pool, so when one is exhausted the next usually has room.
# gemini-3.8-flash is the current model Google's own 404 messages
# point new accounts to. The older ones are kept as fallbacks in
# case 3.8 is temporarily overloaded.
GEMINI_MODEL_CHAIN = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

# ------------------------------------------------------------------
# INSPIRATION TRANSCRIPTS
# ------------------------------------------------------------------

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

    # Space lane — best performer, tightened.
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
# STATE
# ------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"category_progress": {}, "recent_titles": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_category_topics(category):
    return [t for t in TOPIC_POOL if t["category"] == category]


def get_recent_titles():
    return load_state().get("recent_titles", [])


def record_used_title(title):
    state = load_state()
    recent = state.get("recent_titles", [])
    recent.append(title)
    state["recent_titles"] = recent[-40:]
    save_state(state)


def get_next_topic():
    """
    Per-category round-robin. Each category tracks its own position
    independently; "order" is a shuffled permutation regenerated
    fresh each time a full pass completes, so you get variety in the
    sequence too while still guaranteeing every topic is used
    exactly once before any repeat.
    """
    state = load_state()
    state.setdefault("category_progress", {})

    categories = [t["category"] for t in TOPIC_POOL]
    categories = list(dict.fromkeys(categories))
    weights = [CATEGORY_WEIGHTS.get(c, 0.0) for c in categories]

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
of the clip, not as raw seconds. Shorter videos make the retention
bar physically easier to clear. Do not pad.

RETENTION TARGETS:
  - Swipe rate must be 20% or LOWER. Controlled entirely by the hook.
  - Average view duration must be 100% of clip length or more.

Rules for how it should sound:
- Write like you're explaining something wild to a friend, not
  narrating a documentary.
- Use contractions (it's, you'd, that's, don't).
- Vary sentence length: mix short punchy lines with one longer
  explanatory line.
- Do NOT use rhetorical filler like "this isn't science fiction,
  it's reality" or "prepare to have your mind blown."
- Do NOT stack intensifiers (incredibly, absolutely, insanely). Pick
  ONE strong word max per sentence, and only when it's earned.
- Include exactly one moment of genuine surprise or disbelief,
  phrased like a reaction, not a lecture.
- Deliver the core fact clearly before the final scene.
- When you cite a number, ALWAYS translate it into a comparison or
  ordinary reference in the same breath. "38 pico Kelvins" means
  nothing to a viewer; "38 trillionths of a degree above absolute
  zero" does. A number without a translation is a number the viewer
  will not remember.

HOOK — the first scene's narration. Must be fully spoken within 2.5
seconds (roughly 8 words or fewer), because that is the window in
which the viewer's finger decides whether to swipe.

Use ONE of these five patterns, whichever fits the topic best:
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
Prefer pattern 1 when a genuinely apt comparison exists.
Do NOT use generic hook filler like "did you know" or "here's a fact
that will blow your mind."
Do NOT start with a subordinate clause ("In the depths of...",
"Somewhere in the universe...") — those push the actual hook past
the swipe window.

ENDING — follow whichever style is set above:
- If ending_style is "loop": the FINAL scene must end mid-thought or
  lead seamlessly into the very first word of the hook, so the video
  loops endlessly with no visible seam. No joke, no summary, no
  moral. Example: hook is "...is why you can never touch a black
  hole." -> final scene is "And that terrifying reality..." (loops
  back to hook).
- If ending_style is "joke": the FINAL scene must be a short joke or
  pun directly related to the fact — one line, genuinely funny, not
  a generic "dad joke for the sake of it." If a clean pun exists in
  the topic, prefer that over a generic joke. The strongest joke
  endings connect the pun directly back to the specific number or
  comparison the video just established.

TITLE — under 60 characters. Use a curiosity-gap framing, not a
flat description:
  Weak:  "Facts About Deep Ocean Darkness"
  Strong: "The Ocean Depth Where Light Physically Can't Exist"

Also return a "title_emphasis" field: the substring of your title
that a thumbnail renderer should highlight in a different color.
Pick the one phrase that carries the whole hook of the title (2-4
words).

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


def _clean_transcript(raw):
    text = raw
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"^\s*>>\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s*$", "", text, flags=re.M)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _build_style_reference_block():
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


def _is_quota_error(e):
    msg = str(e)
    return any(
        marker in msg
        for marker in ("RESOURCE_EXHAUSTED", "429", "quota")
    )


def _is_model_unavailable_error(e):
    """New accounts can't use older models — Google returns 404
    NOT_FOUND instead of a quota error. Treat as 'skip to next model'
    rather than a hard fail."""
    msg = str(e)
    return "NOT_FOUND" in msg or "no longer available" in msg


def _is_transient_gemini_error(e):
    """Non-quota, non-unavailable errors (5xx, network) get fast
    retries; everything else bubbles up to the model chain."""
    if _is_quota_error(e) or _is_model_unavailable_error(e):
        return False
    return True


def _extract_retry_delay(e):
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(e))
    return float(m.group(1)) if m else None


def _is_daily_quota_error(e):
    return "PerDayPerProject" in str(e)


def _call_gemini_with_quota_fallback(call_fn):
    """
    Runs call_fn(). On a per-minute quota error, sleeps the delay
    Gemini hints + buffer, retries once. On a per-day quota error,
    raises immediately so the model chain can try the next model.
    """
    try:
        return call_fn()
    except Exception as e:
        if not _is_quota_error(e):
            raise

        if _is_daily_quota_error(e):
            raise

        delay = _extract_retry_delay(e)
        if delay is None:
            raise

        delay = min(delay, 90.0) + 5.0
        print(f"      (per-minute quota hit — sleeping {delay:.0f}s, "
              f"then retrying once)")
        time.sleep(delay)
        return call_fn()


def retry_with_backoff(fn, *args, retries=3, base_delay=3,
                       should_retry=None, **kwargs):
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


def generate_script(topic, ending_style, recent_titles=None):
    if recent_titles:
        titles_list = "\n".join(f"- {t}" for t in recent_titles)
        recent_titles_block = (
            "AVOID RESEMBLING RECENT VIDEOS — these titles were made "
            "recently on this channel. Even if today's topic is "
            "technically different, do not produce a hook, angle, or "
            "framing that would feel like a repeat of any of these to "
            "a viewer who's seen them:\n" + titles_list
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

    def _generate_with_model(model_name):
        model = genai.GenerativeModel(model_name)

        def _call():
            return model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"},
            )

        return _call_gemini_with_quota_fallback(
            lambda: retry_with_backoff(
                _call, retries=3, base_delay=5,
                should_retry=_is_transient_gemini_error,
            )
        )

    response = None
    last_error = None
    for model_name in GEMINI_MODEL_CHAIN:
        try:
            print(f"      (trying model: {model_name})")
            response = _generate_with_model(model_name)
            break
        except Exception as e:
            if not (_is_quota_error(e) or _is_model_unavailable_error(e)):
                raise
            last_error = e
            print(f"      ({model_name} unavailable — trying next)")
            continue

    if response is None:
        raise last_error or RuntimeError("all Gemini models exhausted")

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

async def _synthesize(text, voice, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def synthesize_scene_audio(scenes, run_dir):
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

def fetch_pexels_video(query, out_path):
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


def _fetch_pollinations_image_once(prompt, out_path):
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


def _generate_fallback_image(prompt, out_path):
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


def fetch_pollinations_image(prompt, out_path):
    try:
        return retry_with_backoff(
            _fetch_pollinations_image_once, prompt, out_path
        )
    except Exception as e:
        print(f"      (Pollinations failed — using fallback image: {e})")
        return _generate_fallback_image(prompt, out_path)


def fetch_visual_for_scene(scene, index, run_dir):
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

    bgm = bgm.with_effects([afx.MultiplyVolume(0.10)])

    combined = CompositeAudioClip([final_clip.audio, bgm])
    return final_clip.with_audio(combined)


def build_video(script, audio_clips, visuals, run_dir):
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