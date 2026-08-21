# File Manager

A self-hosted web file manager with an in-browser text editor and a real
web terminal, built on FastAPI. No JS build step — the frontend is plain
HTML/CSS/JS served straight from `static/` and `templates/`.

## Features

- Browse, upload (drag & drop, with progress), download (single files or
  zipped multi-select), rename, move, copy, delete
- In-browser text editor (CodeMirror) with syntax highlighting for common
  languages, image preview for common formats
- Compress to `.zip` / extract `.zip` (zip-slip protected)
- Recursive filename search within a folder
- A real web terminal (xterm.js + a PTY-backed shell over WebSocket),
  including a right-click "Open terminal here" that `cd`s into the
  folder you're browsing
- Session-cookie auth, CSRF protection, brute-force lockout, path
  traversal prevention, and a security-headers middleware by default

## Quick start

```bash
cp .env.example .env          # then edit FM_USERNAME / FM_PASSWORD / FM_SECRET_KEY
export $(cat .env | xargs)    # or set these in your shell / PaaS dashboard
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`, sign in, and you're in `FM_ROOT` (defaults
to `./data`).

## Deploying with your build config

Your build config already matches this project as-is:

```toml
[build]
install = "pip install -r requirements.txt"
build = ""
start = "uvicorn main:app --host 0.0.0.0 --port $PORT"
```

Just make sure to set the environment variables from `.env.example` in
your platform's dashboard (especially `FM_USERNAME`, `FM_PASSWORD`, and
`FM_SECRET_KEY`) before deploying — the defaults are for local testing
only.

## Project layout

```
main.py                 FastAPI app, page routes, middleware wiring
app/config.py            All settings, read from environment variables
app/security.py          safe_join() path-traversal guard, CSRF, security headers, login throttle
app/auth.py               Signed-cookie sessions, /api/login, /api/logout
app/files.py               File manager REST API (list/upload/download/edit/move/copy/zip/search)
app/terminal.py            PTY web terminal over WebSocket
templates/login.html       Sign-in page
templates/index.html       App shell
static/style.css            Dark, terminal-inspired UI theme
static/app.js                 All frontend logic (no build step, no framework)
```

## Security notes — please read before exposing this publicly

This tool gives whoever logs in full read/write access to `FM_ROOT`, and
(if enabled) a real shell — that's the point, but it also means:

- **Set a strong `FM_PASSWORD` and a random `FM_SECRET_KEY`.** The
  defaults in `config.py` are only there so the app runs out of the box
  locally.
- **Always run this behind HTTPS in production.** Session cookies are
  `HttpOnly` + `Secure` by default (`FM_COOKIE_SECURE=true`), so they
  won't even be sent over plain HTTP once deployed.
- **Think about who can reach this.** If you don't need the terminal,
  set `FM_ENABLE_TERMINAL=false`. Consider putting the whole app behind
  your platform's IP allowlist, a VPN, or HTTP basic auth at the proxy
  layer as a second layer, since this is single-factor auth.
- The brute-force lockout is keyed by client IP and stored in memory —
  fine for a single instance/worker. If you deploy multiple replicas or
  workers behind a load balancer, each one tracks lockouts separately
  (and if your PaaS proxies all requests from one internal IP, every
  client will share a lockout bucket). Swap in Redis if that matters
  for your setup.
- Path traversal is blocked centrally in `safe_join()` — every route
  that touches the filesystem goes through it. If you extend the API,
  route new file paths through `safe_join()` too rather than joining
  paths by hand.
- The web terminal endpoint checks the `Origin` header against `Host`
  to prevent cross-site WebSocket hijacking, on top of the normal
  session cookie.

## Notes

- The web terminal uses `pty.fork()`, which is Linux/macOS only (no
  Windows support) — fine for typical container deployments.
- The in-browser editor caps files at 5MB (`TEXT_EDIT_MAX_BYTES` in
  `app/files.py`); larger files can still be downloaded normally.
- `/docs` and `/redoc` are disabled by default (`docs_url=None` in
  `main.py`) since every route requires auth anyway — re-enable them
  locally if you want to explore the API interactively.
