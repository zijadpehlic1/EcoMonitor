import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Check,
  CloudSun,
  Database,
  Droplets,
  ExternalLink,
  Gauge,
  Info,
  Leaf,
  MapPin,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Wind,
  X,
} from 'lucide-react'
import { api } from './api'
import { aqiBand } from './aqi'
import { AirQualityChart, historyControlLabels } from './components/AirQualityChart'
import { ForecastPanel } from './components/ForecastPanel'
import { LoadingState } from './components/LoadingState'
import { SensorPanel } from './components/SensorPanel'
import { WeatherModelPanel } from './components/WeatherModelPanel'
import { WeatherPanel } from './components/WeatherPanel'
import { formatDateTime, formatInteger, formatNumber } from './locale'
import type {
  DashboardData,
  ForecastData,
  HistoricalData,
  HistoryAggregation,
  HistoryGrouping,
  Location,
  Reading,
  SensorData,
  SensorStation,
  WeatherData,
  WeatherModelComparison,
} from './types'

const ranges = [
  { label: '24 h', hours: 24 },
  { label: '7 d', hours: 24 * 7 },
  { label: '30 d', hours: 24 * 30 },
  { label: '90 d', hours: 24 * 90 },
]

const pollutantMeta = [
  { key: 'pm2_5', label: 'PM2.5', detail: 'Fine čestice', icon: Sparkles, accent: 'bg-lime/20 text-moss' },
  { key: 'pm10', label: 'PM10', detail: 'Grube čestice', icon: Wind, accent: 'bg-orange-50 text-orange-700' },
  { key: 'nitrogen_dioxide', label: 'NO₂', detail: 'Gas iz sagorijevanja', icon: CloudSun, accent: 'bg-violet-50 text-violet-700' },
  { key: 'sulphur_dioxide', label: 'SO₂', detail: 'Industrijski gas', icon: Droplets, accent: 'bg-sky-50 text-sky-700' },
] as const

const formatUpdated = (value: string | null) => {
  if (!value) return 'Još nije sinhronizirano'
  return formatDateTime(value)
}

export default function App() {
  const [location, setLocation] = useState('zenica')
  // Remount city-scoped state: late requests can never populate another city's UI.
  return <CityDashboard key={location} location={location} setLocation={setLocation} />
}

