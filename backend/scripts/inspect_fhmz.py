"""Repeat the dated two-day public FHMZ connectivity probe used in the audit."""
import asyncio
import json
import httpx

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        root = 'https://zrak.fhmzbih.gov.ba'
        for station in (6, 30):
            r = await client.get(root + '/rest/aqdata/data', params={'station': station, 'pollutant': 379,
                'aqdata_type': 0, 'begin_date': '03.11.2026.', 'end_date': '04.11.2026.'})
            print(json.dumps({'station': station, 'status': r.status_code, 'data': r.text[:10000]}, ensure_ascii=True))

asyncio.run(main())
