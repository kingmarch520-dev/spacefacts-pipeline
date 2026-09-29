"""
YouTube upload module.

ONE-TIME SETUP
1. https://console.cloud.google.com/apis/credentials — create an
   OAuth 2.0 Client ID, type "Desktop app". Enable "YouTube Data
   API v3" for the project. Note the client ID and client secret.
2. Run get_refresh_token(client_id, client_secret) once, from any
   Python environment where you can approve access in a browser
   (Colab works well for this). It prints a refresh token.
3. Store all three as GitHub repo secrets:
       YT_CLIENT_ID
       YT_CLIENT_SECRET
       YT_REFRESH_TOKEN
"""

import os
import json
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "")


def get_access_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": YT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload_video(
    file_path: str,
    title: str,
    description: str,
    tags: list,
    privacy_status: str = "public",
) -> dict:
    access_token = get_access_token()

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    init_resp = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        data=json.dumps(metadata),
        timeout=30,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    with open(file_path, "rb") as f:
        video_bytes = f.read()

    upload_resp = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4"},
        data=video_bytes,
        timeout=600,
    )
    upload_resp.raise_for_status()
    return upload_resp.json()


def set_privacy_status(video_id: str, privacy_status: str):
    access_token = get_access_token()
    resp = requests.put(
        "https://www.googleapis.com/youtube/v3/videos?part=status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps({"id": video_id, "status": {"privacyStatus": privacy_status}}),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def delete_video(video_id: str):
    access_token = get_access_token()
    resp = requests.delete(
        f"https://www.googleapis.com/youtube/v3/videos?id={video_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    resp.raise_for_status()


def get_refresh_token(client_id: str, client_secret: str):
    """Run once, interactively, to get your refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URL,
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube",
        ],
    )
    creds = flow.run_console()
    print("\nYOUR REFRESH TOKEN (save this as YT_REFRESH_TOKEN secret):")
    print(creds.refresh_token)
