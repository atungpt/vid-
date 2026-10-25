"""Local, review-gated meme localization pipeline."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(response):
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"API error {response.status_code}: {response.text[:600]}") from exc
    return response.json()


def discover(folder, query):
    """Save Agent-Reach search output for human source selection."""
    folder.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["agent-reach", "youtube", "search", query], check=True, capture_output=True, text=True)
    (folder / "discovery.txt").write_text(result.stdout, encoding="utf-8")
    print(result.stdout)


def prepare(folder):
    source = read(folder / "source.json")
    if source.get("permission_to_reuse") is not True or not source.get("source_note"):
        raise ValueError("Cần permission_to_reuse=true và source_note có chứng cứ.")
    url = source["url"]
    run("yt-dlp", "--no-playlist", "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", folder / "original.%(ext)s", url)
    video = folder / "original.mp4"
    if not video.exists():
        raise RuntimeError("Nguồn không xuất thành original.mp4; kiểm tra định dạng và quyền tải.")
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(video), vad_filter=True)
    transcript = [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()} for s in segments]
    write(folder / "transcript.json", {"language": info.language, "segments": transcript})
    # OCR samples once per two seconds; output is evidence for manual frame-level review.
    import pytesseract
    from PIL import Image
    from io import BytesIO
    duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)], text=True).strip())
    ocr = []
    for sec in range(0, min(int(duration) + 1, 180), 2):
        frame = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-ss", str(sec), "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"])
        words = pytesseract.image_to_string(Image.open(BytesIO(frame))).strip()
        if words:
            ocr.append({"second": sec, "text": words})
    write(folder / "ocr.json", ocr)


def localize(folder):
    from openai import OpenAI
    source, transcript, ocr = read(folder / "source.json"), read(folder / "transcript.json"), read(folder / "ocr.json")
    client = OpenAI()
    prompt = {"source": source, "transcript": transcript, "ocr": ocr}
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Bạn biên tập meme cho người Việt. Dịch đúng nghĩa câu đùa và ngữ cảnh, rồi diễn đạt tự nhiên bằng slang Gen Z Việt Nam khi phù hợp. Không thêm ý, không chế thông tin, không lạm dụng slang. Xuất JSON: {segments:[{start:number,end:number,text:string}], onscreen:[{second:number,original:string,vi:string}], post_caption:string}. Giữ đúng start/end và số lượng segments đầu vào. onscreen liệt kê chữ gắn trong hình cần thay/che để biên tập thủ công. Không giả vờ đã thay chữ trong video."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
    data = json.loads(response.choices[0].message.content)
    original = transcript["segments"]
    if len(data["segments"]) != len(original):
        raise ValueError("Số đoạn dịch không khớp transcript; cần biên tập lại.")
    for a, b in zip(data["segments"], original):
        a["start"], a["end"] = b["start"], b["end"]
    write(folder / "localized.json", data)
    (folder / "post.txt").write_text(data["post_caption"].strip() + "\n", encoding="utf-8")


def timestamp(sec):
    ms = round(float(sec) * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def render(folder):
    segments = read(folder / "localized.json")["segments"]
    lines = []
    for i, row in enumerate(segments, 1):
        if not row["text"].strip() or row["end"] <= row["start"]:
            continue
        lines.extend([str(i), f"{timestamp(row['start'])} --> {timestamp(row['end'])}", row["text"].strip(), ""])
    (folder / "viet.srt").write_text("\n".join(lines), encoding="utf-8")
    # FFmpeg subtitles filter interprets drive-colons and quotes; relative path avoids them.
    run("ffmpeg", "-y", "-i", "original.mp4", "-vf", "subtitles=viet.srt:force_style='FontName=Arial,FontSize=22,Outline=2,Shadow=1,MarginV=55'", "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "final.mp4")


def approve(folder):
    if not (folder / "final.mp4").exists() or not (folder / "post.txt").exists():
        raise FileNotFoundError("Cần final.mp4 và post.txt trước khi duyệt.")
    write(folder / "approved.json", {"video_sha256": digest(folder / "final.mp4"), "caption_sha256": digest(folder / "post.txt")})


def preflight(folder, channel):
    approval = read(folder / "approved.json")
    if digest(folder / "final.mp4") != approval["video_sha256"] or digest(folder / "post.txt") != approval["caption_sha256"]:
        raise ValueError("File đã đổi sau khi duyệt; xem lại video rồi chạy approve.")
    if (folder / f"published-{channel}.json").exists():
        raise ValueError(f"Đã có kết quả {channel}; kiểm tra trước khi đăng lại.")
    return (folder / "post.txt").read_text(encoding="utf-8").strip()


def facebook(folder):
    caption = preflight(folder, "facebook")
    token, page = os.environ["META_PAGE_ACCESS_TOKEN"], os.environ["META_PAGE_ID"]
    version = os.getenv("META_GRAPH_VERSION", "v24.0")
    endpoint = f"https://graph.facebook.com/{version}/{page}/video_reels"
    start = checked(requests.post(endpoint, data={"access_token": token, "upload_phase": "start"}, timeout=30))
    video_id = start["video_id"]
    video = folder / "final.mp4"
    with video.open("rb") as file:
        checked(requests.post(f"https://rupload.facebook.com/video-upload/{version}/{video_id}", headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(video.stat().st_size), "Content-Type": "application/octet-stream"}, data=file, timeout=600))
    result = checked(requests.post(endpoint, data={"access_token": token, "video_id": video_id, "upload_phase": "finish", "video_state": "PUBLISHED", "description": caption}, timeout=60))
    write(folder / "published-facebook.json", {"video_id": video_id, "response": result})


def tiktok(folder):
    caption = preflight(folder, "tiktok")
    token = os.environ["TIKTOK_ACCESS_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    root = "https://open.tiktokapis.com/v2/post/publish"
    creator = checked(requests.post(root + "/creator_info/query/", headers=headers, json={}, timeout=30))
    if creator.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok creator info: {creator.get('error')}")
    options = creator["data"]["privacy_level_options"]
    if "SELF_ONLY" not in options:
        raise ValueError(f"Không có SELF_ONLY trong quyền riêng tư TikTok: {options}")
    video = folder / "final.mp4"
    size = video.stat().st_size
    chunk = min(size, 10 * 1024 * 1024)
    count = (size + chunk - 1) // chunk
    info = checked(requests.post(root + "/video/init/", headers=headers, json={"post_info": {"title": caption[:2200], "privacy_level": "SELF_ONLY", "disable_duet": True, "disable_comment": True, "disable_stitch": True}, "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}}, timeout=30))
    if info.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok init: {info.get('error')}")
    upload = info["data"]["upload_url"]
    publish_id = info["data"]["publish_id"]
    with video.open("rb") as file:
        for i in range(count):
            part = file.read(chunk)
            start, end = i * chunk, i * chunk + len(part) - 1
            response = requests.put(upload, headers={"Content-Type": "video/mp4", "Content-Length": str(len(part)), "Content-Range": f"bytes {start}-{end}/{size}"}, data=part, timeout=180)
            response.raise_for_status()
    write(folder / "published-tiktok.json", {"publish_id": publish_id, "state": "upload_complete_check_publish_status"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["discover", "prepare", "localize", "render", "approve", "publish-facebook", "publish-tiktok"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--query", default="brainrot meme")
    args = parser.parse_args()
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if args.command == "render":
        os.chdir(folder)
    if args.command == "discover":
        discover(folder, args.query)
        return
    {"prepare": prepare, "localize": localize, "render": render, "approve": approve, "publish-facebook": facebook, "publish-tiktok": tiktok}[args.command](folder)


if __name__ == "__main__":
    main()
