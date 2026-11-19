"""Sample the public endpoints from a Windows machine outside the PrimeFlow host."""
import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from primeflow_api_monitor import write_state


ENDPOINTS = {"api": "https://api-flow.primexeu.com/health",
             "login": "https://primeflow.primexeu.com/login"}


def probe(name, url):
    started = time.monotonic()
    result = {"url": url, "ok": False}
    try:
        req = Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "PrimeFlow-Availability/1.0"})
        with urlopen(req, timeout=8) as response:
            result["status"] = response.status
            body = response.read(65536)
            valid = (json.loads(body).get("status") == "ok" if name == "api"
                     else b"primeflow" in body.lower() and b"<html" in body.lower())
            result["ok"] = response.status == 200 and response.url == url and valid
    except HTTPError as exc:
        result["status"] = exc.code
        exc.close()
    except (OSError, ValueError, AttributeError) as exc:
        result["error"] = type(exc).__name__
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(args.state_dir / "external.log", maxBytes=4000000,
                                  backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(message)s")
    with ThreadPoolExecutor(max_workers=2) as probes, ThreadPoolExecutor(max_workers=1) as publisher:
        delivery = None
        while True:
            start = time.monotonic()
            at = datetime.now(timezone.utc).isoformat()
            pending = {k: probes.submit(probe, k, url) for k, url in ENDPOINTS.items()}
            sample = {"at": at, "checks": {k: f.result() for k, f in pending.items()}}
            logging.info(json.dumps(sample))
            if delivery is None or delivery.done():
                if delivery and delivery.exception():
                    logging.warning("sample publication failed: %s", type(delivery.exception()).__name__)
                delivery = publisher.submit(write_state, args.publish, sample)
            time.sleep(max(0, 30 - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
