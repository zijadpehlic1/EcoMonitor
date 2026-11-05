"""Read-only local REST checks and observed response sizes/latencies."""
import json
from pathlib import Path
from time import perf_counter
import httpx

results = []
with httpx.Client(base_url='http://127.0.0.1:8001/api/v1', timeout=120) as client:
    for city in ('zenica', 'sarajevo', 'mostar', 'banja-luka'):
        stations = client.get('/sensors/stations', params={'location': city}).json()
        for endpoint in ('/dashboard', '/weather', '/sensors/current'):
            started = perf_counter()
            response = client.get(endpoint, params={'location': city})
            response.raise_for_status()
            data = response.json()
            assert data['location']['slug'] == city
            results.append({'city': city, 'endpoint': endpoint, 'status': response.status_code,
                'elapsed_ms': round((perf_counter()-started)*1000, 2), 'bytes': len(response.content),
                'sensor_status': data.get('status'), 'is_live': data.get('is_live')})
        for source in ('modeled', 'sensor'):
            station = stations[0]['id'] if source == 'sensor' and stations else None
            if source == 'sensor' and not station:
                continue
            for grouping in ('hourly', 'daily'):
                params = {'location': city, 'hours': 2160, 'grouping': grouping, 'aggregation': 'maximum', 'source': source}
                if station:
                    params['station_id'] = station
                started = perf_counter()
                response = client.get('/history', params=params)
                response.raise_for_status()
                data = response.json()
                assert data['pollution_source']['type'] == source
                assert data['location']['slug'] == city
                assert all(p['sample_counts']['pm2_5'] <= p['expected_samples'] for p in data['points'])
                results.append({'city': city, 'endpoint': '/history', 'source': source, 'grouping': grouping,
                    'status': response.status_code, 'elapsed_ms': round((perf_counter()-started)*1000, 2),
                    'bytes': len(response.content), 'points': len(data['points']),
                    'pm25_available_hours': sum(p['sample_counts']['pm2_5'] for p in data['points'])})
    response = client.get('/history', params={'location': 'mostar', 'source': 'sensor', 'station_id': 1})
    assert response.status_code == 422
    results.append({'endpoint': '/history wrong city/station', 'status': response.status_code})
Path('audit-api-smoke.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps({'checks': len(results), 'all_assertions_passed': True, 'results': results}))
