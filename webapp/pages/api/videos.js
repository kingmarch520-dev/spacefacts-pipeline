import { fetchVideos } from "../../lib/supabase";

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  try {
    const videos = await fetchVideos();
    res.status(200).json(videos);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
