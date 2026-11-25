from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from app.services.primeflow_report_delivery import deliver_report, validate_report_config


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or safely deliver a PrimeFlow 1H report")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--slot", required=True, choices=["10:00", "11:00", "11:50", "14:10", "14:20", "16:00"])
    parser.add_argument("--send", action="store_true", help="Send and verify through Gmail; default is dry-run")
    args = parser.parse_args()
    validate_report_config(require_gmail=args.send, require_api=False)
    run = await deliver_report(args.date, args.slot, send=args.send)
    print(json.dumps({"id": str(run.id), "status": run.status, "subject": run.subject}, ensure_ascii=False))
    if not args.send:
        print(getattr(run, "dry_run_body", ""))


if __name__ == "__main__":
    asyncio.run(main())
