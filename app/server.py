"""Local web server: upload, silence analysis, AI script, subtitle editor, job queue, WebSocket progress.

Run:  python run.py  (bound to 0.0.0.0:8080 for PC & mobile access)
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import ai_writer, mixer, pipeline, silence, subtitles
from core.ffmpeg_utils import get_duration, get_video_size, has_nvenc, probe
from core.pipeline import JobOptions

ROOT = Path(__file__).resolve().parent.parent
UPLOADS, OUTPUTS = ROOT / "input", ROOT / "output"
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

app = FastAPI(title="Auto Video Editor (local)")
JOBS: dict[str, dict] = {}
Q: "queue.Queue[str]" = queue.Queue()  # one job at a time -> GPU is never oversubscribed


def _find_upload(file_id: str) -> Path:
    if not file_id.isalnum():
        raise HTTPException(400, "file id không hợp lệ")
    matches = list(UPLOADS.glob(f"{file_id}.*"))
    if not matches:
        raise HTTPException(404, "Không tìm thấy file đã upload")
    return matches[0]


# ---------------------------------------------------------------- worker
def _overall(job: dict) -> float:
    total = sum(s["weight"] for s in job["stages"]) or 1
    return sum(s["weight"] * s["progress"] for s in job["stages"]) / total


def _worker() -> None:
    while True:
        jid = Q.get()
        job = JOBS[jid]
        job["status"], job["started"] = "running", time.time()

        def on_update(sid: str, p: float, msg: str) -> None:
            for s in job["stages"]:
                if s["id"] == sid:
                    s["progress"] = max(0.0, min(p, 1.0))
                    s["state"] = "done" if p >= 1 else "running"
            job["message"] = msg
            job["progress"] = _overall(job)

        try:
            out = OUTPUTS / f"{jid}.mp4"
            job["result"] = pipeline.run_pipeline(job["src"], out, job["options"], on_update)
            job.update(status="done", progress=1.0, message="Hoàn tất", output=out.name)
        except Exception as e:
            traceback.print_exc()
            job.update(status="error", message=str(e)[-1500:])
        finally:
            job["finished"] = time.time()
            Q.task_done()


threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------- API
@app.get("/api/info")
def info() -> dict:
    return {"nvenc": has_nvenc()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    fid = uuid.uuid4().hex[:12]
    ext = Path(file.filename or "x.mp4").suffix.lower() or ".bin"
    dest = UPLOADS / f"{fid}{ext}"
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    try:
        meta = await asyncio.to_thread(probe, dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"File không hợp lệ: {e}")
    v = next((s for s in meta["streams"] if s["codec_type"] == "video"), None)
    return {
        "id": fid,
        "name": file.filename,
        "ext": ext,
        "duration": float(meta["format"]["duration"]),
        "width": v and int(v["width"]),
        "height": v and int(v["height"]),
        "url": f"/uploads/{dest.name}",
    }


@app.get("/api/analyze")
async def analyze(id: str, min_silence: float = 0.5, noise_db: float = -35.0, padding: float = 0.08) -> dict:
    """Preview of silence detection for timeline."""
    path = _find_upload(id)
    dur = await asyncio.to_thread(get_duration, path)
    sil = await asyncio.to_thread(silence.detect_silences, path, min_silence, noise_db)
    keep = silence.compute_keep_segments(sil, dur, padding)
    kept = sum(e - s for s, e in keep)
    return {"duration": dur, "keep": keep, "silences": sil, "result_duration": kept}


@app.post("/api/ai-script")
async def generate_script(
    file_id: str = Form(...),
    style: str = Form("tiktok_viral"),
    topic: str = Form(""),
    provider: str = Form("auto"),
    api_key: Optional[str] = Form(None),
    ollama_model: str = Form("qwen2.5:latest"),
) -> dict:
    """Generate voiceover script using AI based on video duration & speech content."""
    src = _find_upload(file_id)
    try:
        res = await ai_writer.write_video_script(
            video_path=src,
            style=style,
            topic=topic,
            provider=provider,
            api_key=api_key,
            ollama_model=ollama_model,
        )
        return res
    except Exception as e:
        raise HTTPException(500, f"Lỗi khi viết kịch bản AI: {e}")


@app.post("/api/subtitles/transcribe")
async def transcribe_subtitles(
    file_id: str = Form(...),
    sub_model: str = Form("small"),
    sub_language: str = Form("vi"),
) -> dict:
    """Get editable transcript segments for the interactive subtitle editor."""
    src = _find_upload(file_id)
    try:
        segments = await asyncio.to_thread(
            subtitles.transcribe_to_segments,
            src,
            model_size=sub_model,
            language=sub_language or None,
        )
        return {"segments": segments}
    except Exception as e:
        raise HTTPException(500, f"Lỗi nhận diện phụ đề: {e}")


@app.post("/api/subtitles/save")
async def save_custom_subtitles(
    file_id: str = Form(...),
    segments_json: str = Form(...),
    aspect: str = Form("original"),
    aspect_mode: str = Form("blur"),
    sub_font_size: Optional[int] = Form(None),
    sub_highlight: str = Form("#FFD400"),
) -> dict:
    """Save user-edited subtitle segments as an .ass file."""
    src = _find_upload(file_id)
    try:
        segments = json.loads(segments_json)
        _, size = mixer.build_video_filter(get_video_size(src), aspect, aspect_mode)
        ass_path = OUTPUTS / f"{file_id}_custom.ass"
        subtitles.segments_to_ass(
            segments,
            ass_path,
            width=size[0],
            height=size[1],
            font_size=sub_font_size,
            highlight=sub_highlight,
        )
        return {"ass_path": str(ass_path)}
    except Exception as e:
        raise HTTPException(500, f"Lỗi lưu phụ đề: {e}")


@app.post("/api/jobs")
async def create_job(
    file_id: str = Form(...),
    cut_silence: bool = Form(False),
    min_silence: float = Form(0.5),
    noise_db: float = Form(-35.0),
    dub: bool = Form(False),
    script: str = Form(""),
    voice: str = Form("hoaimy"),
    rate: str = Form("+0%"),
    bgm_id: Optional[str] = Form(None),
    bgm_volume: float = Form(0.35),
    keep_original: float = Form(0.0),
    subtitles: bool = Form(False),
    sub_model: str = Form("small"),
    sub_language: str = Form("vi"),
    sub_highlight: str = Form("#FFD400"),
    sub_font_size: Optional[int] = Form(None),
    custom_ass_path: Optional[str] = Form(None),
    color_preset: str = Form("none"),
    auto_zoom: bool = Form(False),
    watermark_text: str = Form(""),
    aspect: str = Form("original"),
    aspect_mode: str = Form("blur"),
    fps: int = Form(60),
    use_gpu: bool = Form(True),
) -> dict:
    src = _find_upload(file_id)
    if dub and not script.strip():
        raise HTTPException(400, "Bật lồng tiếng nhưng chưa nhập kịch bản")
    o = JobOptions(
        cut_silence=cut_silence,
        min_silence=min_silence,
        noise_db=noise_db,
        dub=dub,
        script=script,
        voice=voice,
        rate=rate,
        bgm=str(_find_upload(bgm_id)) if bgm_id else None,
        bgm_volume=bgm_volume,
        keep_original=keep_original,
        subtitles=subtitles,
        sub_model=sub_model,
        sub_language=sub_language or None,
        sub_highlight=sub_highlight,
        sub_font_size=sub_font_size,
        custom_sub_ass=custom_ass_path,
        color_preset=color_preset,
        auto_zoom=auto_zoom,
        watermark_text=watermark_text,
        aspect=aspect,
        aspect_mode=aspect_mode,
        fps=fps or None,
        use_gpu=use_gpu,
    )
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {
        "id": jid,
        "src": str(src),
        "options": o,
        "status": "queued",
        "progress": 0.0,
        "message": "Đang chờ trong hàng đợi",
        "output": None,
        "created": time.time(),
        "stages": [
            {"id": i, "label": l, "weight": w, "progress": 0.0, "state": "pending"}
            for i, l, w in pipeline.plan_stages(o)
        ],
    }
    Q.put(jid)
    return {"id": jid}


def _public(job: dict) -> dict:
    d = {k: v for k, v in job.items() if k not in ("options", "src")}
    d["url"] = f"/files/{job['output']}" if job.get("output") else None
    d["position"] = (
        max(list(Q.queue).index(job["id"]) + 1, 0)
        if job["id"] in list(Q.queue)
        else 0
    )
    return d


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict:
    if jid not in JOBS:
        raise HTTPException(404)
    return _public(JOBS[jid])


@app.websocket("/ws/{jid}")
async def ws_progress(ws: WebSocket, jid: str) -> None:
    await ws.accept()
    if jid not in JOBS:
        await ws.close(code=4404)
        return
    try:
        last = None
        while True:
            snap = _public(JOBS[jid])
            if snap != last:
                await ws.send_json(snap)
                last = snap
            if snap["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return
    await ws.close()


@app.get("/files/{name}")
def download(name: str, dl: int = 0):
    path = OUTPUTS / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4", filename=name if dl else None)


app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")
