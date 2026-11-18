"""Local Windows integration test. Pass a Caddy executable on the command line."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
ENTERED = threading.Event()
RELEASE = threading.Event()


class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            ENTERED.set()
            RELEASE.wait(30)
        body = json.dumps({"status": "ok", "port": self.server.server_port}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def get(port, path="/health"):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=35) as response:
        return int(response.headers["X-PrimeFlow-Origin"]), json.load(response)["port"]


def switch(surface, port):
    # Redirect only the two public verification URLs to the real local gateway.
    script = r"""
. ./deploy/origins.ps1
$ErrorActionPreference = 'Stop'
function Invoke-WebRequest($Uri, [switch]$UseBasicParsing, $TimeoutSec, $ErrorAction) {
    $Uri = "$Uri".Replace('https://primeflow.primexeu.com','http://127.0.0.1:13000').Replace('https://api-flow.primexeu.com','http://127.0.0.1:18080')
    Microsoft.PowerShell.Utility\Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
}
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script + f"Set-PrimeFlowRoute {surface} {port}"],
                   cwd=ROOT.parent, check=True, timeout=45)


def main():
    servers = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PRIMEFLOW_GATEWAY_STATE"] = tmp
        env = dict(os.environ, APPDATA=tmp, XDG_CONFIG_HOME=tmp, XDG_DATA_HOME=tmp)
        for port in (3000, 3301, 8000, 8080):
            server = ThreadingHTTPServer(("127.0.0.1", port), Origin)
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        gateway = subprocess.Popen([sys.argv[1], "run", "--config", str(ROOT / "Caddyfile"), "--adapter", "caddyfile"],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                if gateway.poll() is not None:
                    raise RuntimeError("Test gateway could not bind its ports.")
                try:
                    if get(13000) == (3000, 3000):
                        break
                except OSError:
                    time.sleep(0.1)
            with concurrent.futures.ThreadPoolExecutor() as pool:
                slow = pool.submit(get, 18080, "/slow")
                assert ENTERED.wait(5)
                def sample():
                    for _ in range(150):
                        for listener in (13000, 18080):
                            header, actual = get(listener)
                            assert header == actual
                        time.sleep(0.02)
                samples = pool.submit(sample)
                try:
                    switch("api", 8000)
                    switch("web", 3301)
                    assert get(18080) == (8000, 8000)
                    assert get(13000) == (3301, 3301)
                finally:
                    RELEASE.set()
                assert slow.result() == (8080, 8080)
                switch("web", 3000)
                switch("api", 8080)
                samples.result()
                assert get(18080) == (8080, 8080) and get(13000) == (3000, 3000)
            print("300 successful probes across two origins, in-flight request preserved, rollback verified.")
        finally:
            RELEASE.set()
            gateway.terminate()
            gateway.wait(timeout=10)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
