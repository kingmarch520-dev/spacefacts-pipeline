import { getVideoStats } from "../../lib/youtube";

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  const { youtubeIds } = req.body;
  if (!Array.isArray(youtubeIds)) {
    return res.status(400).json({ error: "youtubeIds must be an array" });
  }

  try {
    const stats = await getVideoStats(youtubeIds);
    res.status(200).json(stats);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
