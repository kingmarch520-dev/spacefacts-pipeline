// Server-side only — uses the service role key, never exposed to the browser.

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;

const HEADERS = {
  apikey: SUPABASE_SERVICE_KEY,
  Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`,
  "Content-Type": "application/json",
};

export async function fetchVideos() {
  const resp = await fetch(
    `${SUPABASE_URL}/rest/v1/videos?select=*&order=created_at.desc`,
    { headers: HEADERS }
  );
  if (!resp.ok) throw new Error("Failed to fetch videos from Supabase");
  return resp.json();
}

export async function updateVideoStatus(youtubeId, status) {
  const resp = await fetch(
    `${SUPABASE_URL}/rest/v1/videos?youtube_id=eq.${youtubeId}`,
    {
      method: "PATCH",
      headers: HEADERS,
      body: JSON.stringify({ status }),
    }
  );
  if (!resp.ok) throw new Error("Failed to update video status in Supabase");
  return resp.json();
}
