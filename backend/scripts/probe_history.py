"""Small read-only probe of documented/public endpoints; secrets stay in headers."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.core.config import get_settings

async def main():
    s = get_settings()
    async with httpx.AsyncClient(timeout=40) as c:
        if s.openaq_api_key:
            headers = {"X-API-Key": s.openaq_api_key.get_secret_value()}
            metadata = json.loads((Path(__file__).resolve().parents[1] / "source-verification.json").read_text())
            for entry in metadata:
                for station in entry.get("openaq", {}).get("results", []):
                    if station['id'] not in (9598, 6482140, 2656051):
                        continue
                    sensor = next(x for x in station['sensors'] if x['parameter']['name'] in ('pm25', 'pm10'))
                    end = '2024-07-12T00:00:00Z' if station['id'] == 2656051 else '2026-11-04T00:00:00Z'
                    start = '2024-07-11T00:00:00Z' if station['id'] == 2656051 else '2026-11-03T00:00:00Z'
                    r = await c.get(f"{s.openaq_base_url}/sensors/{sensor['id']}/hours", headers=headers,
                                    params={"datetime_from": start, "datetime_to": end, "limit": 2})
                    print(json.dumps({"station": station['id'], "status": r.status_code, "data": r.json()}, ensure_ascii=True))
        for path in ('/robots.txt', '/rest/pubrep/stations'):
            r = await c.get(s.fhmz_air_quality_url + path)
            print(path, r.status_code, json.dumps(r.text[:12000], ensure_ascii=True))

asyncio.run(main())
