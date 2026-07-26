#!/usr/bin/env python3
"""CORS-enabled static server for audio fixtures, so a browser page on :3000 can
fetch a fixture WAV and inject it as simulated caller audio during a live test.

Demo-safety note: this exists for TESTING ONLY. Any simulated caller audio shown to
an audience must carry a visible "SIMULATED CALLER — prerecorded" label; see the
simulated-caller spec on sarvam-t5o.

Usage: python3 tools/orchestration/fixture_server.py [port]
Serves: backend/tests/fixtures/
"""

import functools
import http.server
import pathlib
import socketserver
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures"


class CorsHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter output
        sys.stderr.write("fixture-server: " + (fmt % args) + "\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3200
    handler = functools.partial(CorsHandler, directory=str(ROOT))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as srv:
        print(f"serving {ROOT} on http://127.0.0.1:{port} (CORS *)")
        srv.serve_forever()


if __name__ == "__main__":
    main()
