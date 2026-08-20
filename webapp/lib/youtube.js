// Server-side only — uses env vars set in Vercel project settings.
// Never imported into any client-facing component.

async function getAccessToken() {
  const resp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: process.env.YT_CLIENT_ID,
      client_secret: process.env.YT_CLIENT_SECRET,
      refresh_token: process.env.YT_REFRESH_TOKEN,
      grant_type: "refresh_token",
    }),
  });
  if (!resp.ok) throw new Error("Failed to refresh YouTube access token");
  const data = await resp.json();
  return data.access_token;
}

export async function setPrivacyStatus(videoId, privacyStatus) {
  const accessToken = await getAccessToken();
  const resp = await fetch(
    "https://www.googleapis.com/youtube/v3/videos?part=status",
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        id: videoId,
        status: { privacyStatus },
      }),
    }
  );
  if (!resp.ok) throw new Error(`YouTube update failed: ${await resp.text()}`);
  return resp.json();
}

export async function deleteVideo(videoId) {
  const accessToken = await getAccessToken();
  const resp = await fetch(
    `https://www.googleapis.com/youtube/v3/videos?id=${videoId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    }
  );
  if (!resp.ok && resp.status !== 204) {
    throw new Error(`YouTube delete failed: ${await resp.text()}`);
  }
}

export async function getVideoStats(videoIds) {
  // videos.list accepts up to 50 comma-separated ids per call
  if (!videoIds.length) return {};
  const accessToken = await getAccessToken();
  const idsParam = videoIds.join(",");
  const resp = await fetch(
    `https://www.googleapis.com/youtube/v3/videos?part=statistics&id=${idsParam}`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!resp.ok) throw new Error(`YouTube stats fetch failed: ${await resp.text()}`);
  const data = await resp.json();

  const statsMap = {};
  for (const item of data.items || []) {
    statsMap[item.id] = {
      viewCount: parseInt(item.statistics.viewCount || "0", 10),
      likeCount: parseInt(item.statistics.likeCount || "0", 10),
    };
  }
  return statsMap;
}
