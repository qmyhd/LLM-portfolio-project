"""Manual spike: confirm youtube-transcript-api works from this machine."""
from src.youtube import fetch_transcript, parse_video_id

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # known public video w/ captions
vid = parse_video_id(URL)
ok, segs, reason = fetch_transcript(vid)
print(f"video={vid} available={ok} reason={reason} n_segments={len(segs)}")
print(segs[:2])
