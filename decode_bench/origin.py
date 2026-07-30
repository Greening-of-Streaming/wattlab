#!/usr/bin/env python3
"""
origin.py — Range-correct clip origin for the decode rig (port 8123).

Replaces the ad-hoc `python3 -m http.server` whose ignored Range requests
broke ffmpeg-over-HTTP (July's media3 over-fetch suspect) and 500'd the
Apple TV's AirPlay player (2026-07-30). Serves the decode-bench streams
tree (incl. _uploads/) with correct 206/Content-Range semantics, plus a
/status endpoint with per-request byte counters — the delivery-side truth
the July report had to scrape from TCP counters.

TARGET ARCHITECTURE (owner directive, 2026-07-30): serving streams from
GoS1 is a PRECIOUS process — when a measured delivery run is active, the
origin gets the same treatment as an encode job: focus mode, stable-idle
guard before, energy envelope after (see CR-072). This phase-1 server is
deliberately a single dedicated process with no system-nginx coupling so
that wrapper can own it: OWL will be able to start/stop it inside a
measured window and attribute its energy. The /status counters (bytes,
requests, ranged, active) are the attribution seed.

Run:  python3 origin.py [port]        (default 8123)
"""
import json
import os
import re
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/srv/data/owl/decode-bench/streams"

_stats = {"started_epoch": round(time.time(), 1), "requests": 0,
          "bytes_sent": 0, "ranged_requests": 0, "active": 0}
_lock = threading.Lock()


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "owl-origin/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):   # quiet by design; truth via /status
        pass

    def _send_file_head(self, path, size, start, end, status):
        self.send_response(status)
        self.send_header("Content-Type",
                         self.guess_type(path) or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

    def _resolve(self):
        path = self.translate_path(self.path.split("?", 1)[0])
        if not os.path.isfile(path):
            return None, 0
        return path, os.path.getsize(path)

    def _parse_range(self, size):
        """Returns (start, end, status) or raises ValueError for 416."""
        rng = self.headers.get("Range")
        if not rng:
            return 0, size - 1, 200
        m = re.match(r"\s*bytes=(\d*)-(\d*)\s*$", rng)
        if not m or (m.group(1) == "" and m.group(2) == ""):
            raise ValueError(rng)
        if m.group(1) == "":                       # suffix: last N bytes
            start = max(0, size - int(m.group(2)))
            end = size - 1
        else:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        if start >= size or end < start:
            raise ValueError(rng)
        return start, min(end, size - 1), 206

    def do_HEAD(self):
        path, size = self._resolve()
        if path is None:
            self.send_error(404)
            return
        try:
            start, end, status = self._parse_range(size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        self._send_file_head(path, size, start, end, status)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/status":
            with _lock:
                body = json.dumps({**_stats,
                                   "uptime_s": round(time.time()
                                                     - _stats["started_epoch"], 1)
                                   }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        path, size = self._resolve()
        if path is None:
            self.send_error(404)
            return
        try:
            start, end, status = self._parse_range(size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        self._send_file_head(path, size, start, end, status)
        sent = 0
        with _lock:
            _stats["active"] += 1
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass                                    # client hung up — normal
        finally:
            with _lock:
                _stats["active"] -= 1
                _stats["requests"] += 1
                _stats["bytes_sent"] += sent
                if status == 206:
                    _stats["ranged_requests"] += 1


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    srv = ThreadingHTTPServer(("0.0.0.0", port), RangeHandler)
    print(f"owl-origin serving {ROOT} on :{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
