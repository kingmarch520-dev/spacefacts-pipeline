"""
==================================================================
SPACE/PHYSICS FACTS CHANNEL — AUTOMATED SHORTS PIPELINE
==================================================================
Built for Google Colab. Run cells top to bottom, or paste into
one cell and execute.
"""

import os
import json
import random
import asyncio
import requests
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import google.generativeai as genai
# Note: Ensure youtube_upload.py and supabase_client.py are in the same directory
import youtube_upload
import supabase_client

# moviepy 2.x imports
from moviepy import * 

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
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

# Weights scaled to total 1.0 (based on your actual 53% Space / 47% Ocean performance split)
FALLBACK_CATEGORY_WEIGHTS = {
    "space": 0.53,
    "ocean": 0.47,
}

PUBLIC_PUBLISH_CHANCE = 0.5

MANUAL_PERFORMANCE_LOG = [
    # {"title": "...", "category": "space", "views": 1700},
]

TOPIC_POOL = [
    # --- SPACE ---
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
    
    # --- OCEAN ---
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
    {"topic": "why some deep sea fish can survive being frozen solid", "category": "ocean"},
    {"topic": "how a single drop of seawater can contain millions of microorganisms", "category": "ocean"},
    {"topic": "why the ocean's color actually changes with depth the way it does", "category": "ocean"},
    {"topic": "how sound travels four times faster underwater than in air", "category": "ocean"},
    {"topic": "what the 'twilight zone' of the ocean actually looks like", "category": "ocean"},
    {"topic": "how a shipwreck actually becomes an artificial reef over time", "category": "ocean"},
    {"topic": "why some ocean currents are strong enough to move entire islands of debris", "category": "ocean"},
    {"topic": "how deep-diving whales survive water pressure that would crush a submarine", "category": "ocean"},
]

# ------------------------------------------------------------------
# CORE LOGIC
# ------------------------------------------------------------------

genai.configure(api_key=GEMINI_API_KEY)

