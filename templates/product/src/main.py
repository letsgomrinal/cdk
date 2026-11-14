"""Single entrypoint; the first arg picks the workload (set via args in deploy/main.tf)."""
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


def main(argv):
    mode = argv[1] if len(argv) > 1 else "serve"
    if mode == "serve":
        HTTPServer(("", int(os.environ.get("PORT", "8080"))), Health).serve_forever()
    else:
        print(f"running {' '.join(argv[1:])}")


if __name__ == "__main__":
    main(sys.argv)
