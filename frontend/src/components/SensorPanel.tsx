import { Activity, AlertTriangle, CheckCircle2, ExternalLink, Radio } from 'lucide-react'
import { formatDateTime, formatNumber } from '../locale'
import type { SensorData } from '../types'

const labels: Record<string, string> = {
  pm2_5: 'PM2.5',
  pm10: 'PM10',
  nitrogen_dioxide: 'NO₂',
  sulphur_dioxide: 'SO₂',
  ozone: 'O₃',
}

export function SensorPanel({ sensor, loading }: { sensor: SensorData | null; loading: boolean }) {
  if (loading && !sensor) {
    return <section className="card p-6 text-sm text-slate-500">Provjera fizičkih mjernih stanica…</section>
  }

  if (!sensor?.is_live) {
    return (
      <section className="card flex items-start gap-3 p-5 sm:p-6" aria-label="Status senzorskih mjerenja">
        <AlertTriangle size={20} className="mt-0.5 shrink-0 text-amber-600" />
        <div>
          <p className="font-bold text-slate-800">Nema potvrđenih svježih senzorskih mjerenja</p>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            {sensor?.message ?? 'Lokalni izvor mjerenja trenutno nije dostupan.'} Modelirani podaci ostaju prikazani odvojeno.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className="card overflow-hidden" aria-label="Stvarna mjerenja kvaliteta zraka">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:px-7">
        <div>
          <p className="label">Stvarna mjerenja</p>
          <h2 className="mt-1 font-display text-2xl font-bold">Fizička mjerna stanica · {sensor.station_name}</h2>
        </div>
        <div className="flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-800">
          <Radio size={15} /> Potvrđeno svježe mjerenje
        </div>
      </div>
      <div className="p-5 sm:p-7">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {sensor.measurements.map((item) => (
            <article key={item.pollutant} className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
              <Activity size={17} className="text-moss" />
              <p className="mt-3 text-xs font-bold text-slate-500">{labels[item.pollutant] ?? item.pollutant}</p>
              <p className="mt-1 font-display text-2xl font-extrabold">
                {formatNumber(item.value)} <span className="text-[0.62rem] font-semibold text-slate-400">{item.unit}</span>
              </p>
            </article>
          ))}
        </div>
        <div className="mt-5 flex flex-col gap-3 rounded-2xl bg-slate-50 p-4 text-xs leading-5 text-slate-600 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <span className="inline-flex items-center gap-1.5 font-bold text-emerald-800"><CheckCircle2 size={14} /> Fizička stanica</span>
            <span> · {sensor.latest_measurement_at ? formatDateTime(sensor.latest_measurement_at) : 'vrijeme nije dostupno'} · automatski, nevalidirani podaci</span>
          </div>
          {sensor.source_url && (
            <a href={sensor.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-bold text-moss hover:underline">
              Službeni izvor <ExternalLink size={13} />
            </a>
          )}
        </div>
        <p className="mt-3 text-xs leading-5 text-slate-500">{sensor.disclaimer}</p>
      </div>
    </section>
  )
}
