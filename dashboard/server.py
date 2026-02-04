"""Dashboard HTTP server with API routing.

Usage:
    python dashboard/server.py --db dashboard/data/dashboard.db --port 8080
    python dashboard/server.py --mock --port 8080
"""

import argparse
import json
import mimetypes
import re
import sys
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Allow running as script from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))


class DashboardHandler(SimpleHTTPRequestHandler):
    provider = None
    jsonl_dir = None
    static_dir = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed)
        else:
            self._serve_static(parsed.path)

    def _handle_api(self, parsed):
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        try:
            # --- health ---
            if path == "/api/health":
                data = self.provider.health()

            # --- overview ---
            elif path == "/api/overview":
                data = self.provider.overview(qs)

            # --- tokens ---
            elif path == "/api/tokens":
                data = self.provider.tokens(qs)

            # --- tools ---
            elif path == "/api/tools":
                data = self.provider.tools(qs)

            # --- concurrency ---
            elif path == "/api/concurrency":
                data = self.provider.concurrency(qs)

            # --- summarization ---
            elif path == "/api/summarization":
                data = self.provider.summarization(qs)

            # --- sessions aggregate ---
            elif path == "/api/sessions/aggregate":
                data = self.provider.sessions_aggregate(qs)

            # --- sessions list ---
            elif path == "/api/sessions":
                data = self.provider.sessions(qs)

            # --- session replay ---
            elif re.match(r"^/api/session/([^/]+)/replay$", path):
                m = re.match(r"^/api/session/([^/]+)/replay$", path)
                data = self.provider.session_replay(m.group(1), self.jsonl_dir)

            # --- session detail ---
            elif re.match(r"^/api/session/([^/]+)$", path):
                m = re.match(r"^/api/session/([^/]+)$", path)
                data = self.provider.session_detail(m.group(1))

            # --- compare ---
            elif path == "/api/compare":
                filters_a = {"from": qs.get("from_a", ""), "to": qs.get("to_a", "")}
                filters_b = {"from": qs.get("from_b", ""), "to": qs.get("to_b", "")}
                data = self.provider.compare(filters_a, filters_b)

            # --- activity heatmap ---
            elif path == "/api/activity_heatmap":
                data = self.provider.activity_heatmap(qs)

            # --- latency ---
            elif path == "/api/latency":
                data = self.provider.latency(qs)

            # --- errors ---
            elif path == "/api/errors":
                data = self.provider.errors(qs)

            else:
                self.send_error(404, "Unknown API endpoint")
                return

            self._send_json(data)

        except Exception:
            tb = traceback.format_exc()
            self.log_error("API error: %s", tb)
            self._send_json({"error": str(tb)}, status=500)

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        file_path = Path(self.static_dir) / path.lstrip("/")
        # Prevent directory traversal
        try:
            file_path = file_path.resolve()
            static_resolved = Path(self.static_dir).resolve()
            if not str(file_path).startswith(str(static_resolved)):
                self.send_error(403)
                return
        except (ValueError, OSError):
            self.send_error(400)
            return

        if file_path.exists() and file_path.is_file():
            self._send_file(file_path)
        else:
            self.send_error(404)

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        origin = self.headers.get("Origin", "")
        allowed = origin if origin in ("http://127.0.0.1:8080", "http://localhost:8080") else "http://127.0.0.1:8080"
        self.send_header("Access-Control-Allow-Origin", allowed)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path):
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Quieter logging - only log errors and API calls."""
        pass


def main():
    parser = argparse.ArgumentParser(description="Dashboard server")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--jsonl", help="Path to Claude projects dir for session replay",
                        default=str(Path.home() / ".claude/projects"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mock", action="store_true", help="Use mock data provider")
    args = parser.parse_args()

    if args.mock:
        from dashboard.providers.mock import MockProvider
        DashboardHandler.provider = MockProvider()
        print("Using MockProvider (deterministic seed=42)")
    else:
        if not args.db:
            parser.error("--db is required when not using --mock")
        from dashboard.providers.sqlite import SqliteProvider
        DashboardHandler.provider = SqliteProvider(args.db)
        print(f"Using SqliteProvider: {args.db}")

    DashboardHandler.jsonl_dir = args.jsonl
    DashboardHandler.static_dir = str(Path(__file__).parent / "static")

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
