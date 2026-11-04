"""Stage 1: generate one Shorts script with Gemini.

Guards against the problems found in the channel analysis:
- truncated scripts (checks finishReason and the final punctuation)
- repeated topics (topics.json log)
- weak openings (hook and "Wait" pivot are required by the prompt and checked)
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "topics.json"
OUT_PATH = ROOT / "script.json"

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Tried in order. A 404 means the key cannot use that model, so the next one is tried.
# Set a GEMINI_MODEL variable in the workflow to force one model first.
MODELS = [
    m for m in [
        os.getenv("GEMINI_MODEL"),
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
    ] if m
]
_working_model = None

# Categories that performed best. Rotated so no category repeats back to back.
CATEGORIES = [
    "deep ocean",
    "deep space scale",
    "ancient engineering",
    "extreme animals",
    "physics paradoxes",
]

MIN_WORDS = 65
MAX_WORDS = 105
MAX_ATTEMPTS = 4


def load_log() -> dict:
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {"topics": []}


def save_log(log: dict) -> None:
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def pick_category(log: dict) -> str:
    used = [t.get("category") for t in log["topics"]]
    last = used[-1] if used else None
    counts = {c: used.count(c) for c in CATEGORIES}
    options = [c for c in CATEGORIES if c != last]
    return min(options, key=lambda c: counts[c])


def build_prompt(category: str, used_titles: list) -> str:
    avoid = "\n".join(f"- {t}" for t in used_titles[-80:]) or "- none yet"
    return f"""You write scripts for a 30 to 40 second YouTube Short in the category: {category}.

Rules:
1. Pick a fresh topic that is NOT similar to any topic in this list:
{avoid}
2. Sentence 1 must be a hook that states an impossible-sounding or surprising fact. No setup, no greeting, no "Did you know".
3. Include one pivot sentence that starts with the word "Wait".
4. Write between {MIN_WORDS} and {MAX_WORDS} words of plain spoken narration. No emojis, no stage directions, no hashtags.
5. The final sentence must be complete and end with a period, question mark or exclamation mark. Vary the ending style, a punchline is optional.
6. Every number and claim must be factually accurate and well established.

Return JSON with exactly these keys:
"topic": a short unique topic label,
"title": a Shorts title under 70 characters,
"script": the narration text,
"search_terms": a list of 4 short stock footage search phrases that match the script."""


def _request(prompt: str, model: str) -> tuple:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,
            # Generous limit so hidden thinking tokens cannot cut the script off.
            # A cut-off is still caught by the finishReason check below.
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    resp = requests.post(
        API_URL.format(model=model),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=90,
    )
    if not resp.ok:
        print(f"Gemini error {resp.status_code} for {model}: {resp.text[:500]}")
        resp.raise_for_status()
    data = resp.json()

    candidate = data["candidates"][0]
    finish = candidate.get("finishReason", "")
    text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
    return text, finish


def call_gemini(prompt: str) -> tuple:
    global _working_model
    models = [_working_model] if _working_model else MODELS

    for model in models:
        try:
            result = _request(prompt, model)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                print(f"Model {model} is not available to this key, trying the next one")
                continue
            raise
        if _working_model != model:
            print(f"Using model: {model}")
        _working_model = model
        return result

    raise RuntimeError("None of the models were available to this API key: " + ", ".join(models))


def validate(item: dict, finish: str, used_topics: set) -> list:
    problems = []

    if finish != "STOP":
        problems.append(f"generation did not finish cleanly (finishReason={finish})")

    for key in ("topic", "title", "script", "search_terms"):
        if not item.get(key):
            problems.append(f"missing field: {key}")
    if problems:
        return problems

    script = item["script"].strip()
    words = len(script.split())

    if not script.endswith((".", "?", "!")):
        problems.append("script does not end with a full sentence")
    if script.endswith("..."):
        problems.append("script ends with an ellipsis")
    if not (MIN_WORDS <= words <= MAX_WORDS):
        problems.append(f"word count {words} outside {MIN_WORDS}-{MAX_WORDS}")
    if not re.search(r"\bWait\b", script):
        problems.append('no "Wait" pivot')
    if len(item["title"]) > 70:
        problems.append("title longer than 70 characters")
    if item["topic"].strip().lower() in used_topics:
        problems.append("topic already used")
    if not isinstance(item["search_terms"], list) or len(item["search_terms"]) < 3:
        problems.append("need at least 3 search terms")

    return problems


def main() -> int:
    log = load_log()
    used_topics = {t["topic"].strip().lower() for t in log["topics"]}
    used_titles = [t["topic"] for t in log["topics"]]
    category = pick_category(log)

    prompt = build_prompt(category, used_titles)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text, finish = call_gemini(prompt)
            item = json.loads(text)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"Attempt {attempt}: unreadable response ({exc})")
            continue

        problems = validate(item, finish, used_topics)
        if not problems:
            item["category"] = category
            OUT_PATH.write_text(json.dumps(item, indent=2), encoding="utf-8")
            log["topics"].append({"topic": item["topic"], "category": category})
            save_log(log)
            print(f"OK on attempt {attempt}: {item['title']}")
            print(item["script"])
            return 0

        print(f"Attempt {attempt} rejected: " + "; ".join(problems))

    print("No valid script after all attempts.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
