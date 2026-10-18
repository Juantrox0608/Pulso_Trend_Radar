"""Manual, one-shot integration check. This is NOT an automatic test."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import httpx

from radar_backend.clients import CollectorClient, AIClient
from radar_backend.config import Settings
from radar_backend.main import create_app


async def run(args):
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "sample_size": 1,
              "collector_days": 1, "search_id": None, "status": "starting"}
    path = Path(args.report)
    if path.exists():
        raise SystemExit("El informe ya existe; usa otro nombre. No se hizo ninguna solicitud.")
    path.parent.mkdir(parents=True, exist_ok=True)

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    class ObservedCollector(CollectorClient):
        async def wait_for_search(self, search_id):
            report["search_id"] = search_id
            report["status"] = "polling"
            save()
            print("search_id=" + search_id, flush=True)
            result = await super().wait_for_search(search_id)
            report["collector_state"] = result.get("estado")
            report["publications"] = len(result.get("publicaciones", []))
            report["metrics"] = len(result.get("metricas", []))
            save()
            return result

    settings = Settings(_env_file=None, collector_url=args.collector_url,
                        ai_analyze_url=args.ai_url, collector_default_days=1)
    save()
    async with httpx.AsyncClient(follow_redirects=False) as external:
        # Health checks wake free instances without consuming inference quota.
        for url in (str(settings.collector_url).rstrip("/") + "/salud", args.ai_url.rsplit("/", 1)[0] + "/health"):
            try:
                response = await external.get(url, timeout=90)
                print("health_status=" + str(response.status_code), flush=True)
            except httpx.RequestError:
                report["status"] = "health_failed_no_search_created"
                save()
                return 1
            if response.status_code != 200:
                report["status"] = "health_failed_no_search_created"
                save()
                return 1
        app = create_app(settings, ObservedCollector(settings, external), AIClient(settings, external))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-main") as client:
                response = await client.post("/research", json={
                    "question": "Para 30X, analiza esta selección de un video y propone una idea útil de contenido sobre IA. No afirmes crecimiento reciente.",
                    "audience": "Líderes y equipos de Latinoamérica que aplican IA en su trabajo",
                    "filters": {"query": "inteligencia artificial", "platform": "youtube", "country": "CO", "sample_size": 1},
                })
                report["http_status"] = response.status_code
                data = response.json()
                if response.status_code == 200:
                    report["status"] = "passed"
                    report["ranking"] = data["analysis"]["ranking"]
                    report["source_ids"] = [source["id"] for source in data["sources"]]
                    report["findings_count"] = len(data["analysis"]["findings"])
                    report["recommendations_count"] = len(data["analysis"]["recommendations"])
                    report["limitations"] = data["analysis"]["limitations"]
                    report["simulated"] = data["collection"]["simulated"]
                else:
                    report["status"] = "failed"
                    report["error"] = data.get("error")
                save()
                print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
                return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector-url", default="https://radar-recoleccion.onrender.com")
    parser.add_argument("--ai-url", required=True)
    parser.add_argument("--report", required=True)
    sys.exit(asyncio.run(run(parser.parse_args())))
