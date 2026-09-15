import os
import sys
import json
import random
import asyncio
from groq import Groq
import edge_tts
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- MOVIEPY V1/V2 COMPATIBILITY IMPORT ---
try:
    from moviepy.editor import (
        VideoFileClip,
        AudioFileClip,
        TextClip,
        CompositeVideoClip,
        ColorClip
    )
except ImportError:
    from moviepy import (
        VideoFileClip,
        AudioFileClip,
        TextClip,
        CompositeVideoClip,
        ColorClip
    )

# ----------------------------------------------------------------------
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ----------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN")

STATE_FILE = "state_spacefacts.json"
BG_VIDEO_PATH = "background.mp4"
OUTPUT_VIDEO = "final_short.mp4"
TEMP_AUDIO = "voiceover.mp3"

groq_client = Groq(api_key=GROQ_API_KEY)

# ----------------------------------------------------------------------
# 2. TOPIC POOL (200 Topics)
# ----------------------------------------------------------------------
TOPIC_POOL = [
    # --- SPACE / PHYSICS (50 topics) ---
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
    {"topic": "why quantum entanglement stumped even Albert Einstein", "category": "space"},
    {"topic": "what the Boötes Void actually is and why it's so empty", "category": "space"},
    {"topic": "how magnetars possess the strongest magnetic fields in the cosmos", "category": "space"},
    {"topic": "the terrifying theoretical concept of false vacuum decay", "category": "space"},
    {"topic": "why dark energy is pushing the universe apart faster every second", "category": "space"},
    {"topic": "why Oumuamua accelerated mysteriously out of our solar system", "category": "space"},
    {"topic": "how Saturn's moon Titan has liquid methane rivers and seas", "category": "space"},
    {"topic": "the massive water ice plumes blasting out of Enceladus", "category": "space"},
    {"topic": "why the Cosmic Microwave Background has a mysterious Cold Spot", "category": "space"},
    {"topic": "how supermassive black holes power ultra-bright quasars", "category": "space"},
    {"topic": "what happens during a tidal disruption event when a star gets torn apart", "category": "space"},
    {"topic": "how hypervelocity stars get launched completely out of galaxies", "category": "space"},
    {"topic": "what a Kugelblitz black hole formed entirely from light would be", "category": "space"},
    {"topic": "how fast pulsars spin and why they act like cosmic clocks", "category": "space"},
    {"topic": "why scientists believe it rains liquid diamonds on Neptune and Uranus", "category": "space"},
    {"topic": "what the Great Attractor pulling our galaxy actually is", "category": "space"},
    {"topic": "the Kardashev scale and how civilizations harness stellar energy", "category": "space"},
    {"topic": "the theoretical end scenarios of our universe from Big Rip to Heat Death", "category": "space"},
    {"topic": "how a gamma-ray burst could strip Earth's ozone layer in seconds", "category": "space"},
    {"topic": "how gravitational assists use planetary gravity to fling spacecraft", "category": "space"},
    {"topic": "what would happen to Earth during a solar flare the size of the Carrington Event", "category": "space"},
    {"topic": "why Olympus Mons on Mars is three times taller than Mount Everest", "category": "space"},
    {"topic": "how deep Europa's hidden ocean might actually be", "category": "space"},
    {"topic": "what the Drake Equation calculates about alien life", "category": "space"},
    {"topic": "how wave-particle duality works in the famous double-slit experiment", "category": "space"},
    {"topic": "why the speed of light is the absolute speed limit of the universe", "category": "space"},
    {"topic": "what theoretical tachyons moving faster than light would cause", "category": "space"},
    {"topic": "how the Wow! Signal was detected and why it remains unexplained", "category": "space"},
    {"topic": "how gravitational waves ripple spacetime when black holes collide", "category": "space"},
    {"topic": "what the Roche limit is and how it destroys moons that get too close", "category": "space"},

    # --- OCEAN / SEA (50 topics) ---
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
    {"topic": "what caused the mystery behind the underwater 'Bloop' sound", "category": "ocean"},
    {"topic": "how siphonophores grow to be the longest organisms in the sea", "category": "ocean"},
    {"topic": "what abyssal gigantism does to creatures living in the deep ocean", "category": "ocean"},
    {"topic": "how underwater brinicles act as icicles of death on the ocean floor", "category": "ocean"},
    {"topic": "why Point Nemo is the most isolated spot in the entire ocean", "category": "ocean"},
    {"topic": "how a whale fall ecosystem can feed deep sea life for decades", "category": "ocean"},
    {"topic": "how the fangtooth fish copes with extreme ocean pressure", "category": "ocean"},
    {"topic": "how vampire squids survive in zones with almost zero oxygen", "category": "ocean"},
    {"topic": "why the dragonfish has ultra-black skin that absorbs 99.5 percent of light", "category": "ocean"},
    {"topic": "how the mantis shrimp punches with the force of a bullet underwater", "category": "ocean"},
    {"topic": "how the goblin shark's unhinging jaw catches deep-sea prey", "category": "ocean"},
    {"topic": "why the Sargasso Sea is the only sea with no land boundaries", "category": "ocean"},
    {"topic": "how rogue waves over 80 feet high appear out of nowhere in open ocean", "category": "ocean"},
    {"topic": "how the Denmark Strait cataract forms the world's largest underwater waterfall", "category": "ocean"},
    {"topic": "how the coelacanth was discovered alive after being thought extinct for 66 million years", "category": "ocean"},
    {"topic": "how the immortal jellyfish can theoretically revert its cells back to youth", "category": "ocean"},
    {"topic": "why the barreleye fish has a completely transparent head", "category": "ocean"},
    {"topic": "how the scale-foot snail grows an armored shell out of real iron", "category": "ocean"},
    {"topic": "how deep the deepest recorded fish live in the ocean", "category": "ocean"},
    {"topic": "what flammable methane ice deposits on the ocean floor actually are", "category": "ocean"},
    {"topic": "why blue holes contain toxic oxygen-free water layers", "category": "ocean"},
    {"topic": "why octopuses have blue copper-based blood instead of iron-based blood", "category": "ocean"},
    {"topic": "why the blobfish only looks strange when removed from deep sea pressure", "category": "ocean"},
    {"topic": "how ocean currents form massive gyres that trap floating plastics", "category": "ocean"},
    {"topic": "how dumbo octopuses navigate at depths over 13,000 feet", "category": "ocean"},
    {"topic": "why the frilled shark is considered a living prehistoric fossil", "category": "ocean"},
    {"topic": "how ocean brine pools form underwater lakes with their own shorelines", "category": "ocean"},
    {"topic": "how the Greenland shark can live for up to 400 years in arctic waters", "category": "ocean"},
    {"topic": "how cookiecutter sharks gouge precise circular wounds on massive sea life", "category": "ocean"},
    {"topic": "how sperm whales use high-decibel clicks to stun prey underwater", "category": "ocean"},

    # --- HISTORY / ANCIENT MYSTERIES (50 topics) ---
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
    {"topic": "how Derinkuyu underground city housed 20,000 people beneath Earth's surface", "category": "history"},
    {"topic": "why Göbekli Tepe challenges historical timelines of early agriculture", "category": "history"},
    {"topic": "how Easter Island's Moai statues actually have massive buried bodies beneath the soil", "category": "history"},
    {"topic": "how the sunken ancient Egyptian city of Heracleion was discovered underwater", "category": "history"},
    {"topic": "how the Nebra sky disc accurately represented the night sky 3,600 years ago", "category": "history"},
    {"topic": "what caused the mysterious 1855 footprints known as the Devil's Footprints", "category": "history"},
    {"topic": "how Sacsayhuamán's massive megalithic stones fit together without mortar", "category": "history"},
    {"topic": "what evidence exists surrounding the Dyatlov Pass incident", "category": "history"},
    {"topic": "why the tomb of China's first emperor is rumored to have rivers of liquid mercury", "category": "history"},
    {"topic": "how 6 million human skeletons ended up inside the Catacombs of Paris", "category": "history"},
    {"topic": "the chilling distress signal sent by the ghost ship SS Ourang Medan", "category": "history"},
    {"topic": "how Pytheas of Massalia navigated to the Arctic circle in 320 BC", "category": "history"},
    {"topic": "how L'Anse aux Meadows proved Vikings reached North America long before Columbus", "category": "history"},
    {"topic": "the weird architecture and maze-like layout of the Winchester Mystery House", "category": "history"},
    {"topic": "the mysterious 12th-century legend of the Green Children of Woolpit", "category": "history"},
    {"topic": "why the Tarim mummies found in China had European facial features", "category": "history"},
    {"topic": "the dark history and speed at which the Codex Gigas was written", "category": "history"},
    {"topic": "how the Royal Game of Ur was rediscovered as the world's oldest playable board game", "category": "history"},
    {"topic": "why the Sanxingdui bronze heads with alien-like eyes shocked archaeologists", "category": "history"},
    {"topic": "why the Mary Celeste was found floating completely deserted with intact cargo", "category": "history"},
    {"topic": "how the Oak Island Money Pit booby-traps foiled treasure hunters for centuries", "category": "history"},
    {"topic": "how the priceless Amber Room vanished during World War II", "category": "history"},
    {"topic": "how three Roman legions were wiped out in the Battle of Teutoburg Forest", "category": "history"},
    {"topic": "what causes the persistent low-frequency hum reported in Taos, New Mexico", "category": "history"},
    {"topic": "how the hand-carved Longyou caves in China were constructed without historical records", "category": "history"},
    {"topic": "what the massive stone Plain of Jars in Laos was used for", "category": "history"},
    {"topic": "whether the submerged rock formation known as Bimini Road is natural or manmade", "category": "history"},
    {"topic": "how Denisovan bone fragments revealed a lost branch of ancient humans", "category": "history"},
    {"topic": "how the sailing stones of Racetrack Playa move across dry lakebeds on their own", "category": "history"},
    {"topic": "why the identity of the Man in the Iron Mask remained a state secret", "category": "history"},

    # --- BIBLE MYSTERIES & THEORIES (50 topics) ---
    {"topic": "who the 'sons of God' in Genesis 6 are actually theorized to be", "category": "bible"},
    {"topic": "why the Book of Enoch was left out of the Bible despite being quoted in it", "category": "bible"},
    {"topic": "theories about what happened during Jesus's unrecorded years before age 30", "category": "bible"},
    {"topic": "whether the Behemoth and Leviathan in Job describe real extinct creatures", "category": "bible"},
    {"topic": "the ongoing debate over which mountain is the real Mount Sinai", "category": "bible"},
    {"topic": "what actually happened to the ten lost tribes of Israel", "category": "bible"},
    {"topic": "theories about who Melchizedek really was and why he has no origin story", "category": "bible"},
    {"topic": "the mystery of where Cain's wife came from in Genesis", "category": "bible"},
    {"topic": "how the Urim and Thummim were actually used to make decisions", "category": "bible"},
    {"topic": "why the 400 years between the Old and New Testament are called 'silent'", "category": "bible"},
    {"topic": "where the biblical land of Ophir, source of Solomon's gold, might actually be", "category": "bible"},
    {"topic": "why Matthew and Acts describe Judas's death two completely different ways", "category": "bible"},
    {"topic": "theories about who Job's mysterious 'satan' figure actually represents", "category": "bible"},
    {"topic": "why the Gospel of Thomas was excluded from the New Testament canon", "category": "bible"},
    {"topic": "theories about the historical identity of the 'beloved disciple' in John", "category": "bible"},
    {"topic": "what scholars debate about the authorship of the Book of Hebrews", "category": "bible"},
    {"topic": "theories about what Paul's 'thorn in the flesh' actually was", "category": "bible"},
    {"topic": "why the location of the real Mount Ararat is still disputed", "category": "bible"},
    {"topic": "theories about the identity and fate of Lot's wife beyond the pillar of salt", "category": "bible"},
    {"topic": "why there's a 'missing' set of genealogy years scholars still argue about", "category": "bible"},
    {"topic": "theories on where the Garden of Eden was located based on its four rivers", "category": "bible"},
    {"topic": "how the Tower of Babel narrative connects to ancient Mesopotamian ziggurats", "category": "bible"},
    {"topic": "claims regarding the current location of the Ark of the Covenant in Ethiopia", "category": "bible"},
    {"topic": "the debate over Archangel Michael and the dispute over the body of Moses", "category": "bible"},
    {"topic": "geological theories surrounding the location of the Red Sea crossing", "category": "bible"},
    {"topic": "theories on what the natural or miraculous origin of manna might have been", "category": "bible"},
    {"topic": "scholarly interpretations of Balaam's talking donkey narrative", "category": "bible"},
    {"topic": "the scientific and radiocarbon controversies surrounding the Shroud of Turin", "category": "bible"},
    {"topic": "the debate over whether the Witch of Endor summoned a real spirit or executed a fraud", "category": "bible"},
    {"topic": "how flood narratives appear in ancient non-biblical texts like Gilgamesh", "category": "bible"},
    {"topic": "different interpretations of Ezekiel's vision of wheels within wheels", "category": "bible"},
    {"topic": "theories explaining the astronomical phenomenon of Joshua's long day", "category": "bible"},
    {"topic": "why some early papyri list the Number of the Beast as 616 instead of 666", "category": "bible"},
    {"topic": "whether Ezekiel's Valley of Dry Bones was intended as metaphor or literal prophecy", "category": "bible"},
    {"topic": "archaeological evidence suggesting a meteor airburst at Sodom and Gomorrah", "category": "bible"},
    {"topic": "astronomical theories explaining what the Star of Bethlehem actually was", "category": "bible"},
    {"topic": "historical theories attempting to identify the real identity of King Nimrod", "category": "bible"},
    {"topic": "how the Dead Sea Scrolls changed our understanding of biblical translation accuracy", "category": "bible"},
    {"topic": "the Melchizedek scroll found at Qumran and its divine descriptions", "category": "bible"},
    {"topic": "the massive iron bed dimensions recorded for Og, King of Bashan", "category": "bible"},
    {"topic": "theories regarding who the Two Witnesses in Revelation are symbolic or literal of", "category": "bible"},
    {"topic": "astronomical records comparing the crucifixion darkness to recorded solar eclipses", "category": "bible"},
    {"topic": "the ongoing debate over whether Ramses II or Amenhotep II was the Pharaoh of the Exodus", "category": "bible"},
    {"topic": "archaeological digs uncovering the Etemenanki ziggurat linked to Babel", "category": "bible"},
    {"topic": "why the biblical account omits details about Lazarus's four days in the afterlife", "category": "bible"},
    {"topic": "historicist vs futurist interpretations of the Four Horsemen", "category": "bible"},
    {"topic": "geopolitical and historical theories surrounding the identities of Gog and Magog", "category": "bible"},
    {"topic": "symbolic distinctions between the Tree of Life and the Tree of Knowledge", "category": "bible"},
    {"topic": "the legal procedural violations argued during the night trial of Jesus under Talmudic law", "category": "bible"},
    {"topic": "how the copper scroll of Qumran lists hidden temple treasures across ancient Judea", "category": "bible"},
]

