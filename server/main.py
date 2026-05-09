"""
ai-nexus  multi-user web chat server
FastAPI + WebSocket  ·  intent detection  ·  pipeline bridge
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# ─── paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT         = os.path.dirname(SCRIPT_DIR)
MANAGER_PS1  = os.path.join(ROOT, "manager.ps1")
STATE_FILE   = os.path.join(ROOT, "STATE.json")
STATIC_DIR   = os.path.join(SCRIPT_DIR, "static")

# ─── intent detection ─────────────────────────────────────────────────────────
_ACTION_KO = (
    r"만들어|작성해|생성해|개발해|구현해|수정해|고쳐|분석해|조사해|"
    r"빌드해|배포해|테스트해|검토해|리팩터|설계해|정리해|요약해|번역해|"
    r"짜줘|해줘|써줘|풀어줘|찾아줘|알아봐|처리해|실행해|시작해"
)
_ACTION_EN = (
    r"\b(?:create|build|make|write|generate|develop|implement|fix|"
    r"analyze|analyse|research|deploy|test|review|refactor|design|"
    r"start|run|execute|check|find|summarize|translate)\b"
)
_NOUN_KO = (
    r"앱|웹사이트|서버|API|코드|스크립트|함수|클래스|파일|데이터|"
    r"보고서|문서|기능|모듈|컴포넌트|데이터베이스|시스템|플러그인|"
    r"프로그램|페이지|폼|UI|UX|봇|자동화"
)
_NOUN_EN = (
    r"\b(?:app|website|server|api|code|script|function|class|file|"
    r"data|report|document|feature|module|component|database|system|"
    r"plugin|program|page|form|bot|automation)\b"
)
_INTENT_RE = re.compile(
    rf"(?:(?:{_ACTION_KO})|(?:{_ACTION_EN})).*?(?:(?:{_NOUN_KO})|(?:{_NOUN_EN}))"
    rf"|(?:(?:{_NOUN_KO})|(?:{_NOUN_EN})).*?(?:(?:{_ACTION_KO})|(?:{_ACTION_EN}))",
    re.IGNORECASE,
)

def detect_intent(text: str) -> Optional[str]:
    """Return matched snippet if text looks like a work request, else None."""
    m = _INTENT_RE.search(text)
    return m.group(0) if m else None


# ─── pipeline state ────────────────────────────────────────────────────────────
PIPELINE_STAGES = [
    "INTAKE", "CLARIFY", "RESEARCH", "DEEP_RESEARCH", "HALLCHECK",
    "PLAN", "PARALLEL_EXECUTE", "INTEGRATE", "CODEX_REVIEW",
    "GEMINI_CHECK", "CLAUDE_RECHECK", "INT_REVIEW", "FINISH",
]

def read_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ─── room / connection manager ────────────────────────────────────────────────
class Room:
    def __init__(self, room_id: str):
        self.id = room_id
        self.connections: Dict[str, WebSocket] = {}   # user_id → ws
        self.history: deque = deque(maxlen=200)
        self.pipeline_running = False
        self.pipeline_goal: Optional[str] = None

    def add(self, user_id: str, ws: WebSocket):
        self.connections[user_id] = ws

    def remove(self, user_id: str):
        self.connections.pop(user_id, None)

    async def broadcast(self, msg: dict, exclude: Optional[str] = None):
        dead = []
        for uid, ws in self.connections.items():
            if uid == exclude:
                continue
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.remove(uid)

    async def broadcast_all(self, msg: dict):
        await self.broadcast(msg, exclude=None)

    def record(self, msg: dict):
        self.history.append(msg)


class RoomManager:
    def __init__(self):
        self._rooms: Dict[str, Room] = {}

    def get_or_create(self, room_id: str) -> Room:
        if room_id not in self._rooms:
            self._rooms[room_id] = Room(room_id)
        return self._rooms[room_id]

    def list_rooms(self) -> List[dict]:
        return [
            {
                "id": r.id,
                "users": list(r.connections.keys()),
                "pipeline_running": r.pipeline_running,
            }
            for r in self._rooms.values()
        ]


rooms = RoomManager()

# ─── pipeline bridge ──────────────────────────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None


def _run_pipeline(room: Room, goal: str):
    """Run manager.ps1 in a background thread; stream logs to the room."""
    room.pipeline_running = True
    room.pipeline_goal = goal

    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", MANAGER_PS1,
        "-Goal", goal,
        "-Auto",
    ]

    def emit(msg: dict):
        if _loop:
            asyncio.run_coroutine_threadsafe(room.broadcast_all(msg), _loop)

    emit({"type": "pipeline.start", "goal": goal, "ts": _now()})

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )

        last_state_check = 0.0
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            emit({"type": "pipeline.log", "text": line, "ts": _now()})

            now = time.time()
            if now - last_state_check > 2:
                last_state_check = now
                state = read_state()
                if state:
                    emit({"type": "pipeline.state", "state": state, "ts": _now()})

        proc.wait()

    except Exception as exc:
        emit({"type": "pipeline.log", "text": f"[ERROR] {exc}", "ts": _now()})
    finally:
        state = read_state()
        emit({"type": "pipeline.done", "state": state, "ts": _now()})
        room.pipeline_running = False


def start_pipeline_thread(room: Room, goal: str):
    t = threading.Thread(target=_run_pipeline, args=(room, goal), daemon=True)
    t.start()


# ─── STATE.json watcher ───────────────────────────────────────────────────────
async def _state_watcher():
    """Periodically broadcast STATE.json to all rooms (fallback polling)."""
    prev: Dict[str, str] = {}
    while True:
        await asyncio.sleep(3)
        for room in rooms._rooms.values():
            if not room.connections:
                continue
            state = read_state()
            key = room.id
            serialized = json.dumps(state, sort_keys=True)
            if prev.get(key) != serialized:
                prev[key] = serialized
                await room.broadcast_all(
                    {"type": "pipeline.state", "state": state, "ts": _now()}
                )


# ─── helpers ──────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ─── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(title="ai-nexus chat server")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def _startup():
    global _loop
    _loop = asyncio.get_event_loop()
    asyncio.create_task(_state_watcher())


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/rooms")
async def api_rooms():
    return {"rooms": rooms.list_rooms()}


@app.get("/api/state")
async def api_state():
    return read_state()


@app.websocket("/ws/{room_id}/{user_id}")
async def ws_endpoint(websocket: WebSocket, room_id: str, user_id: str):
    await websocket.accept()
    room = rooms.get_or_create(room_id)
    room.add(user_id, websocket)

    # send history to newcomer
    for msg in room.history:
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    # announce join
    join_msg = {
        "type": "room.join",
        "user": user_id,
        "room": room_id,
        "ts": _now(),
    }
    room.record(join_msg)
    await room.broadcast_all(join_msg)

    # send current pipeline state if any
    state = read_state()
    if state:
        await websocket.send_json(
            {"type": "pipeline.state", "state": state, "ts": _now()}
        )

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                text: str = data.get("text", "").strip()
                if not text:
                    continue

                chat_msg = {
                    "type": "chat",
                    "user": user_id,
                    "text": text,
                    "ts": _now(),
                }
                room.record(chat_msg)
                await room.broadcast_all(chat_msg)

                # intent detection
                snippet = detect_intent(text)
                if snippet and not room.pipeline_running:
                    intent_msg = {
                        "type": "intent.detected",
                        "user": user_id,
                        "snippet": snippet,
                        "full_text": text,
                        "ts": _now(),
                    }
                    room.record(intent_msg)
                    await room.broadcast_all(intent_msg)

            elif msg_type == "pipeline.start":
                goal: str = data.get("goal", "").strip()
                if not goal:
                    continue
                if room.pipeline_running:
                    await websocket.send_json(
                        {"type": "error", "text": "파이프라인이 이미 실행 중입니다.", "ts": _now()}
                    )
                    continue
                start_pipeline_thread(room, goal)

            elif msg_type == "pipeline.stop":
                # graceful: just flag; actual kill not implemented
                await room.broadcast_all(
                    {"type": "pipeline.log", "text": "[사용자가 중지 요청]", "ts": _now()}
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        room.remove(user_id)
        leave_msg = {"type": "room.leave", "user": user_id, "ts": _now()}
        room.record(leave_msg)
        await room.broadcast_all(leave_msg)
