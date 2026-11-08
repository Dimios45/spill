"""Read-only local top-camera video gallery; no robot or provider access."""

from __future__ import annotations

import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


def inventory(root):
    rows, videos = [], {}
    for run in sorted(root.iterdir(), reverse=True):
        if not run.is_dir() or run.is_symlink():
            continue
        metadata = {}
        try:
            metadata = json.loads((run / "episode.json").read_text())
        except (OSError, ValueError):
            try:
                with (run / "events.jsonl").open() as f:
                    metadata = json.loads(next(f))
            except (OSError, ValueError, StopIteration):
                pass
        clips = []
        for path in sorted((run / "lerobot_v3/videos/observation.images.top").glob("**/*.mp4")):
            if not path.resolve().is_relative_to(root):
                continue
            key = path.relative_to(root).as_posix()
            videos[key] = path
            clips.append(key)
        rows.append(
            (run.name, metadata.get("task") or metadata.get("prompt") or "Task unavailable", clips)
        )
    return rows, videos


def handler(root):
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            route = unquote(urlsplit(self.path).path)
            rows, videos = inventory(root)
            if route == "/":
                cards = []
                for name, task, clips in rows:
                    media = (
                        "".join(
                            f'<p>Video part {i + 1}</p><video controls preload="none" src="/video/{quote(key)}"></video>'
                            for i, key in enumerate(clips)
                        )
                        or "<p>No exported top-camera video yet.</p>"
                    )
                    cards.append(
                        f'<article><h2>{html.escape(name)}</h2><p class="task">{html.escape(str(task))}</p>{media}</article>'
                    )
                body = (
                    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                    "<title>Spill rollout recordings</title><style>body{font:16px system-ui;background:#111827;color:#e5e7eb;max-width:1050px;margin:32px auto;padding:0 20px}"
                    "article{background:#1f2937;padding:20px;margin:20px 0;border-radius:12px}video{width:100%;max-height:65vh}h2{overflow-wrap:anywhere}.task{white-space:pre-wrap}a{color:#93c5fd}</style>"
                    "<h1>Spill · recorded top camera</h1><p>Newest runs first. Refresh to discover newly exported videos. "
                    'Videos show recorded task observations; homing is excluded.</p><a href="/">Refresh recordings</a>'
                    + "".join(cards)
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head:
                    self.wfile.write(body)
                return
            path = (
                videos.get(route.removeprefix("/video/")) if route.startswith("/video/") else None
            )
            if path is None:
                self.send_error(404)
                return
            size = path.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if not match or not any(match.groups()):
                    self.send_error(416)
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
            self.send_response(206 if range_header else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if range_header:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if not head:
                try:
                    with path.open("rb") as f:
                        f.seek(start)
                        remaining = end - start + 1
                        while remaining > 0:
                            data = f.read(min(1024 * 256, remaining))
                            if not data:
                                break
                            self.wfile.write(data)
                            remaining -= len(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return Handler


def serve(run_dir, host="0.0.0.0", port=8085):
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with ThreadingHTTPServer((host, port), handler(root)) as server:
        print(f"Recorded rollout viewer: http://{host}:{port} (read-only)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
