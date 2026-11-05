"""Measure persisted reuse on real local data; optional forecast-cache invalidation only."""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import select
from app.core.database import Base,SessionLocal,engine
from app.models import Location,SensorStation,ModelResult,BackgroundJob
from app.services.jobs import model_key
from app.services.air_quality import utc_now,aware_utc
from app.worker import calculate

parser=argparse.ArgumentParser()
parser.add_argument('--city',default='mostar')
parser.add_argument('--regenerate',action='store_true',help='Invalidate only forecast response identity; preserve models/evaluations/measurements.')
args=parser.parse_args()
Base.metadata.create_all(engine)
fit_calls=0
original_fit=RandomForestRegressor.fit
def counted_fit(self,*args,**kwargs):
    global fit_calls
    fit_calls+=1
    return original_fit(self,*args,**kwargs)
RandomForestRegressor.fit=counted_fit
results=[]
for model in ('base','weather'):
    with SessionLocal() as db:
        city=db.scalar(select(Location).where(Location.slug==args.city))
        station=db.scalar(select(SensorStation).where(SensorStation.location_id==city.id))
        key=model_key(city.slug,'sensor',station.id,model,24)
        job=db.get(BackgroundJob,key)
        if job and job.status=='running' and job.lease_until and aware_utc(job.lease_until)>utc_now():
            raise SystemExit('Model is currently running; retry after the worker finishes.')
        result=db.get(ModelResult,key)
        if args.regenerate and result:
            result.input_version='explicit-forecast-cache-test';db.commit()
        params=dict(city=city.slug,source='sensor',station_id=station.id,model=model,horizon=24)
    start=perf_counter();before=fit_calls
    result=calculate(params)
    results.append(dict(model=model,elapsed_ms=round((perf_counter()-start)*1000,2),fit_calls=fit_calls-before,**result))
output={'city':args.city,'forecast_cache_invalidated':args.regenerate,'results':results}
path=Path(f'model-reuse-{"regenerate" if args.regenerate else "restart"}.json')
path.write_text(json.dumps(output,indent=2),encoding='utf-8')
print(json.dumps(output))
