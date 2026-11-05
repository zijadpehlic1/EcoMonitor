import { BrainCircuit, CheckCircle2, DatabaseZap, TriangleAlert } from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ForecastData } from '../types'
import { formatDate, formatDateTime, formatInteger, formatNumber } from '../locale'

type Props = {
  forecast: ForecastData | null
  loading: boolean
}

export function ForecastPanel({ forecast, loading }: Props) {
  if ((loading && !forecast) || forecast?.status === 'pending') {
    return (
      <section className="card flex min-h-[170px] items-center gap-4 p-6 sm:p-7" role="status" aria-live="polite">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-violet-50 text-violet-700">
          <BrainCircuit size={21} className="animate-pulse" />
        </div>
        <div>
          <p className="label">Mašinsko učenje</p>
          <h2 className="mt-1 font-display text-xl font-bold">Izračunavanje 24-satne PM2.5 prognoze</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Izračun se izvršava u pozadini i može potrajati. Historijski grafikon i ostali podaci ostaju dostupni.
          </p>
        </div>
      </section>
    )
  }

  if (!forecast || !forecast.metrics) {
    return (
      <section className="card flex min-h-[320px] flex-col justify-between p-6 sm:p-7">
        <div>
          <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-amber-50 text-amber-700">
            <TriangleAlert size={21} />
          </div>
          <p className="label">Mašinsko učenje</p>
          <h2 className="mt-2 font-display text-2xl font-bold">Prognoza čeka historijske podatke</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-600">
            {insufficientDataMessage(forecast)}
          </p>
          {forecast && <p className="mt-3 text-xs text-slate-500">{forecast.provenance}</p>}
        </div>
        <div className="mt-8 flex items-center gap-3 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
          <DatabaseZap size={19} className="shrink-0 text-moss" />
          EcoMonitor nikada ne popunjava nedostajuće historijske podatke sintetičkim mjerenjima.
        </div>
      </section>
    )
  }

  const { metrics } = forecast
  const chartData = forecast.forecast.map((point) => ({
    ...point,
    label: formatDateTime(point.timestamp),
  }))

  return (
    <section className="card overflow-hidden">
      <p className="px-6 pt-4 text-xs text-slate-500">Izračunato: {formatDateTime(forecast.generated_at)}{forecast.computation_status === 'running' || forecast.computation_status === 'queued' ? ' · Provjera novog rezultata u pozadini.' : ''}</p>
      <div className="flex flex-col gap-5 border-b border-slate-100 p-6 sm:flex-row sm:items-start sm:justify-between sm:p-7">
        <div>
          <div className="flex items-center gap-2 text-moss">
            <BrainCircuit size={18} />
            <p className="label !text-moss">24-satna ML prognoza</p>
          </div>
          <h2 className="mt-2 font-display text-2xl font-bold">Prognoza PM2.5</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Evaluacijski model je obučen na početnih 80% vremenske serije. Rezultati su izračunati pomoću nepreklapajućih rekurzivnih prognoza od 24 koraka u završnih 20%, bez ponovnog obučavanja tokom evaluacije.
            {' '}Prikazani su samo preostali budući sati horizonta od 24 sata, računatog od posljednjeg mjerenja.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 rounded-full bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800">
          <CheckCircle2 size={15} /> Model evaluiran
        </div>
      </div>

      <div className="grid lg:grid-cols-[1.45fr_.55fr]">
        <div className="border-b border-slate-100 p-5 sm:p-7 lg:border-b-0 lg:border-r">
          <div className="mb-4 flex items-baseline justify-between">
            <span className="text-sm font-semibold text-slate-700">Prognozirana koncentracija</span>
            <span className="text-xs text-slate-500">μg/m³ · nije stvarno mjerenje</span>
          </div>
          <div className="h-[260px]">
            {!chartData.length ? <p className="flex h-full items-center justify-center text-sm text-slate-500">Evaluacija je dostupna. Nova prognoza zahtijeva svježa mjerenja i neprekidan posljednji 24-satni niz.</p> :
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7cb64c" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#7cb64c" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#e7ece8" strokeDasharray="4 5" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#718078' }} minTickGap={28} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: '#718078' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(value) => [`${formatNumber(Number(value))} μg/m³`, 'Prognozirani PM2.5']} contentStyle={{ border: 0, borderRadius: 14 }} />
                <Area type="monotone" dataKey="predicted_pm2_5" stroke="#397253" strokeWidth={3} fill="url(#forecastFill)" />
              </AreaChart>
            </ResponsiveContainer>}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-px bg-slate-100 lg:grid-cols-1">
          <Metric label="Prosječna apsolutna greška (MAE)" value={metrics.mae} unit="μg/m³" />
          <Metric label="Korijen srednje kvadratne greške (RMSE)" value={metrics.rmse} unit="μg/m³" />
          <Metric label="MAE baznog modela" value={metrics.baseline_mae} unit="μg/m³" />
          <Metric
            label="Poboljšanje prema perzistenciji"
            value={metrics.improvement_over_baseline_percent}
            unit="%"
            positive={metrics.improvement_over_baseline_percent > 0}
          />
        </div>
      </div>
      <div className="border-t border-slate-100 bg-slate-50/70 px-6 py-4 text-xs leading-5 text-slate-500">
        {forecast.provenance} Prognoza nije stvarno mjerenje. Evaluacija: {formatInteger(metrics.evaluation_origins)} nepreklapajućih polazišta od {formatInteger(metrics.evaluation_horizon_hours)} sata, {formatInteger(metrics.test_samples)} prognoziranih sati, {formatDate(metrics.test_start)}–{formatDate(metrics.test_end)}.
      </div>
    </section>
  )
}

function Metric({ label, value, unit, positive }: { label: string; value: number; unit: string; positive?: boolean }) {
  return (
    <div className="bg-white p-5 sm:p-6">
      <p className="label">{label}</p>
      <p className={`mt-2 font-display text-2xl font-bold ${positive ? 'text-emerald-700' : 'text-ink'}`}>
        {formatNumber(value)}<span className="ml-1 text-xs font-semibold text-slate-400">{unit}</span>
      </p>
    </div>
  )
}

function insufficientDataMessage(forecast: ForecastData | null): string {
  if (!forecast) return 'Usluga za prognozu trenutno nije dostupna.'
  if (forecast.trained_samples < 24 * 14) {
    return `Za obuku modela potrebne su najmanje 336 satne vrijednosti PM2.5. Trenutno je dostupno ${formatInteger(forecast.trained_samples)}.`
  }
  return 'Nema dovoljno neprekidnih satnih podataka za pouzdanu hronološku obuku i evaluaciju prognoze.'
}