def retry_with_backoff(func, retries=3, backoff_in_seconds=2):
    """Retries a function with exponential backoff."""
    def wrapper(*args, **kwargs):
        x = 0
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if x == retries:
                    print(f"Failed after {retries} retries. Error: {e}")
                    raise
                sleep_time = (backoff_in_seconds * 2 ** x) + random.uniform(0, 1)
                print(f"Attempt failed: {e}. Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
                x += 1
    return wrapper

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "indexes": {"space": 0, "ocean": 0},
        "recent_titles": [],
        "shuffled_indices": {
            "space": list(range(20)),
            "ocean": list(range(20, 40)),
        }
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def get_next_topic(state):
    """Picks a topic weighted by category performance, without repeating until the category is exhausted."""
    # Attempt to fetch live performance from Supabase
    try:
        live_data = supabase_client.get_category_performance()
        if not live_data:
            weights = FALLBACK_CATEGORY_WEIGHTS
        else:
            # Ensure we only use 'space' and 'ocean' from live data, just in case
            valid_keys = [k for k in live_data.keys() if k in FALLBACK_CATEGORY_WEIGHTS.keys()]
            total_views = sum([live_data[k] for k in valid_keys])
            if total_views > 0:
                weights = {k: live_data[k] / total_views for k in valid_keys}
            else:
                weights = FALLBACK_CATEGORY_WEIGHTS
    except Exception:
        weights = FALLBACK_CATEGORY_WEIGHTS

    categories = list(weights.keys())
    probs = [weights[c] for c in categories]
    chosen_category = random.choices(categories, weights=probs, k=1)[0]

    # Get index for the chosen category
    current_idx = state["indexes"][chosen_category]
    category_indices = state["shuffled_indices"][chosen_category]

    if current_idx >= len(category_indices):
        # Reshuffle when exhausted
        random.shuffle(category_indices)
        state["shuffled_indices"][chosen_category] = category_indices
        current_idx = 0

    actual_topic_idx = category_indices[current_idx]
    state["indexes"][chosen_category] = current_idx + 1

    return TOPIC_POOL[actual_topic_idx]

@retry_with_backoff
def generate_script(topic_dict, recent_titles, ending_style):
    topic = topic_dict["topic"]
    
    prompt = f"""
    Write a 60-second YouTube Short script about: "{topic}".
    
    IMPORTANT RULES:
    1. Title MUST be dry, plain, and curiosity-driven (e.g., "Why Space is Completely Silent" rather than "Why Space Is Terrifyingly Silent"). 
    2. Hook MUST use one of these 5 patterns:
       - Compare the extreme to something ordinary
       - Ask a deceptively simple question
       - State an impossible-sounding fact
       - Correct a massive, widely believed misconception
       - Start in the middle of a high-stakes scenario
    3. Ending MUST be a '{ending_style}' style ending. 
       - If 'loop', write the last sentence so it grammatically flows directly back into the opening hook.
       - If 'joke', end with a punchy, relevant observation or joke.
    4. Provide the result as raw JSON with keys: "title", "hook", "body_script", "ending", "image_prompt".
    
    DO NOT generate any title close to these recently used ones: {recent_titles}
    """
    
    model = genai.GenerativeModel("gemini-1.5-flash") # gemini-3.6-flash equivalent or latest available GA
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    return json.loads(response.text)

async def generate_audio(text, voice, output_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

@retry_with_backoff
def fetch_pollinations_image(prompt, output_path):
    # Sanitize prompt for URL
    safe_prompt = prompt.replace(" ", "%20")
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width={VIDEO_W}&height={VIDEO_H}&nologo=true"
    
    response = requests.get(url, timeout=15)
    
    if response.status_code == 200 and 'image' in response.headers.get('content-type', ''):
        with open(output_path, 'wb') as f:
            f.write(response.content)
    else:
        raise Exception(f"Failed to fetch image. Status: {response.status_code}, Content-Type: {response.headers.get('content-type')}")

def create_fallback_image(output_path, text="Image Generation Failed"):
    """Locally generated placeholder image in case Pollinations fails after all retries."""
    img = Image.new('RGB', (VIDEO_W, VIDEO_H), color=(20, 20, 30))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(CAPTION_FONT_PATH, 50)
    except:
        font = ImageFont.load_default()
    d.text((100, VIDEO_H//2), text, fill=(255,255,255), font=font)
    img.save(output_path)

def add_background_music(tts_audio_path, output_audio_path):
    if not BGM_DIR.exists():
        return tts_audio_path # No music folder, just skip
        
    bgm_files = list(BGM_DIR.glob("*.mp3"))
    if not bgm_files:
        return tts_audio_path
        
    bgm_file = random.choice(bgm_files)
    
    tts_clip = AudioFileClip(str(tts_audio_path))
    bgm_clip = AudioFileClip(str(bgm_file)).with_volume_multiplier(0.08).loop(duration=tts_clip.duration)
    
    final_audio = CompositeAudioClip([tts_clip, bgm_clip])
    final_audio.write_audiofile(str(output_audio_path), fps=44100, logger=None)
    
    return output_audio_path

def log_manual_performance():
    """Pushes manual YouTube Studio views to Supabase to adjust topic weights"""
    if MANUAL_PERFORMANCE_LOG:
        supabase_client.batch_insert_performance(MANUAL_PERFORMANCE_LOG)

# ------------------------------------------------------------------
# MAIN PIPELINE
# ------------------------------------------------------------------

def main():
    print("🚀 Starting Shorts Pipeline...")
    
    # 1. Setup & State Management
    state = load_state()
    topic_data = get_next_topic(state)
    ending_style = random.choice(["loop", "joke"])
    
    print(f"📌 Selected Topic: {topic_data['topic']} | Category: {topic_data['category']} | Ending: {ending_style}")
    
    # 2. Generate Script via Gemini
    script_data = generate_script(topic_data, state["recent_titles"], ending_style)
    print(f"📜 Generated Title: {script_data['title']}")
    
    full_text = f"{script_data['hook']} {script_data['body_script']} {script_data['ending']}"
    
    # Update State for duplicate prevention
    state["recent_titles"].append(script_data['title'])
    if len(state["recent_titles"]) > 40:
        state["recent_titles"].pop(0)
    save_state(state)
    
    # 3. Audio Generation (Edge TTS)
    voice = random.choice(TTS_VOICES)
    raw_audio_path = OUTPUT_DIR / "tts_raw.mp3"
    final_audio_path = OUTPUT_DIR / "audio_mixed.mp3"
    
    asyncio.run(generate_audio(full_text, voice, str(raw_audio_path)))
    add_background_music(raw_audio_path, final_audio_path)
    
    # 4. Image Generation
    img_path = OUTPUT_DIR / "bg_image.jpg"
    try:
        fetch_pollinations_image(script_data["image_prompt"], str(img_path))
    except Exception as e:
        print(f"⚠️ Image generation completely failed: {e}. Using fallback.")
        create_fallback_image(str(img_path))
        
    # 5. Video Assembly (MoviePy)
    print("🎬 Assembling Video...")
    audio_clip = AudioFileClip(str(final_audio_path))
    image_clip = ImageClip(str(img_path)).with_duration(audio_clip.duration)
    
    # Simple caption clip in center
    txt_clip = TextClip(
        font=CAPTION_FONT_PATH,
        text=script_data['title'],
        font_size=70,
        color='white',
        stroke_color='black',
        stroke_width=3,
        method='caption',
        size=(VIDEO_W - 100, None)
    ).with_position('center').with_duration(audio_clip.duration)
    
    video = CompositeVideoClip([image_clip, txt_clip])
    video = video.with_audio(audio_clip)
    
    output_video_path = OUTPUT_DIR / f"final_short_{int(time.time())}.mp4"
    video.write_videofile(
        str(output_video_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        logger=None
    )
    
    # 6. Upload
    is_public = random.random() < PUBLIC_PUBLISH_CHANCE
    privacy_status = "public" if is_public else "unlisted"
    print(f"⬆️ Uploading to YouTube as {privacy_status}...")
    
    try:
        video_id = youtube_upload.upload_video(
            file_path=str(output_video_path),
            title=script_data["title"],
            description=f"Topic: {topic_data['topic']}\n#shorts #facts #{topic_data['category']}",
            privacy=privacy_status
        )
        print(f"✅ Uploaded successfully! Video ID: {video_id}")
        
        # 7. Log to Supabase for A/B Testing
        supabase_client.log_video(
            video_id=video_id,
            title=script_data["title"],
            category=topic_data["category"],
            ending_style=ending_style,
            is_public=is_public
        )
        print("📊 Logged to Supabase.")
        
    except Exception as e:
        print(f"❌ Upload or logging failed: {e}")

if __name__ == "__main__":
    main()
