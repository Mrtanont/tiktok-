"""
FastAPI application to read TikTok Live comments and broadcast them to
connected WebSocket clients. This application serves a minimal web UI
allowing the user to enter a TikTok username, start and stop listening
for live comments, and listen to those comments via the browser's
speech synthesis API. A simple dark/light theme toggle is included.

The `TikTokLive` package is used to connect to TikTok live streams. If
it isn't available at runtime, the application will log an error and
gracefully degrade such that no comments will be received. This allows
the UI to load even if the library is missing.
"""

import os
import asyncio
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Mount the static directory if it exists. This prevents runtime errors
# when the directory is missing on deployment.
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Keep a mapping of TikTok usernames to lists of connected WebSocket clients.
clients: Dict[str, List[WebSocket]] = {}

# Keep track of running TikTok listener tasks so that multiple clients
# connecting to the same username share the same underlying connection.
listener_tasks: Dict[str, asyncio.Task] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health() -> Dict[str, str]:
    """Provide a simple health check endpoint."""
    return {"status": "ok"}


@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str) -> None:
    """Handle WebSocket connections per TikTok username.

    When a client connects, add them to the list of listeners for the
    specified username. If no listener task is currently running for
    that username, start one. When the client disconnects, remove them
    from the list. If there are no more clients listening for a given
    username, cancel the corresponding TikTok listener task.
    """
    await websocket.accept()
    clients.setdefault(username, []).append(websocket)

    # Start the TikTok listener task if it's not already running
    if username not in listener_tasks:
        listener_tasks[username] = asyncio.create_task(_run_tiktok_listener(username))

    try:
        # Keep the connection open; clients send no data in this simple implementation
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        # Remove the WebSocket from our client list
        if username in clients:
            try:
                clients[username].remove(websocket)
            except ValueError:
                pass
            # If no more clients are connected, cancel the listener task
            if not clients[username]:
                task = listener_tasks.pop(username, None)
                if task is not None:
                    task.cancel()


async def _run_tiktok_listener(username: str) -> None:
    """Listen to comments on a TikTok live stream and broadcast them.

    This coroutine attempts to connect to the given TikTok username's live
    stream via TikTokLive. When new comments arrive, they are sent to
    all connected WebSocket clients. If an error occurs (e.g. the
    TikTokLive library is not installed or the live stream ends), the
    coroutine exits. When the last client disconnects, cancellation
    propagates through this task.
    """
    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent

        client = TikTokLiveClient(unique_id=username)

        @client.on(CommentEvent)
        async def on_comment(event):  # type: ignore
            message = f"{event.user.nickname}: {event.comment}"
            # Broadcast to all connected clients listening for this username
            for ws in clients.get(username, []):
                try:
                    await ws.send_text(message)
                except Exception:
                    # Ignore errors when sending messages
                    pass

        # Start the TikTok live stream listener. This call blocks until
        # the stream ends or the task is cancelled.
        await client.start()
    except Exception as exc:
        # Log the error. In a real application, use a proper logging
        # framework. Here we simply print to stderr.
        import sys
        print(f"Error in TikTok listener for {username}: {exc}", file=sys.stderr)
