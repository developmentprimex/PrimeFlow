"""Keep ten-second Caddy traffic samples for the two PrimeFlow origins."""
import json
import logging
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import urlopen


def main():
    logger = logging.getLogger("traffic")
    logger.setLevel(logging.INFO)
    destination = Path(__file__).resolve().parent / "state" / "traffic.log"
    logger.addHandler(RotatingFileHandler(destination, maxBytes=8_000_000, backupCount=4))
    start = time.monotonic()
    for index in range(6):
        time.sleep(max(0, start + index * 10 - time.monotonic()))
        record = {"utc": datetime.now(timezone.utc).isoformat()}
        try:
            with urlopen("http://127.0.0.1:19019/metrics", timeout=3) as response:
                lines = response.read().decode().splitlines()
            record["metrics"] = {
                key: float(value) for line in lines
                if line.startswith(("caddy_http_requests_", "caddy_http_request_duration_seconds_"))
                and 'handler="subroute"' in line
                and ("_bucket{" not in line or 'le="1"' in line)
                for key, value in [line.rsplit(" ", 1)]
            }
            if not record["metrics"]:
                record["error"] = "No origin metrics"
        except (OSError, ValueError) as exc:
            record["error"] = type(exc).__name__
        logger.info(json.dumps(record, separators=(",", ":")))


if __name__ == "__main__":
    main()
