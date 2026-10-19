import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text
from app.db import SessionLocal, engine


async def main():
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        projects = (await db.execute(text("""
            SELECT id, title FROM projects WHERE title ILIKE :title
        """), {"title": "%TT%PIM%IMAGE%"})).mappings().all()
        print(json.dumps([dict(row) for row in projects], default=str))
        for project in projects:
            rows = (await db.execute(text("""
                SELECT t.id, t.title, t.phase, t.status, t.start_date, t.due_date,
                       t.daily_products, t.internal_notes, t.dependency_task_id,
                       t.assigned_to, t.completed_at, t.is_active,
                       u.full_name AS assignee,
                       (SELECT string_agg(u2.full_name, ', ') FROM task_assignees ta
                        JOIN users u2 ON u2.id = ta.user_id WHERE ta.task_id = t.id) AS additional_assignees
                FROM tasks t LEFT JOIN users u ON u.id = t.assigned_to
                WHERE t.project_id = :project
                ORDER BY t.created_at, t.id
            """), {"project": project["id"]})).mappings().all()
            selected = [dict(row) for row in rows]
            products = [row for row in selected if row["phase"] == "PRODUCT" and row["is_active"]]
            controls = [row for row in selected if row["phase"] == "CONTROL" and row["is_active"]]
            product_ids = {str(row["id"]) for row in products}
            links = {}
            anomalies = []
            def number(notes, field):
                match = re.search(rf"\b{field}=(\d+)", notes or "")
                return int(match[1]) if match else None
            for index, control in enumerate(controls, 1):
                match = re.search(r"origin_task_id[:=]\s*([a-f0-9-]+)", control["internal_notes"] or "", re.I)
                origin = match[1] if match else None
                links.setdefault(origin, []).append((index, control))
                if origin not in product_ids:
                    anomalies.append({"control": index, "issue": "missing_or_invalid_product", "origin": origin})
                if not control["assigned_to"]:
                    anomalies.append({"control": index, "issue": "no_KO_assignee", "additional_assignees": control["additional_assignees"]})
            pairs = []
            for index, product in enumerate(products, 1):
                linked = links.get(str(product["id"]), [])
                if len(linked) != 1:
                    anomalies.append({"product": index, "issue": "control_count", "count": len(linked)})
                for control_index, control in linked:
                    pairs.append({"product": index, "control": control_index, "title": product["title"],
                                  "product_total": product["daily_products"], "control_total": control["daily_products"],
                                  "product_completed": number(product["internal_notes"], "completed_products"),
                                  "control_completed": number(control["internal_notes"], "completed_products"),
                                  "product_status": product["status"], "control_status": control["status"]})
                    if product["daily_products"] != control["daily_products"]:
                        anomalies.append({"product": index, "control": control_index, "issue": "total_mismatch",
                                          "product_total": product["daily_products"], "control_total": control["daily_products"]})
                    if product["completed_at"] and control["completed_at"] and control["completed_at"] < product["completed_at"]:
                        anomalies.append({"product": index, "control": control_index, "issue": "control_completed_before_product",
                                          "product_completed_at": product["completed_at"], "control_completed_at": control["completed_at"]})
                    if "TOP MAIN IMG" in product["title"]:
                        anomalies.append({"product": index, "control": control_index, "issue": "date_check",
                                          "start_date": control["start_date"], "due_date": control["due_date"],
                                          "production_date": re.findall(r"production_date=([0-9-]+)", control["internal_notes"] or "")})
            print(json.dumps({"project": project["title"], "product_count": len(products), "control_count": len(controls),
                              "pairs": pairs, "checks": anomalies}, default=str, ensure_ascii=False))
        await db.rollback()
    await engine.dispose()


asyncio.run(main())
