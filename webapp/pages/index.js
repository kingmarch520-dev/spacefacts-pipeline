import { useEffect, useState } from "react";
import { fetchVideos } from "../lib/supabase";

export async function getServerSideProps() {
  const videos = await fetchVideos();
  return { props: { initialVideos: videos } };
}

export default function Dashboard({ initialVideos }) {
  const [videos, setVideos] = useState(initialVideos);
  const [pendingId, setPendingId] = useState(null);

  async function refresh() {
    const res = await fetch("/api/videos");
    const data = await res.json();
    setVideos(data);
  }

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

  const pendingReview = videos.filter((v) => v.status === "unlisted");
  const decided = videos.filter((v) => v.status !== "unlisted");

  return (
    <div className="wrap">
      <div className="header">
        <div>
          <div className="label">Spacefacts / Control</div>
          <h1>Upload queue</h1>
        </div>
        <div className="count">
          {pendingReview.length} awaiting review
        </div>
      </div>

      {videos.length === 0 && (
        <div className="empty">No runs logged yet. The daily pipeline
          hasn't uploaded anything. Trigger it manually from GitHub Actions
          if you don't want to wait for the next scheduled run.</div>
      )}

      {[...pendingReview, ...decided].map((v) => (
        <div className="entry" key={v.youtube_id}>
          <img className="thumb" src={v.thumbnail_url} alt="" />
          <div className="entry-body">
            <div className="entry-meta">
              {new Date(v.created_at).toLocaleDateString(undefined, {
                month: "short", day: "numeric",
              })} · {v.topic || "space fact"}
            </div>
            <div className="entry-title">{v.title}</div>
            <div className={`status ${v.status}`}>{v.status}</div>
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
      ))}
    </div>
  );
}