# ----------------------------------------------------------------------
# 3. YOUTUBE API AUTHENTICATION & DEDUPLICATION
# ----------------------------------------------------------------------
def get_youtube_client():
    """Builds YouTube API client using GitHub Actions Secrets or token.json."""
    if YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN:
        credentials = Credentials(
            None,
            refresh_token=YT_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YT_CLIENT_ID,
            client_secret=YT_CLIENT_SECRET
        )
    elif os.path.exists("token.json"):
        scopes = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly"
        ]
        credentials = Credentials.from_authorized_user_file("token.json", scopes)
    else:
        raise ValueError("Missing YouTube credentials in environment variables or token.json.")

    return build("youtube", "v3", credentials=credentials)

def get_used_topics():
    """Loads uploaded topics from state_spacefacts.json."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return set(data.get("used_topics", []))
        except Exception:
            return set()
    return set()

def save_used_topic(topic_text):
    """Saves used topic to state_spacefacts.json."""
    used = get_used_topics()
    used.add(topic_text.lower())
    with open(STATE_FILE, "w") as f:
        json.dump({"used_topics": list(used)}, f, indent=2)

# ----------------------------------------------------------------------
# 4. SCRIPT GENERATION (Groq / Llama 3.1 70B)
# ----------------------------------------------------------------------
def generate_script(topic: str) -> str:
    """Uses Groq (Llama 3.1 70B) to generate short script."""
    prompt = f"""
    Write a fast-paced, highly engaging script for a 30-second YouTube Short about: "{topic}".
    Requirements:
    - Start immediately with a strong hook sentence.
    - Keep total script length under 110 words.
    - No emojis, stage directions, or narration cues (like [Music Plays]).
    - Output raw speakable text only.
    """
    response = groq_client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_completion_tokens=300
    )
    return response.choices[0].message.content.strip()

# ----------------------------------------------------------------------
# 5. VOICE GENERATION (Edge-TTS)
# ----------------------------------------------------------------------
async def generate_voiceover(text: str, output_path: str):
    """Synthesizes voice audio."""
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

# ----------------------------------------------------------------------
# 6. VIDEO RENDERING ENGINE (MoviePy)
# ----------------------------------------------------------------------
def render_video_short(audio_path: str, script_text: str, output_path: str):
    """Renders 9:16 short video."""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    if os.path.exists(BG_VIDEO_PATH):
        bg_clip = VideoFileClip(BG_VIDEO_PATH)
        if bg_clip.duration < duration:
            bg_clip = bg_clip.loop(duration=duration)
        else:
            bg_clip = bg_clip.subclip(0, duration)
        bg_clip = bg_clip.resize(height=1920) if bg_clip.h < 1920 else bg_clip
        bg_clip = bg_clip.crop(x_center=bg_clip.w / 2, width=1080, height=1920)
    else:
        bg_clip = ColorClip(size=(1080, 1920), color=(15, 15, 20), duration=duration)

    bg_clip = bg_clip.set_audio(audio)

    # Subtitle Overlay Logic
    words = script_text.split()
    chunk_size = 5
    chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
    chunk_duration = duration / max(len(chunks), 1)

    txt_clips = []
    for idx, chunk in enumerate(chunks):
        start_time = idx * chunk_duration
        txt = (
            TextClip(
                chunk.upper(),
                fontsize=55,
                color="yellow",
                font="DejaVu-Sans-Bold",
                method="caption",
                size=(900, None)
            )
            .set_position(("center", "center"))
            .set_start(start_time)
            .set_duration(chunk_duration)
        )
        txt_clips.append(txt)

    final_video = CompositeVideoClip([bg_clip] + txt_clips)
    final_video.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4
    )

    audio.close()
    bg_clip.close()

# ----------------------------------------------------------------------
# 7. YOUTUBE UPLOAD PIPELINE
# ----------------------------------------------------------------------
def upload_to_youtube(youtube, video_path: str, topic: str, category: str):
    """Uploads compiled video to YouTube."""
    title = f"{topic.title()} #Shorts"
    if len(title) > 100:
        title = title[:95] + "..."

    description = (
        f"Mind-bending facts about {topic}.\n\n"
        f"#shorts #{category} #facts #viral #didyouknow"
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": [topic, category, "shorts", "facts", "educational"],
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = request.execute()
    print(f"Upload Complete! Video ID: {response.get('id')}")

# ----------------------------------------------------------------------
# 8. MAIN EXECUTOR
# ----------------------------------------------------------------------
def main():
    print("--- 1. Authenticating YouTube Client ---")
    youtube = get_youtube_client()

    print("--- 2. Checking Topic Pool ---")
    used_topics = get_used_topics()
    available_topics = [item for item in TOPIC_POOL if item["topic"].lower() not in used_topics]
    print(f"Unused Topics Remaining: {len(available_topics)} / {len(TOPIC_POOL)}")

    if not available_topics:
        print("All topics in the pool have been uploaded!")
        return

    selected = random.choice(available_topics)
    topic = selected["topic"]
    category = selected["category"]
    print(f"Selected Topic: '{topic}' [{category}]")

    print("--- 3. Generating Script with Groq ---")
    script_text = generate_script(topic)
    print(f"Script:\n\"{script_text}\"\n")

    print("--- 4. Generating TTS Voiceover ---")
    asyncio.run(generate_voiceover(script_text, TEMP_AUDIO))

    print("--- 5. Rendering Video Short ---")
    render_video_short(TEMP_AUDIO, script_text, OUTPUT_VIDEO)

    print("--- 6. Uploading to YouTube ---")
    upload_to_youtube(youtube, OUTPUT_VIDEO, topic, category)

    print("--- 7. Saving State ---")
    save_used_topic(topic)

    # Cleanup temp files
    if os.path.exists(TEMP_AUDIO):
        os.remove(TEMP_AUDIO)
    if os.path.exists(OUTPUT_VIDEO):
        os.remove(OUTPUT_VIDEO)

if __name__ == "__main__":
    main()
