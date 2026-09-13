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
  const [errorMsg, setErrorMsg] = useState("");
  const [statsError, setStatsError] = useState("");

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
      if (!res.ok) {
        // Surfaced on-screen now instead of only in the browser console,
        // which you can't easily see on mobile.
        setStatsError(data.error || "Failed to load view counts");
        return;
      }
      setStats(data);
      setStatsError("");
    } catch (err) {
      setStatsError(err.message);
    }
  }

  useEffect(() => {
    loadStats(videos);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handlePublish(youtubeId) {
    setPendingId(youtubeId);
    setErrorMsg("");
    try {
      const res = await fetch("/api/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtubeId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErrorMsg(`Publish failed: ${data.error || res.statusText}`);
      } else {
        await refresh();
      }
    } catch (err) {
      setErrorMsg(`Publish failed: ${err.message}`);
    }
    setPendingId(null);
  }

  async function handleDelete(youtubeId) {
    setPendingId(youtubeId);
    setErrorMsg("");
    try {
      const res = await fetch("/api/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtubeId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErrorMsg(`Delete failed: ${data.error || res.statusText}`);
      } else {
        await refresh();
      }
    } catch (err) {
      setErrorMsg(`Delete failed: ${err.message}`);
    }
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

      {errorMsg && (
        <div style={{
          color: "#e5484d",
          background: "#e5484d18",
          border: "1px solid #e5484d40",
          borderRadius: "8px",
          padding: "10px 14px",
          marginBottom: "16px",
          fontFamily: "var(--mono)",
          fontSize: "12px",
        }}>
          {errorMsg}
        </div>
      )}

      {statsError && (
        <div style={{
          color: "#8a7bb5",
          background: "#12102a",
          border: "1px solid #2a2850",
          borderRadius: "8px",
          padding: "10px 14px",
          marginBottom: "16px",
          fontFamily: "var(--mono)",
          fontSize: "12px",
        }}>
          View counts unavailable: {statsError}
        </div>
      )}

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
