"""
Web terminal: spawns a real shell in a pseudo-terminal and relays bytes
between it and a browser WebSocket. xterm.js on the frontend does all
the VT100/ANSI rendering — the server's job is just to shovel bytes and
handle resize events.

Security notes (read before exposing this publicly):
  - This is full remote code execution as whatever OS user runs the
    process. Treat FM_USERNAME/FM_PASSWORD with the same care as SSH
    credentials, and put this behind HTTPS.
  - The WebSocket handshake carries cookies automatically, which makes
    it vulnerable to cross-site WebSocket hijacking unless the Origin
    header is checked — so we check it below, on top of the normal
    session cookie.
  - Set FM_ENABLE_TERMINAL=false to remove this feature entirely if you
    only want the file browser.
"""
import asyncio
import codecs
import contextlib
import fcntl
import os
import pty
import signal
import struct
import termios
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import SESSION_COOKIE, read_session
from .config import settings

router = APIRouter()


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    with contextlib.suppress(OSError):
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        # Same-origin browser requests to a plain ws:// connection may omit
        # Origin in some setups; be conservative and require it.
        return False
    origin_host = urlparse(origin).netloc
    return origin_host == websocket.headers.get("host")


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    if not settings.ENABLE_TERMINAL:
        await websocket.close(code=1008, reason="Terminal disabled")
        return

    if not _origin_allowed(websocket):
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    session = read_session(websocket.cookies.get(SESSION_COOKIE))
    if session is None:
        await websocket.close(code=1008, reason="Not authenticated")
        return

    await websocket.accept()

    pid, master_fd = pty.fork()
    if pid == 0:
        # --- child process: becomes the shell ---
        os.chdir(str(settings.ROOT_DIR))
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        try:
            os.execvpe(settings.TERMINAL_SHELL, [settings.TERMINAL_SHELL], env)
        except FileNotFoundError:
            os.execvpe("/bin/sh", ["/bin/sh"], env)
        os._exit(1)  # pragma: no cover — unreachable unless exec fails

    # --- parent process: relays bytes ---
    os.set_blocking(master_fd, True)
    loop = asyncio.get_event_loop()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    async def pump_output():
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            text = decoder.decode(data)
            if text:
                try:
                    await websocket.send_json({"type": "output", "data": text})
                except Exception:
                    break
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "exit"})

    output_task = asyncio.create_task(pump_output())

    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "input":
                data = msg.get("data", "")
                if data:
                    with contextlib.suppress(OSError):
                        os.write(master_fd, data.encode("utf-8", errors="replace"))
            elif mtype == "resize":
                rows, cols = int(msg.get("rows", 24)), int(msg.get("cols", 80))
                _set_winsize(master_fd, rows, cols)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        # Any other error (malformed frame, etc.) just ends this
        # connection gracefully — cleanup below still runs.
        pass
    finally:
        output_task.cancel()
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGHUP)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
        with contextlib.suppress(OSError):
            os.close(master_fd)
