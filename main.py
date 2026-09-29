# ==================================================================
# GEMINI SCRIPT GENERATION
# ==================================================================

# Try newer models first, then fall back to the model we already
# know works for this project.
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]


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
    Decide whether a Gemini error is worth retrying.

    429 / RESOURCE_EXHAUSTED:
        Usually quota or rate limiting. Retry.

    500 / 502 / 503 / 504:
        Temporary Google server/API problems. Retry.

    Network/connection errors:
        Retry.

    Authentication, invalid-request, or permission errors:
        Do not retry indefinitely.
    """

    msg = str(e).lower()

    # --------------------------------------------------------------
    # Temporary API/server errors
    # --------------------------------------------------------------

    transient_markers = (
        "429",
        "resource_exhausted",
        "quota",
        "rate limit",
        "500 internal",
        "502 bad gateway",
        "503 unavailable",
        "504 gateway",
        "service unavailable",
        "temporarily unavailable",
        "high demand",
        "deadline exceeded",
        "timeout",
        "connection",
        "connection reset",
        "connection aborted",
    )

    if any(marker in msg for marker in transient_markers):
        return True

    # --------------------------------------------------------------
    # Don't endlessly retry obvious permanent errors.
    # --------------------------------------------------------------

    permanent_markers = (
        "401",
        "403",
        "unauthorized",
        "permission denied",
        "invalid api key",
        "api key not valid",
        "400 bad request",
        "invalid argument",
        "malformed",
    )

    if any(marker in msg for marker in permanent_markers):
        return False

    # Unknown API/network errors get one chance to recover.
    return True


def is_model_unavailable_error(e) -> bool:
    """
    Errors indicating that a particular model cannot currently be used.

    These should cause us to move to the next model instead of repeatedly
    hammering the same model.
    """

    msg = str(e).lower()

    markers = (
        "404",
        "not found",
        "is not found",
        "model not found",
        "not supported",
        "unsupported model",
        "model is unavailable",
        "unavailable for",
    )

    return any(marker in msg for marker in markers)


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

    last_error = None

    # --------------------------------------------------------------
    # Try models in order
    # --------------------------------------------------------------

    for model_index, model_name in enumerate(
        GEMINI_MODELS
    ):

        print(
            f"      Trying Gemini model: "
            f"{model_name}"
        )

        def _call_gemini():

            return client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                },
            )

        try:

            response = retry_with_backoff(
                _call_gemini,
                retries=4,
                base_delay=20,
                should_retry=is_gemini_retryable_error,
            )

            print(
                f"      Gemini model succeeded: "
                f"{model_name}"
            )

            break

        except Exception as e:

            last_error = e

            print(
                f"      Model failed: "
                f"{model_name}"
            )

            print(
                f"      Error: {e}"
            )

            # ------------------------------------------------------
            # If this model is unavailable/not found, immediately
            # try the next model.
            # ------------------------------------------------------

            if is_model_unavailable_error(e):

                if (
                    model_index
                    < len(GEMINI_MODELS) - 1
                ):

                    next_model = GEMINI_MODELS[
                        model_index + 1
                    ]

                    print(
                        f"      Switching to "
                        f"{next_model}..."
                    )

                    continue

            # ------------------------------------------------------
            # For a temporary server problem, also try the next
            # model after this model's retries are exhausted.
            # ------------------------------------------------------

            msg = str(e).lower()

            if (
                "503" in msg
                or "high demand" in msg
                or "service unavailable" in msg
            ):

                if (
                    model_index
                    < len(GEMINI_MODELS) - 1
                ):

                    next_model = GEMINI_MODELS[
                        model_index + 1
                    ]

                    print(
                        f"      {model_name} is "
                        f"temporarily unavailable."
                    )

                    print(
                        f"      Switching to "
                        f"{next_model}..."
                    )

                    continue

            # ------------------------------------------------------
            # Other errors should not silently switch models.
            # ------------------------------------------------------

            raise

    else:

        raise last_error

    # --------------------------------------------------------------
    # Validate response
    # --------------------------------------------------------------

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

        print(
            response.text
        )

        raise RuntimeError(
            "Gemini response was not valid JSON."
        ) from e

    # --------------------------------------------------------------
    # Validate response structure
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
                + str(
                    scene["visual_type"]
                )
            )

    return data