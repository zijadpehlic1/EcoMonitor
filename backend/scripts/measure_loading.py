"""Read-only HTTP timing while independent workers may run. No invented baseline."""
import json
from datetime import datetime, UTC
from pathlib import Path
from statistics import median
from time import perf_counter
import httpx

report = {'measured_at': datetime.now(UTC).isoformat(), 'measurements': [],
          'note': 'Local sequential HTTP timings, 3 repetitions. Background workers may be active; not a load test.'}
with httpx.Client(base_url='http://127.0.0.1:8001/api/v1',timeout=60) as client:
    for city in ('zenica','sarajevo','mostar','banja-luka'):
        stations=client.get('/sensors/stations',params={'location':city}).json()
        station=stations[0]['id'] if stations else None
        for endpoint in ('/dashboard','/history','/forecast/pm25','/forecast/pm25/weather-comparison'):
            params={'location':city}
            if endpoint != '/dashboard':
                params.update(source='sensor',station_id=station) if station else params.update(source='modeled')
            if endpoint=='/history': params.update(hours=24,grouping='hourly',aggregation='average')
            samples=[]
            for _ in range(3):
                start=perf_counter();response=client.get(endpoint,params=params);response.raise_for_status()
                samples.append(round((perf_counter()-start)*1000,2))
            body=response.json()
            report['measurements'].append({'city':city,'endpoint':endpoint,'median_ms':median(samples),
                'samples_ms':samples,'response_bytes':len(response.content),'status':body.get('status')})
report['overall_median_ms']=median(x['median_ms'] for x in report['measurements'])
Path('loading-performance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
