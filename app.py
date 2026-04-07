import asyncio
import importlib
import re
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="TikTok Live Chat Reader")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_TEXT_LEN = 180
LOG_LIMIT = 300
EVENT_LIMIT = 1200
RECENT_CACHE = 300


class StartPayload(BaseModel):
    unique_id: str


class AppState:
    def __init__(self):
        self.client = None
        self.client_task: Optional[asyncio.Task] = None
        self.current_unique_id: Optional[str] = None
        self.running: bool = False
        self.last_error: Optional[str] = None
        self.logs: Deque[Dict] = deque(maxlen=LOG_LIMIT)
        self.events: Deque[Dict] = deque(maxlen=EVENT_LIMIT)
        self.recent_messages: Deque[str] = deque(maxlen=RECENT_CACHE)
        self.event_id: int = 0
        self.started_at: Optional[float] = None
        self.chat_count: int = 0

    def push_log(self, level: str, message: str):
        self.logs.appendleft(
            {
                "id": self.next_event_id(),
                "ts": time.strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            }
        )

    def push_event(self, event_type: str, payload: Dict):
        self.events.append(
            {
                "id": self.next_event_id(),
                "ts": time.strftime("%H:%M:%S"),
                "type": event_type,
                **payload,
            }
        )

    def next_event_id(self) -> int:
        self.event_id += 1
        return self.event_id


state = AppState()


def clean_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def readable_text(text: str) -> bool:
    if not text:
        return False
    if len(text) > MAX_TEXT_LEN:
        return False
    if not re.search(r"[A-Za-z0-9ก-๙]", text):
        return False
    return True


async def stop_current(reset_logs: bool = False):
    if state.client:
        try:
            await state.client.disconnect()
        except Exception:
            pass

    if state.client_task and not state.client_task.done():
        state.client_task.cancel()
        try:
            await state.client_task
        except BaseException:
            pass

    state.client = None
    state.client_task = None
    state.current_unique_id = None
    state.running = False
    state.started_at = None
    state.recent_messages.clear()
    if reset_logs:
        state.logs.clear()
        state.events.clear()
        state.chat_count = 0
    state.push_event("status", {"message": "stopped"})


def _import_tiktoklive():
    try:
        mod = importlib.import_module("TikTokLive")
        events = importlib.import_module("TikTokLive.events")
        return {
            "TikTokLiveClient": mod.TikTokLiveClient,
            "CommentEvent": events.CommentEvent,
            "ConnectEvent": events.ConnectEvent,
            "DisconnectEvent": events.DisconnectEvent,
            "LiveEndEvent": events.LiveEndEvent,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "ไม่สามารถโหลด TikTokLive ได้บนเซิร์ฟเวอร์นี้: "
                f"{e}. ตรวจสอบว่า requirements ติดตั้งครบและใช้ Python 3.11"
            ),
        )


async def start_reader(unique_id: str):
    unique_id = unique_id.strip().lstrip("@")
    if not unique_id:
        raise HTTPException(status_code=400, detail="กรุณาใส่ TikTok ID")

    await stop_current(reset_logs=True)

    state.running = True
    state.current_unique_id = unique_id
    state.last_error = None
    state.started_at = time.time()
    state.push_log("info", f"Preparing to connect: @{unique_id}")
    state.push_event("status", {"message": f"connecting:{unique_id}"})

    libs = _import_tiktoklive()
    TikTokLiveClient = libs["TikTokLiveClient"]
    CommentEvent = libs["CommentEvent"]
    ConnectEvent = libs["ConnectEvent"]
    DisconnectEvent = libs["DisconnectEvent"]
    LiveEndEvent = libs["LiveEndEvent"]

    client = TikTokLiveClient(unique_id=unique_id)
    state.client = client

    @client.on(ConnectEvent)
    async def _on_connect(_):
        state.push_log("success", f"Connected to @{unique_id}")
        state.push_event("status", {"message": f"connected:{unique_id}"})

    @client.on(DisconnectEvent)
    async def _on_disconnect(_):
        state.push_log("warning", f"Disconnected from @{unique_id}")
        state.push_event("status", {"message": f"disconnected:{unique_id}"})

    @client.on(LiveEndEvent)
    async def _on_live_end(_):
        state.push_log("warning", "Live ended")
        state.push_event("status", {"message": "live_ended"})

    @client.on(CommentEvent)
    async def _on_comment(event):
        nickname = (getattr(event.user, "nickname", None) or "ไม่ทราบชื่อ").strip()
        username = (getattr(event.user, "unique_id", None) or "").strip()
        raw_text = clean_text(getattr(event, "comment", ""))
        if not readable_text(raw_text):
            return

        dedupe_key = f"{nickname}:{raw_text}"
        if dedupe_key in state.recent_messages:
            return
        state.recent_messages.append(dedupe_key)

        spoken_text = f"{nickname} บอกว่า {raw_text}"
        state.chat_count += 1
        state.push_log("chat", spoken_text)
        state.push_event(
            "chat",
            {
                "nickname": nickname,
                "username": username,
                "comment": raw_text,
                "spoken_text": spoken_text,
            },
        )

    async def runner():
        try:
            await client.start()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state.last_error = str(e)
            state.push_log("error", f"Connection error: {e}")
            state.push_event("status", {"message": f"error:{e}"})
            state.running = False

    state.client_task = asyncio.create_task(runner())


@app.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def api_health():
    return {"ok": True, "service": "tiktok-chat-reader"}


@app.post("/api/start")
async def api_start(payload: StartPayload):
    await start_reader(payload.unique_id)
    return {"ok": True, "unique_id": state.current_unique_id}


@app.post("/api/stop")
async def api_stop():
    await stop_current()
    state.push_log("info", "Stopped")
    return {"ok": True}


@app.get("/api/status")
async def api_status():
    uptime = int(time.time() - state.started_at) if state.started_at else 0
    return {
        "running": state.running,
        "unique_id": state.current_unique_id,
        "last_error": state.last_error,
        "chat_count": state.chat_count,
        "uptime_seconds": uptime,
        "latest_event_id": state.event_id,
        "logs": list(state.logs),
    }


@app.get("/api/events")
async def api_events(after_id: int = Query(0, ge=0)):
    events: List[Dict] = [event for event in state.events if event["id"] > after_id]
    return {
        "events": events,
        "latest_event_id": state.event_id,
    }
