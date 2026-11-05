import { CloudRain, CloudSun, Droplets, Thermometer, Wind } from 'lucide-react'
import { formatDateTime, formatNumber } from '../locale'
import type { WeatherData } from '../types'

type Props = {
  weather: WeatherData | null
  loading: boolean
  city: string
}

const value = (number: number | null | undefined, unit: string) =>
  number == null ? '—' : `${formatNumber(number)} ${unit}`

export function WeatherPanel({ weather, loading, city }: Props) {
  const latest = weather?.latest
  const daily = weather?.daily
  const next = weather?.forecast[0]

  return (
    <section className="card overflow-hidden" aria-label="Vremenski podaci">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:px-7">
        <div>
          <p className="label">Meteorološki podaci</p>
          <h2 className="mt-1 font-display text-2xl font-bold">Vrijeme: {weather?.location.name ?? city}</h2>
        </div>
        <div className="flex items-center gap-2 rounded-full bg-sky-50 px-3 py-2 text-xs font-bold text-sky-800">
          <CloudSun size={15} /> Modelirani podaci
        </div>
      </div>

      {loading && !weather ? (
        <div className="p-7 text-sm text-slate-500">Učitavanje vremenskih podataka…</div>
      ) : !latest && !daily ? (
        <div className="p-7 text-sm text-slate-500">
          Vremenski podaci još nisu dostupni. Pokušajte pokrenuti osvježavanje.
        </div>
      ) : (
        <div className="grid gap-0 lg:grid-cols-[1fr_1.25fr]">
          <div className="border-b border-slate-100 p-5 sm:p-7 lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Posljednji dostupni uslovi</p>
              <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[0.65rem] font-bold text-emerald-800">modelirano</span>
            </div>
            <div className="mt-5 flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-50 text-sky-700"><Thermometer size={27} /></div>
              <div>
                <p className="font-display text-4xl font-extrabold">{value(latest?.temperature_2m, '°C')}</p>
                <p className="mt-1 text-xs text-slate-500">{latest ? formatDateTime(latest.measured_at) : 'Vrijeme nije dostupno'}</p>
                {latest && Date.now() - new Date(latest.measured_at).getTime() > 3 * 3600_000 && <p className="mt-1 text-xs text-amber-700">Podaci su zastarjeli.</p>}
              </div>
            </div>
            <div className="mt-6 grid grid-cols-3 gap-3">
              <WeatherValue icon={Wind} label="Vjetar" value={value(latest?.wind_speed_10m, 'km/h')} />
              <WeatherValue icon={Droplets} label="Vlažnost" value={value(latest?.relative_humidity_2m, '%')} />
              <WeatherValue icon={CloudRain} label="Padavine" value={value(latest?.precipitation, 'mm')} />
            </div>
          </div>

          <div className="p-5 sm:p-7">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Dnevna prognoza temperature</p>
              <span className="rounded-full bg-violet-50 px-2.5 py-1 text-[0.65rem] font-bold text-violet-800">prognoza</span>
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3">
              <TemperatureTile label="Prosječna" value={value(daily?.temperature_mean, '°C')} />
              <TemperatureTile label="Najniža" value={value(daily?.temperature_min, '°C')} />
              <TemperatureTile label="Najviša" value={value(daily?.temperature_max, '°C')} />
            </div>
            <div className="mt-5 rounded-2xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">
              <strong className="text-slate-800">Buduća prognoza:</strong>{' '}
              {next
                ? `${formatDateTime(next.measured_at)} · ${value(next.temperature_2m, '°C')}, vjetar ${value(next.wind_speed_10m, 'km/h')}, vlažnost ${value(next.relative_humidity_2m, '%')}.`
                : 'Naredni sat još nije dostupan.'}
            </div>
            <p className="mt-4 text-xs leading-5 text-slate-500">
              Izvor: {weather?.source.name ?? 'Open-Meteo'}. Modelirani podaci i prognoze nisu mjerenja lokalne meteorološke stanice.
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

function WeatherValue({ icon: Icon, label, value }: { icon: typeof Wind; label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-slate-50 p-3">
      <Icon size={16} className="text-moss" />
      <p className="mt-2 text-[0.65rem] font-semibold text-slate-400">{label}</p>
      <p className="mt-0.5 text-xs font-bold text-slate-700">{value}</p>
    </div>
  )
}

function TemperatureTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-100 p-4 text-center">
      <p className="text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-2 font-display text-xl font-extrabold text-slate-800">{value}</p>
    </div>
  )
}
