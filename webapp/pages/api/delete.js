import { deleteVideo } from "../../lib/youtube";
import { updateVideoStatus } from "../../lib/supabase";

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  const { youtubeId } = req.body;
  if (!youtubeId) {
    return res.status(400).json({ error: "youtubeId is required" });
  }

  try {
    await deleteVideo(youtubeId);
    await updateVideoStatus(youtubeId, "deleted");
    res.status(200).json({ success: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
