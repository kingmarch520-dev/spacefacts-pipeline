import { useEffect, useState } from "react";
import { fetchVideos } from "../lib/supabase";

export async function getServerSideProps() {
  const videos = await fetchVideos();
  return { props: { initialVideos: videos } };
}

const SEA_KEYWORDS = [
  "ocean", "sea", "deep", "trench", "squid", "whale", "hydrothermal",
  "bioluminescence", "underwater", "marine", "mariana",
];

function categorize(topic) {
  if (!topic) return "space";
  const lower = topic.toLowerCase();
  return SEA_KEYWORDS.some((kw) => lower.includes(kw)) ? "sea" : "space";
}

function formatCount(n) {
  if (n === undefined || n === null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function Dashboard({ initialVideos }) {
  const [videos, setVideos] = useState(initialVideos);
  const [pendingId, setPendingId] = useState(null);
  const [stats, setStats] = useState({});
  const [triggerStatus, setTriggerStatus] = useState("");

  async function refresh() {
    const res = await fetch("/api/videos");
    const data = await res.json();
    setVideos(data);
  }

  async function loadStats(videoList) {
    const ids = videoList.map((v) => v.youtube_id).filter(Boolean);
    if (!ids.length) return;
    try {
      const res = await fetch("/api/stats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtubeIds: ids }),
      });
      const data = await res.json();
      setStats(data);
    } catch (err) {
      console.error("Failed to load stats:", err);
    }
  }

  useEffect(() => {
    loadStats(videos);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handlePublish(youtubeId) {
    setPendingId(youtubeId);
    await fetch("/api/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ youtubeId }),
    });
    await refresh();
    setPendingId(null);
  }

  async function handleDelete(youtubeId) {
    setPendingId(youtubeId);
    await fetch("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ youtubeId }),
    });
    await refresh();
    setPendingId(null);
  }

  // ─── Trigger the GitHub Actions pipeline ───
  async function triggerPipeline() {
    setTriggerStatus("⏳ Starting...");
    try {
      const res = await fetch("/api/trigger", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        setTriggerStatus("✅ " + data.message);
      } else {
        setTriggerStatus("❌ " + data.error);
      }
    } catch (err) {
      setTriggerStatus("❌ " + err.message);
    }
    // Auto‑clear after 5 seconds
    setTimeout(() => setTriggerStatus(""), 5000);
  }

  const pendingReview = videos.filter((v) => v.status === "unlisted");
  const decided = videos.filter((v) => v.status !== "unlisted");

  const published = videos.filter((v) => v.status === "public");
  const bySpace = published.filter((v) => categorize(v.topic) === "space");
  const bySea = published.filter((v) => categorize(v.topic) === "sea");

  function avgViews(list) {
    const withStats = list.filter((v) => stats[v.youtube_id]);
    if (!withStats.length) return null;
    const total = withStats.reduce(
      (sum, v) => sum + (stats[v.youtube_id]?.viewCount || 0), 0
    );
    return Math.round(total / withStats.length);
  }

  const spaceAvg = avgViews(bySpace);
  const seaAvg = avgViews(bySea);

  return (
    <div className="wrap">
      <div className="header">
        <div>
          <div className="label">Spacefacts / Control</div>
          <h1>Upload queue</h1>
        </div>
        <div className="header-actions">
          <div className="count">{pendingReview.length} awaiting review</div>
          <button
            className="btn-trigger"
            onClick={triggerPipeline}
            disabled={!!triggerStatus}
          >
            ⚡ Run
          </button>
          {triggerStatus && <span className="trigger-status">{triggerStatus}</span>}
        </div>
      </div>

      {published.length > 0 && (spaceAvg !== null || seaAvg !== null) && (
        <div className="summary">
          <div className="summary-label">Avg views by topic</div>
          <div className="summary-row">
            <div className="summary-item">
              <span className="summary-tag space">space</span>
              <span className="summary-val">
                {spaceAvg !== null ? formatCount(spaceAvg) : "—"}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-tag sea">sea</span>
              <span className="summary-val">
                {seaAvg !== null ? formatCount(seaAvg) : "—"}
              </span>
            </div>
          </div>
        </div>
      )}

      {videos.length === 0 && (
        <div className="empty">No runs logged yet. The daily pipeline
          hasn't uploaded anything. Trigger it manually from GitHub Actions
          if you don't want to wait for the next scheduled run.</div>
      )}

      {[...pendingReview, ...decided].map((v) => {
        const vidStats = stats[v.youtube_id];
        const category = categorize(v.topic);
        return (
          <div className="entry" key={v.youtube_id}>
            <img className="thumb" src={v.thumbnail_url} alt="" />
            <div className="entry-body">
              <div className="entry-meta">
                {new Date(v.created_at).toLocaleDateString(undefined, {
                  month: "short", day: "numeric",
                })} · <span className={`cat-tag ${category}`}>{category}</span>
              </div>
              <div className="entry-title">{v.title}</div>
              <div className="entry-row">
                <div className={`status ${v.status}`}>{v.status}</div>
                {vidStats && (
                  <div className="stats">
                    <span>👁 {formatCount(vidStats.viewCount)}</span>
                    <span>♥ {formatCount(vidStats.likeCount)}</span>
                  </div>
                )}
              </div>
              <div className="actions">
                {v.status === "unlisted" && (
                  <>
                    <button
                      className="publish"
                      disabled={pendingId === v.youtube_id}
                      onClick={() => handlePublish(v.youtube_id)}
                    >
                      Publish
                    </button>
                    <button
                      className="delete"
                      disabled={pendingId === v.youtube_id}
                      onClick={() => handleDelete(v.youtube_id)}
                    >
                      Delete
                    </button>
                  </>
                )}
                <a
                  className="watch-link"
                  href={`https://youtu.be/${v.youtube_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  watch ↗
                </a>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}