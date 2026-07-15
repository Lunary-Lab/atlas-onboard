# tests/e2e/mock_otp_server.py
import http.server
import json
import socketserver

PORT = 8765


class OtpGateHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/v1/verify":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")


with socketserver.TCPServer(("", PORT), OtpGateHandler) as httpd:
    print(f"Serving mock OTP gate at port {PORT}")
    httpd.serve_forever()
