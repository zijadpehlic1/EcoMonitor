"""Read-only provider probe. Never logs credentials or request headers."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.core.config import get_settings


async def main():
    settings = get_settings()
    evidence = []
    cities = {"zenica": (44.2034, 17.9077), "sarajevo": (43.8563, 18.4131),
              "mostar": (43.3438, 17.8078), "banja-luka": (44.7722, 17.1910)}
    async with httpx.AsyncClient(timeout=40) as client:
        if settings.openaq_api_key:
            headers = {"X-API-Key": settings.openaq_api_key.get_secret_value()}
            for city, coords in cities.items():
                try:
                    response = await client.get(f"{settings.openaq_base_url}/locations", headers=headers,
                        params={"coordinates": f"{coords[0]},{coords[1]}", "radius": 25000, "limit": 100})
                    print(json.dumps({"city": city, "http_status": response.status_code}))
                    if response.is_success:
                        evidence.append({"city": city, "openaq": response.json()})
                        for item in response.json().get("results", []):
                            print(json.dumps({k: item.get(k) for k in (
                                "id", "name", "isMonitor", "datetimeFirst", "datetimeLast")}, ensure_ascii=True))
                except Exception as exc:
                    print(json.dumps({"city": city, "error": type(exc).__name__}))
        else:
            print('OpenAQ credential unavailable')
        for station in (6, 3, 30):
            try:
                response = await client.get(f"{settings.fhmz_air_quality_url}/rest/aqdata/one/{station}")
                evidence.append({"fhmz_station": station, "http_status": response.status_code,
                                 "data": response.json() if response.is_success else None})
                print(json.dumps({"fhmz_station": station, "http_status": response.status_code,
                                  "hourly": [r for r in response.json().get("data", []) if r[2] == "Satni izvorni podaci"] if response.is_success else None}, ensure_ascii=True))
            except Exception as exc:
                print(json.dumps({"fhmz_station": station, "error": type(exc).__name__}))
    target = Path(__file__).resolve().parents[1] / "source-verification.json"
    target.write_text(json.dumps(evidence, ensure_ascii=True, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