function CityDashboard({ location, setLocation }: { location: string; setLocation: (value: string) => void }) {
  const [locations, setLocations] = useState<Location[]>([])
  const [source, setSource] = useState<'sensor' | 'modeled'>('sensor')
  const [stations, setStations] = useState<SensorStation[]>([])
  const [stationId, setStationId] = useState<number | undefined>()
  const [hours, setHours] = useState(24)
  const [historyGrouping, setHistoryGrouping] = useState<HistoryGrouping>('hourly')
  const [historyAggregation, setHistoryAggregation] = useState<HistoryAggregation>('average')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [history, setHistory] = useState<HistoricalData | null>(null)
  const [forecast, setForecast] = useState<ForecastData | null>(null)
  const [weather, setWeather] = useState<WeatherData | null>(null)
  const [weatherComparison, setWeatherComparison] = useState<WeatherModelComparison | null>(null)
  const [sensor, setSensor] = useState<SensorData | null>(null)
  const [loading, setLoading] = useState(true)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [forecastLoading, setForecastLoading] = useState(true)
  const [weatherLoading, setWeatherLoading] = useState(true)
  const [comparisonLoading, setComparisonLoading] = useState(true)
  const [sensorLoading, setSensorLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const datasetKey = `${source}:${stationId}`
  const currentDataset = useRef(datasetKey)
  currentDataset.current = datasetKey
  const historyKey = `${datasetKey}:${hours}:${historyGrouping}:${historyAggregation}`
  const currentHistory = useRef(historyKey)
  currentHistory.current = historyKey
  const datasetLabel = source === 'modeled' ? 'Modelirani podaci: CAMS / Open-Meteo'
    : `Stvarna mjerenja: ${stations.find(s => s.id === stationId)?.name ?? 'nema odabrane stanice'}`

  const loadDashboard = useCallback(async (showLoader = true) => {
    if (showLoader) setLoading(true)
    setError(null)
    try {
      const result = await api.dashboard(location, 24)
      setDashboard(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nadzornu ploču nije moguće učitati.')
    } finally {
      setLoading(false)
    }
  }, [location])

  const loadHistory = useCallback(async (showLoader = true) => {
    if (source === 'sensor' && !stationId) {
      setHistory(null); setHistoryLoading(false); setHistoryError('Nema pohranjene mjerne stanice za ovaj grad.'); return
    }
    if (showLoader) setHistoryLoading(true)
    setHistoryError(null)
    try {
      const result = await api.history(location, hours, historyGrouping, historyAggregation, source, stationId)
      if (currentHistory.current === historyKey) setHistory(result)
    } catch (err) {
      if (currentHistory.current !== historyKey) return
      setHistory(null)
      setHistoryError(err instanceof Error ? err.message : 'Historijske podatke nije moguće učitati.')
    } finally {
      if (currentHistory.current === historyKey) setHistoryLoading(false)
    }
  }, [historyAggregation, historyGrouping, hours, location, source, stationId, historyKey])

  const loadForecast = useCallback(async () => {
    if (source === 'sensor' && !stationId) { setForecast(null); setForecastLoading(false); return }
    setForecastLoading(true)
    try {
      const result = await api.forecast(location, 24, source, stationId)
      if (currentDataset.current === datasetKey) setForecast(result)
    } catch {
      if (currentDataset.current === datasetKey) setForecast(null)
    } finally {
      if (currentDataset.current === datasetKey) setForecastLoading(false)
    }
  }, [location, source, stationId, datasetKey])

  const loadWeather = useCallback(async (showLoader = true) => {
    if (showLoader) setWeatherLoading(true)
    try {
      setWeather(await api.weather(location))
    } catch {
      setWeather(null)
    } finally {
      setWeatherLoading(false)
    }
  }, [location])

  const loadWeatherComparison = useCallback(async () => {
    if (source === 'sensor' && !stationId) { setWeatherComparison(null); setComparisonLoading(false); return }
    setComparisonLoading(true)
    try {
      const result = await api.weatherComparison(location, 24, source, stationId)
      if (currentDataset.current === datasetKey) setWeatherComparison(result)
    } catch {
      if (currentDataset.current === datasetKey) setWeatherComparison(null)
    } finally {
      if (currentDataset.current === datasetKey) setComparisonLoading(false)
    }
  }, [location, source, stationId, datasetKey])

  const loadSensor = useCallback(async (allowRefresh = true) => {
    setSensorLoading(true)
    try {
      let result = await api.sensors(location)
      if (allowRefresh && result.status !== 'live') {
        await api.refreshSensors(location, false)
        result = await api.sensors(location)
      }
      setSensor(result)
      const available = await api.stations(location)
      setStations(available)
      setStationId(previous => previous ?? available[0]?.id)
    } catch {
      setSensor(null)
    } finally {
      setSensorLoading(false)
    }
  }, [location])

  useEffect(() => {
    api.locations().then(setLocations).catch(() => setLocations([]))
  }, [])

  useEffect(() => {
    void loadDashboard()
  }, [loadDashboard])

  useEffect(() => {
    setHistory(null)
    void loadHistory()
  }, [loadHistory])

  useEffect(() => {
    setForecast(null)
    void loadForecast()
  }, [loadForecast])

  useEffect(() => {
    void loadWeather()
  }, [loadWeather])

  useEffect(() => {
    setWeatherComparison(null)
    void loadWeatherComparison()
  }, [loadWeatherComparison])

  useEffect(() => {
    void loadSensor()
  }, [loadSensor])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadDashboard(false)
      void loadHistory(false)
      void loadWeather(false)
      void loadSensor(false)
      void loadForecast()
      void loadWeatherComparison()
    }, 15 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [loadDashboard, loadHistory, loadSensor, loadWeather, loadForecast, loadWeatherComparison])

  const refresh = async () => {
    setRefreshing(true)
    setError(null)
    try {
      const [airResult, weatherResult, sensorResult] = await Promise.allSettled([
        api.refresh(location, true),
        api.refreshWeather(location, true),
        api.refreshSensors(location, true),
      ])
      if (airResult.status === 'rejected' && weatherResult.status === 'rejected' && sensorResult.status === 'rejected') {
        throw new Error('Sinhronizacija podataka nije uspjela.')
      }
      setNotice(
        [airResult, weatherResult, sensorResult].every(result => result.status === 'fulfilled' && ['success', 'cached'].includes(result.value.status))
          ? 'Podaci o kvalitetu zraka, mjernim stanicama i vremenu su sinhronizirani.'
          : 'Dio podataka je sinhroniziran; jedan izvor trenutno nije dostupan.',
      )
      await Promise.all([loadDashboard(false), loadHistory(false), loadForecast(), loadWeather(false), loadWeatherComparison(), loadSensor(false)])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Osvježavanje podataka nije uspjelo.')
    } finally {
      setRefreshing(false)
    }
  }

  const latest = dashboard?.latest ?? null
  const fresh = latest && Date.now() - new Date(latest.measured_at).getTime() <= 3 * 3600_000
  const currentAqi = fresh ? latest?.european_aqi : null
  const band = aqiBand(currentAqi)
  const aqiKnown = band.label !== 'Nedostupno'
  const averages = useMemo(() => {
    if (!history?.points.length) return null
    const valid = history.points.map((item) => item.pm2_5).filter((value): value is number => value != null)
    return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null
  }, [history])

  if (loading && !dashboard) return <LoadingState />

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-moss text-lime shadow-lg shadow-emerald-950/10">
              <Leaf size={23} strokeWidth={2.4} />
            </div>
            <div>
              <div className="font-display text-lg font-extrabold tracking-tight">EcoMonitor</div>
              <div className="text-[0.65rem] font-semibold uppercase tracking-[0.15em] text-slate-400">Inteligentno praćenje okoliša</div>
            </div>
          </div>

          <div className="flex flex-1 items-center justify-end gap-2 sm:flex-none">
            <div className="hidden items-center gap-2 rounded-full bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 sm:flex">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> {sensor?.is_live ? 'Stvarna mjerenja dostupna' : 'Modelirani podaci'}
            </div>
            <label className="relative flex items-center">
              <MapPin size={16} className="pointer-events-none absolute left-3 text-slate-500" />
              <select
                aria-label="Lokacija praćenja"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                className="h-10 min-w-[145px] appearance-none rounded-xl border border-slate-200 bg-white pl-9 pr-8 text-sm font-semibold text-slate-700"
              >
                {(locations.length ? locations : [{ slug: 'zenica', name: 'Zenica', country: 'Bosna i Hercegovina' }]).map((item) => (
                  <option key={item.slug} value={item.slug}>{item.name}, BA</option>
                ))}
              </select>
            </label>
            <button
              onClick={refresh}
              disabled={refreshing}
              className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 transition hover:border-moss hover:text-moss disabled:opacity-50"
              aria-label="Osvježi podatke o okolišu"
            >
              <RefreshCw size={17} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] space-y-5 px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
        {error && (
          <div className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div className="flex-1"><strong>Problem s povezivanjem na podatke.</strong> {error} Pohranjene vrijednosti ostaju dostupne kada je to moguće.</div>
            <button onClick={() => setError(null)} aria-label="Zatvori poruku o grešci"><X size={17} /></button>
          </div>
        )}
        {notice && (
          <div className="flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">
            <Check size={18} /> <span className="flex-1">{notice}</span>
            <button onClick={() => setNotice(null)} aria-label="Zatvori obavijest"><X size={17} /></button>
          </div>
        )}

        <section className="grid gap-5 xl:grid-cols-[1.35fr_.65fr]">
          <div className="grid-glow relative overflow-hidden rounded-[1.65rem] bg-[#173c2d] p-6 text-white shadow-soft sm:p-8">
            <div className="absolute -bottom-28 -right-20 h-80 w-80 rounded-full border-[44px] border-white/[0.035]" />
            <div className="relative flex h-full flex-col justify-between gap-12">
              <div className="flex flex-wrap items-start justify-between gap-5">
                <div>
                  <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-emerald-100/70">
                    <Activity size={15} /> Trenutno stanje zraka
                  </div>
                  <h1 className="max-w-xl font-display text-3xl font-extrabold leading-tight sm:text-4xl">
                    Kvalitet zraka: <span className="text-lime">{dashboard?.location.name ?? 'Zenica'}</span>, prikazan razumljivo.
                  </h1>
                  <p className="mt-4 max-w-2xl text-sm leading-6 text-emerald-50/70">
                    Satne atmosferske procjene, transparentno porijeklo podataka i PM2.5 prognoza bez curenja podataka — na jednom mjestu.
                  </p>
                </div>
                <span className="rounded-full border border-white/15 bg-white/10 px-3 py-2 text-xs font-semibold backdrop-blur">
                  {latest ? fresh ? 'Podaci dostupni' : 'Podaci su zastarjeli' : 'Čeka se prva sinhronizacija'}
                </span>
              </div>

              <div className="flex flex-col gap-7 sm:flex-row sm:items-end sm:justify-between">
                <div className="flex items-center gap-5">
                  <AqiGauge value={aqiKnown ? currentAqi ?? null : null} color={band.color} />
                  <div>
                    <p className="text-sm text-emerald-50/65">Evropski AQI</p>
                    <p className="mt-1 font-display text-3xl font-extrabold">{band.label}</p>
                    <p className="mt-2 max-w-sm text-sm leading-5 text-emerald-50/65">{band.text}</p>
                  </div>
                </div>
                <div className="border-t border-white/10 pt-4 text-xs leading-5 text-emerald-50/60 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
                  <div className="font-semibold text-white">Posljednja modelirana vrijednost</div>
                  <div>{formatUpdated(latest?.measured_at ?? null)}</div>
                </div>
              </div>
            </div>
          </div>

          <aside className="card flex flex-col p-6 sm:p-7">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="label">Zdravstvene preporuke</p>
                <h2 className="mt-2 font-display text-2xl font-bold">Današnji pokazatelj</h2>
              </div>
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-lime/20 text-moss">
                <ShieldCheck size={22} />
              </div>
            </div>
            <div className="my-6 h-px bg-slate-100" />
            <div className="space-y-5">
              <SignalRow label="Aktivnosti na otvorenom" value={aqiKnown ? (currentAqi! > 60 ? 'Smanjiti' : 'Uobičajeno') : 'Nepoznato'} good={aqiKnown && currentAqi! <= 60} neutral={!aqiKnown} />
              <SignalRow label="Osjetljive grupe" value={aqiKnown ? (currentAqi! > 40 ? 'Potreban oprez' : 'Nizak rizik') : 'Nepoznato'} good={aqiKnown && currentAqi! <= 40} neutral={!aqiKnown} />
              <SignalRow label="Vrsta podataka" value="Modelirana procjena" neutral />
            </div>
            <div className="mt-auto pt-7">
              <div className="rounded-2xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">
                <span className="font-semibold text-slate-800">Važno:</span> Ovo su opće informacije, a ne medicinski savjet. Stvarna mjerenja lokalnih senzora mogu se razlikovati od regionalne procjene CAMS mrežne ćelije.
              </div>
            </div>
          </aside>
        </section>

        <SensorPanel sensor={sensor} loading={sensorLoading} />

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-5" aria-label="Najnovije modelirane vrijednosti zagađujućih materija">
          {pollutantMeta.map(({ key, label, detail, icon: Icon, accent }) => (
            <article key={key} className="card p-4 sm:p-5">
              <div className="flex items-start justify-between gap-2">
                <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${accent}`}><Icon size={18} /></div>
                <span className="rounded-full bg-slate-50 px-2 py-1 text-[0.63rem] font-bold uppercase tracking-wider text-slate-400">modelirano</span>
              </div>
              <p className="mt-5 text-xs font-semibold text-slate-500">{label} · {detail}</p>
              <p className="mt-1 font-display text-2xl font-extrabold sm:text-3xl">
                {valueOf(latest, key)} <span className="text-[0.65rem] font-semibold text-slate-400">μg/m³</span>
              </p>
            </article>
          ))}
        </section>

        <WeatherPanel weather={weather} loading={weatherLoading} city={locations.find(l => l.slug === location)?.name ?? location} />

        <section className="card overflow-hidden">
          <div className="flex flex-col gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-7">
            <div>
              <p className="label">Historijski podaci</p>
              <h2 className="mt-1 font-display text-2xl font-bold">Koncentracije zagađujućih materija</h2>
            </div>
            <div className="flex rounded-xl bg-slate-100 p-1" aria-label="Historijski vremenski raspon">
              {ranges.map((range) => (
                <button
                  key={range.hours}
                  onClick={() => setHours(range.hours)}
                  className={`rounded-lg px-3 py-2 text-xs font-bold transition ${hours === range.hours ? 'bg-white text-moss shadow-sm' : 'text-slate-500 hover:text-ink'}`}
                >
                  {range.label}
                </button>
              ))}
            </div>
          </div>
          <div className="p-4 sm:p-7">
            <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-slate-600">
              <label className="flex min-w-0 max-w-full flex-wrap items-center gap-2">Izvor za grafikon i ML <select aria-label="Izvor za grafikon i ML" value={source} onChange={e => setSource(e.target.value as 'sensor' | 'modeled')} className="min-w-0 max-w-full rounded-xl border border-slate-200 bg-white p-2">
                <option value="sensor">Stvarna mjerenja</option><option value="modeled">Modelirani podaci (CAMS)</option>
              </select></label>
              {source === 'sensor' && <label className="flex min-w-0 max-w-full flex-wrap items-center gap-2">Mjerna stanica <select aria-label="Mjerna stanica" value={stationId ?? ''} onChange={e => setStationId(Number(e.target.value))} className="min-w-0 max-w-full rounded-xl border border-slate-200 bg-white p-2">
                {!stations.length && <option value="">Nema dostupnih stanica</option>}
                {stations.map(s => <option key={s.id} value={s.id}>{s.name} · {s.provider}</option>)}
              </select></label>}
              <span>{datasetLabel}</span>
            </div>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <div className="flex rounded-xl bg-slate-100 p-1" aria-label="Grupiranje historijskih podataka">
                  {(['hourly', 'daily'] as HistoryGrouping[]).map((value) => (
                    <button
                      key={value}
                      onClick={() => setHistoryGrouping(value)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${historyGrouping === value ? 'bg-white text-moss shadow-sm' : 'text-slate-500'}`}
                    >
                      {historyControlLabels[value]}
                    </button>
                  ))}
                </div>
                <div className="flex rounded-xl bg-slate-100 p-1" aria-label="Agregacija historijskih podataka">
                  {(['average', 'maximum'] as HistoryAggregation[]).map((value) => (
                    <button
                      key={value}
                      onClick={() => setHistoryAggregation(value)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${historyAggregation === value ? 'bg-white text-moss shadow-sm' : 'text-slate-500'}`}
                    >
                      {historyControlLabels[value]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="text-right text-xs text-slate-500">
                <span>Tačke: {formatInteger(history?.points.length ?? 0)}</span>
                <span className="mx-2 text-slate-300">·</span>
                <span>{historyAggregation === 'maximum' ? `Prosjek ${historyGrouping === 'daily' ? 'dnevnih' : 'satnih'} maksimuma` : 'Prosjek prikazanih vrijednosti'} PM2.5: <strong className="text-ink">{averages == null ? '—' : `${formatNumber(averages)} μg/m³`}</strong></span>
              </div>
            </div>
            {historyError ? (
              <div className="flex h-[320px] items-center justify-center rounded-2xl bg-amber-50 px-5 text-center text-sm text-amber-800" role="alert">
                Historijski podaci trenutno nisu dostupni. {historyError}
              </div>
            ) : (
              <AirQualityChart history={history} loading={historyLoading} />
            )}
            <div className="mt-4 flex flex-wrap items-start justify-between gap-3 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">
              <p className="max-w-3xl">
                Zagađenje: <strong className="text-slate-700">{datasetLabel}</strong>. Temperatura: <strong className="text-slate-700">Open-Meteo modelirani/historijski podaci</strong>. Izvori zagađenja se ne miješaju. Označeni i nepotpuni senzorski sati su izostavljeni.
                {source === 'sensor' && <span className="block">Izvor i uslovi: {stations.find(s => s.id === stationId)?.attribution.replace('upstream provider:', 'izvorni pružalac:')}. Automatski podaci nisu konačno validirani; satna oznaka predstavlja kraj mjernog intervala.</span>}
              </p>
              <p className="max-w-xl text-right">
                Broj uzoraka u opisu tačke pokazuje stvarnu dostupnost; nedostajući sati se ne dopunjavaju. Dnevne granice: Europe/Sarajevo.
              </p>
            </div>
          </div>
        </section>

        <ForecastPanel forecast={forecast} loading={forecastLoading} />

        <WeatherModelPanel comparison={weatherComparison} loading={comparisonLoading} />

        <section className="grid gap-5 lg:grid-cols-3">
          <article className="card p-6 lg:col-span-2 sm:p-7">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="label">Porijeklo podataka</p>
                <h2 className="mt-2 font-display text-2xl font-bold">Transparentnost ugrađena u sistem</h2>
              </div>
              <div className="flex items-center gap-2 rounded-full bg-sky-50 px-3 py-2 text-xs font-bold text-sky-800"><Info size={15} /> Nisu stvarna mjerenja</div>
            </div>
            <p className="mt-5 max-w-3xl text-sm leading-7 text-slate-600">
              CAMS atmosferske modelirane procjene dostupne su putem servisa Open-Meteo. Ove vrijednosti nisu mjerenja fizičke stanice za lokaciju {dashboard?.location.name ?? 'Zenica'}. Predstavljaju satne procjene najbliže mrežne ćelije i treba ih tumačiti kao regionalni kontekst, a ne kao izloženost na nivou pojedinačne ulice.
            </p>
            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <InfoTile icon={Database} label="Izvor podataka" value={dashboard?.source.name ?? 'Open-Meteo / CAMS'} />
              <InfoTile icon={MapPin} label="Lokacija mrežne ćelije" value={`${dashboard ? formatNumber(dashboard.location.latitude, 3) : '44,203'}°, ${dashboard ? formatNumber(dashboard.location.longitude, 3) : '17,908'}°`} />
              <InfoTile icon={Gauge} label="Pohranjene vrijednosti" value={formatInteger(dashboard?.sync.records_stored ?? 0)} />
            </div>
            <a
              href={dashboard?.source.url ?? 'https://open-meteo.com/en/docs/air-quality-api'}
              target="_blank"
              rel="noreferrer"
              className="mt-6 inline-flex items-center gap-2 text-sm font-bold text-moss hover:underline"
            >
              Pregledaj metodologiju izvora <ExternalLink size={15} />
            </a>
          </article>

          <article className="card p-6 sm:p-7">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-50 text-moss"><ServerCog size={22} /></div>
            <p className="label mt-5">Zeleno softversko inženjerstvo</p>
            <h2 className="mt-2 font-display text-2xl font-bold">Manje zahtjeva, korisni podaci</h2>
            <ul className="mt-5 space-y-4 text-sm text-slate-600">
              <GreenItem text="Predmemorija izvora od 30 minuta" />
              <GreenItem text="Jedan objedinjeni zahtjev za nadzornu ploču" />
              <GreenItem text="Indeksirana pohrana bez duplikata" />
              <GreenItem text="Klijentsko osvježavanje svakih 15 minuta" />
            </ul>
            <div className="mt-6 rounded-2xl bg-[#eef5e8] p-4">
              <p className="text-xs font-semibold text-slate-500">Starost predmemorije</p>
              <p className="mt-1 font-display text-xl font-extrabold text-moss">
                {dashboard?.sync.cache_age_minutes == null ? 'Nije dostupno' : `${formatNumber(dashboard.sync.cache_age_minutes, 0)} min`}
              </p>
            </div>
          </article>
        </section>
      </main>

      <footer className="mt-6 border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-4 py-7 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <div>EcoMonitor · Implementacija završnog rada · Bosna i Hercegovina</div>
          <div className="flex items-center gap-1.5"><Leaf size={13} className="text-moss" /> Dizajnirano uz mjerljivu efikasnost zahtjeva</div>
        </div>
      </footer>
    </div>
  )
}

function valueOf(reading: Reading | null, key: keyof Reading) {
  const value = reading?.[key]
  return typeof value === 'number' ? formatNumber(value) : '—'
}

function AqiGauge({ value, color }: { value: number | null; color: string }) {
  const display = value == null ? '—' : formatInteger(Math.round(value))
  const progress = Math.min(100, Math.max(0, value ?? 0)) * 3.6
  return (
    <div
      className="relative flex h-28 w-28 shrink-0 items-center justify-center rounded-full"
      style={{ background: `conic-gradient(${color} ${progress}deg, rgba(255,255,255,.12) ${progress}deg)` }}
      aria-label={`Evropski AQI ${display}`}
    >
      <div className="flex h-[84px] w-[84px] flex-col items-center justify-center rounded-full bg-[#173c2d]">
        <span className="font-display text-3xl font-extrabold">{display}</span>
        <span className="text-[0.6rem] font-bold uppercase tracking-widest text-emerald-100/60">EAQI</span>
      </div>
    </div>
  )
}

function SignalRow({ label, value, good, neutral }: { label: string; value: string; good?: boolean; neutral?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-slate-500">{label}</span>
      <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${neutral ? 'bg-sky-50 text-sky-800' : good ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>{value}</span>
    </div>
  )
}

function InfoTile({ icon: Icon, label, value }: { icon: typeof Database; label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
      <Icon size={18} className="text-moss" />
      <p className="mt-3 text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-bold text-slate-700">{value}</p>
    </div>
  )
}

function GreenItem({ text }: { text: string }) {
  return <li className="flex items-center gap-3"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-lime/30 text-moss"><Check size={12} /></span>{text}</li>
}

