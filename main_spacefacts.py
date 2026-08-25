fallback render with minimal settings...")
            fallback_video = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0,0,0), duration=10)
            txt = TextClip("Video generation failed", font_size=60, color="white", font=None, duration=10).with_position("center")
            final_fallback = CompositeVideoClip([fallback_video, txt], size=(VIDEO_W, VIDEO_H))
            final_fallback.write_videofile(str(out_path), fps=1, codec="libx264", audio_codec="aac", verbose=False)
            log(f"  ⚠️ Fallback video created at {out_path}")
        except Exception as e2:
            log(f"  ❌ Fallback also failed: {e2}")
            raise

    return out_path

# ------------------------------------------------------------------
# 7. MAIN PIPELINE
# ------------------------------------------------------------------

def run_pipeline():
    try:
        topic = get_next_topic()
        log(f"Topic: {topic}")

        log("Generating script...")
        script = generate_script(topic)
        log(f"Title: {script['title']}")

        run_dir = OUTPUT_DIR / script["title"].replace(" ", "_")[:40]
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "script.json").write_text(json.dumps(script, indent=2))

        log("Synthesizing narration...")
        audio_clips = synthesize_scene_audio(script["scenes"], run_dir)

        log("Fetching visuals...")
        visuals = []
        for i, scene in enumerate(script["scenes"]):
            log(f"  Scene {i+1}: '{scene['visual_query']}'")
            visuals.append(get_cached_visual(scene, i, run_dir))

        log("Assembling video...")
        final_path = build_video(script, audio_clips, visuals, run_dir, topic)

        if DRY_RUN:
            log("DRY RUN: Skipping upload.")
            print(f"\n✅ Done: {final_path}")
            return

        log("Uploading to YouTube...")
        description = f"{script.get('hook', '')}\n\n{' '.join(script['hashtags'])}"
        upload_result = youtube_upload.upload_video(
            file_path=str(final_path),
            title=script["title"],
            description=description,
            tags=[h.replace("#", "") for h in script["hashtags"]],
            privacy_status="unlisted",
        )
        video_id = upload_result["id"]
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        supabase_client.log_video(
            youtube_id=video_id,
            title=script["title"],
            description=description,
            hashtags=script["hashtags"],
            thumbnail_url=thumbnail_url,
            topic=topic,
            status="unlisted",
        )

        print(f"\n🎬 Done: {final_path}")
        print(f"📺 YouTube (unlisted): https://youtu.be/{video_id}")
        print("Review and publish from the dashboard.")

    except Exception as e:
        log(f"❌ Pipeline crashed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    run_pipeline()