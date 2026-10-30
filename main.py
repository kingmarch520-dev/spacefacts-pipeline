"""
IMMERSIVE STORY CHANNEL — COMPLETE EPISODE PIPELINE

Python 3.11
1920x1080 landscape video
Edge TTS narration
MoviePy video editing
Pillow captions and temporary illustrations

Stories are written and approved manually.
The pipeline handles production and optional YouTube upload.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re

from pathlib import Path

import edge_tts

from PIL import Image, ImageDraw, ImageFont

from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    concatenate_audioclips,
)

from moviepy.audio.AudioClip import CompositeAudioClip


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

WIDTH = 1920
HEIGHT = 1080
FPS = 24

VOICE = os.getenv(
    "TTS_VOICE",
    "en-US-AndrewMultilingualNeural"
)

RATE = os.getenv("TTS_RATE", "+0%")
VOLUME = os.getenv("TTS_VOLUME", "+0%")

SCENE_DIR = ROOT / "assets" / "scenes"
MUSIC_DIR = ROOT / "assets" / "music"

OUTPUT_DIR = ROOT / "output"
TEMP_DIR = OUTPUT_DIR / "_temp"

STATE_PATH = ROOT / "episode_state.json"


# ============================================================
# STORY LOADING
# ============================================================

def read_json(path: Path) -> dict:

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )

    except json.JSONDecodeError as exc:

        raise ValueError(
            f"Invalid story JSON: {exc}"
        )


def validate_story(story: dict):

    if not story.get("title"):
        raise ValueError("Story needs a title.")

    scenes = story.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Story needs scenes.")

    for number, scene in enumerate(scenes, 1):

        if not scene.get("narration"):
            raise ValueError(
                f"Scene {number} has no narration."
            )

        if not scene.get("visual_prompt"):
            raise ValueError(
                f"Scene {number} has no visual prompt."
            )


# ============================================================
# FONT SYSTEM
# ============================================================

def load_font(size: int, bold=True):

    candidates = [

        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",

        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",

        "C:/Windows/Fonts/arialbd.ttf"

    ]

    for candidate in candidates:

        if Path(candidate).exists():

            return ImageFont.truetype(
                candidate,
                size
            )

    return ImageFont.load_default()


# ============================================================
# TEMPORARY SCENE ILLUSTRATIONS
# ============================================================

def draw_fallback_scene(scene, output_path, index):

    """
    Temporary illustration fallback.

    Replace these images with finished illustrations
    matching the supplied stick-figure references
    before publishing.
    """

    prompt = (
        scene.get("visual_prompt", "") +
        " " +
        scene.get("narration", "")
    ).lower()

    snowy = any(
        word in prompt
        for word in [
            "snow",
            "ice",
            "winter",
            "cold",
            "frozen",
            "mountain"
        ]
    )

    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (235, 188, 128)
    )

    draw = ImageDraw.Draw(image)

    sky = (
        (105, 126, 169)
        if snowy
        else (238, 179, 111)
    )

    ground = (
        (224, 229, 233)
        if snowy
        else (174, 117, 68)
    )

    draw.rectangle(
        (0, 0, WIDTH, 690),
        fill=sky
    )

    draw.rectangle(
        (0, 690, WIDTH, HEIGHT),
        fill=ground
    )

    if snowy:

        draw.polygon(
            [(0, 690), (320, 280), (720, 690)],
            fill=(235, 239, 242),
            outline=(30, 30, 35)
        )

        draw.polygon(
            [(480, 690), (1000, 210), (1530, 690)],
            fill=(246, 247, 245),
            outline=(30, 30, 35)
        )

        draw.polygon(
            [(1280, 690), (1640, 360), (1920, 690)],
            fill=(215, 224, 232),
            outline=(30, 30, 35)
        )

        for x in (150, 1730):

            draw.rectangle(
                (x-12, 490, x+12, 760),
                fill=(65, 70, 61)
            )

            for y in (400, 500, 600):

                draw.polygon(
                    [
                        (x, y-100),
                        (x-95, y+65),
                        (x+95, y+65)
                    ],
                    fill=(42, 78, 67),
                    outline=(25, 45, 40)
                )

    else:

        draw.rectangle(
            (140, 420, 520, 700),
            fill=(151, 82, 52),
            outline=(35, 30, 35),
            width=8
        )

        draw.polygon(
            [(105, 420), (330, 225), (555, 420)],
            fill=(88, 54, 45),
            outline=(35, 30, 35)
        )

    # Main stick figure

    x = 970
    y = 445

    draw.ellipse(
        (x-102, y-102, x+102, y+102),
        fill="white",
        outline=(20, 20, 24),
        width=10
    )

    draw.ellipse(
        (x-47, y-8, x-25, y+18),
        fill=(20, 20, 24)
    )

    draw.ellipse(
        (x+25, y-8, x+47, y+18),
        fill=(20, 20, 24)
    )

    draw.arc(
        (x-40, y+20, x+40, y+78),
        195,
        345,
        fill=(20, 20, 24),
        width=7
    )

    draw.polygon(
        [
            (x-65, y+92),
            (x+65, y+92),
            (x+112, y+350),
            (x-112, y+350)
        ],
        fill=(48, 54, 76),
        outline=(20, 20, 24)
    )

    draw.line(
        (x-75, y+130, x-240, y+260),
        fill=(20, 20, 24),
        width=18
    )

    draw.line(
        (x+75, y+130, x+240, y+260),
        fill=(20, 20, 24),
        width=18
    )

    draw.line(
        (x-48, y+340, x-100, y+510),
        fill=(20, 20, 24),
        width=18
    )

    draw.line(
        (x+48, y+340, x+100, y+510),
        fill=(20, 20, 24),
        width=18
    )

    draw.rounded_rectangle(
        (35, 35, 1030, 122),
        radius=18,
        fill=(20, 24, 34)
    )

    draw.text(
        (60, 57),
        f"TEMPORARY SCENE ART {index:02d}",
        font=load_font(27),
        fill="white"
    )

    image.save(
        output_path,
        quality=95
    )


# ============================================================
# CAPTIONS
# ============================================================

def wrap_lines(draw, text, font, max_width):

    words = text.split()

    lines = []
    current = ""

    for word in words:

        test = (current + " " + word).strip()

        width = draw.textbbox(
            (0, 0),
            test,
            font=font
        )[2]

        if width <= max_width:

            current = test

        else:

            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    return lines


def caption_image(text, output_path):

    image = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    font = load_font(43)

    lines = wrap_lines(
        draw,
        text.upper(),
        font,
        WIDTH - 250
    )

    line_height = 59

    box_height = (
        len(lines) * line_height + 38
    )

    y = HEIGHT - box_height - 55

    draw.rounded_rectangle(
        (70, y-12, WIDTH-70, HEIGHT-35),
        radius=22,
        fill=(0, 0, 0, 195)
    )

    for line in lines:

        bounds = draw.textbbox(
            (0, 0),
            line,
            font=font
        )

        x = (
            WIDTH -
            (bounds[2] - bounds[0])
        ) // 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=2,
            stroke_fill="black"
        )

        y += line_height

    image.save(output_path)


def caption_chunks(text, words_per_chunk=8):

    words = re.findall(r"\S+", text)

    return [
        " ".join(
            words[i:i+words_per_chunk]
        )
        for i in range(
            0,
            len(words),
            words_per_chunk
        )
    ]


# ============================================================
# TEXT TO SPEECH
# ============================================================

async def synthesize(text, destination):

    communicator = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate=RATE,
        volume=VOLUME
    )

    await communicator.save(
        str(destination)
    )


# ============================================================
# SCENE PRODUCTION
# ============================================================

def make_scene_clip(scene, index):

    audio_path = TEMP_DIR / (
        f"narration_{index:03d}.mp3"
    )

    asyncio.run(
        synthesize(
            scene["narration"],
            audio_path
        )
    )

    audio = AudioFileClip(
        str(audio_path)
    )

    image_path = SCENE_DIR / (
        f"scene_{index:02d}.png"
    )

    if not image_path.exists():

        draw_fallback_scene(
            scene,
            image_path,
            index
        )

    still = ImageClip(
        str(image_path)
    ).resize(height=HEIGHT)

    if still.w < WIDTH:

        still = still.resize(
            width=WIDTH
        )

    still = still.crop(
        x_center=still.w / 2,
        y_center=still.h / 2,
        width=WIDTH,
        height=HEIGHT
    ).set_duration(audio.duration)

    still = still.resize(
        lambda t: 1.0 + (
            0.018 * (
                t / max(audio.duration, 0.1)
            )
        )
    ).set_position("center")

    overlays = [still]

    chunks = caption_chunks(
        scene["narration"]
    )

    total_words = max(
        1,
        len(scene["narration"].split())
    )

    elapsed = 0.0

    for number, chunk in enumerate(chunks):

        duration = (
            audio.duration *
            len(chunk.split()) /
            total_words
        )

        caption_path = TEMP_DIR / (
            f"caption_{index:03d}_{number:03d}.png"
        )

        caption_image(
            chunk,
            caption_path
        )

        overlays.append(
            ImageClip(
                str(caption_path)
            )
            .set_start(elapsed)
            .set_duration(duration)
        )

        elapsed += duration

    clip = CompositeVideoClip(
        overlays,
        size=(WIDTH, HEIGHT)
    ).set_duration(audio.duration)

    clip = clip.set_audio(audio)

    return clip


# ============================================================
# BACKGROUND MUSIC
# ============================================================

def add_music(video):

    music_files = sorted(
        MUSIC_DIR.glob("*.mp3")
    )

    if not music_files:
        return video

    music = AudioFileClip(
        str(music_files[0])
    ).volumex(
        float(os.getenv("MUSIC_VOLUME", "0.10"))
    )

    if music.duration < video.duration:

        repeats = (
            int(video.duration / music.duration) + 1
        )

        music = concatenate_audioclips(
            [music] * repeats
        ).subclip(
            0,
            video.duration
        )

    else:

        music = music.subclip(
            0,
            video.duration
        )

    return video.set_audio(
        CompositeAudioClip(
            [video.audio, music]
        )
    )


# ============================================================
# EPISODE RENDERING
# ============================================================

def render_episode(story_file):

    story = read_json(story_file)

    validate_story(story)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    TEMP_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    SCENE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    clips = []
    durations = []

    for index, scene in enumerate(
        story["scenes"],
        1
    ):

        clip = make_scene_clip(
            scene,
            index
        )

        clips.append(clip)

        durations.append(
            round(clip.duration, 2)
        )

        print(
            f"Rendered scene {index}/"
            f"{len(story['scenes'])}: "
            f"{clip.duration:.1f}s"
        )

    final = concatenate_videoclips(
        clips,
        method="compose"
    )

    final = add_music(final)

    slug = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        story["title"]
    ).strip("_")[:90]

    output_path = OUTPUT_DIR / (
        f"{slug}.mp4"
    )

    final.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=2,
        bitrate="5000k"
    )

    total_seconds = round(
        sum(durations),
        2
    )

    state = {

        "episode": story.get("episode", 1),

        "title": story["title"],

        "rendered_file": str(
            output_path.relative_to(ROOT)
        ),

        "duration_seconds": total_seconds,

        "duration_minutes": round(
            total_seconds / 60,
            2
        ),

        "scenes": [

            {
                "number": i + 1,

                "duration_seconds": durations[i],

                "art_file": (
                    f"assets/scenes/scene_{i+1:02d}.png"
                )
            }

            for i in range(len(durations))
        ],

        "inventory_at_end": story.get(
            "inventory_at_end",
            {}
        ),

        "characters_at_end": story.get(
            "characters_at_end",
            {}
        ),

        "status": "rendered_not_uploaded"
    }

    STATE_PATH.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8"
    )

    final.close()

    for clip in clips:
        clip.close()

    print(
        f"Finished: {output_path} "
        f"({total_seconds / 60:.1f} minutes)"
    )

    return output_path, story


# ============================================================
# YOUTUBE UPLOAD
# ============================================================

def upload_episode(video_path, story):

    from youtube_upload import upload_video

    result = upload_video(

        file_path=str(video_path),

        title=story["title"],

        description=story.get(
            "description",
            story["title"]
        ),

        tags=story.get(
            "tags",
            ["immersive storytelling", "story"]
        ),

        privacy_status=os.getenv(
            "YOUTUBE_PRIVACY",
            "private"
        )
    )

    state = read_json(STATE_PATH)

    state["status"] = "uploaded"

    state["youtube_result"] = result

    STATE_PATH.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8"
    )

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--story",
        default=os.getenv(
            "STORY_FILE",
            "stories/episode_001.json"
        )
    )

    parser.add_argument(
        "--upload",
        action="store_true"
    )

    args = parser.parse_args()

    video_path, story = render_episode(
        ROOT / args.story
    )

    if args.upload:

        print(
            upload_episode(
                video_path,
                story
            )
        )

    else:

        print(
            "Upload skipped. Review the video first."
        )


if __name__ == "__main__":

    main()