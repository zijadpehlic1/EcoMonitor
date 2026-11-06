import { Database, MapPin, Gauge, Info, ExternalLink } from 'lucide-react'
import type { DashboardData, SensorStation } from '../types'
import { formatDateTime, formatInteger, formatNumber } from '../locale'

type Props = { city: string; source: 'sensor' | 'modeled'; stationId?: number; stations: SensorStation[]; dashboard: DashboardData | null }

export function ProvenancePanel({city, source, stationId, stations, dashboard}: Props) {
  const station = stations.find(s => s.id === stationId && s.location === city)
  const modeled = dashboard?.location.slug === city ? dashboard : null
  const physical = source === 'sensor'
  const name = modeled?.location.name ?? city
  const url = physical ? station?.source_url : modeled?.source.url
  const hasGrid = modeled?.source.grid_latitude != null && modeled?.source.grid_longitude != null
  return <article className="card p-6 lg:col-span-2 sm:p-7">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="label">Porijeklo podataka</p><h2 className="mt-2 font-display text-2xl font-bold">Transparentnost ugrađena u sistem</h2></div>
      <div className="flex items-center gap-2 rounded-full bg-sky-50 px-3 py-2 text-xs font-bold text-sky-800"><Info size={15}/>{physical ? 'Stvarna mjerenja' : 'Nisu stvarna mjerenja'}</div>
    </div>
    <p className="mt-5 max-w-3xl text-sm leading-7 text-slate-600">
      {physical ? station
        ? `Grafikon zagađenja i ML koriste fizička mjerenja stanice ${station.name}, pružalac: ${station.provider}. Pohranjeni zapis predstavlja jednu zagađujuću materiju u jednom mjernom terminu. Automatski podaci nisu konačno validirani; označeni i nepotpuni sati se ne koriste u analizi.`
        : 'Podaci o odabranoj mjernoj stanici još nisu dostupni. CAMS vrijednosti nisu zamjena za njena mjerenja.'
        : `CAMS atmosferske modelirane procjene dostupne su putem servisa Open-Meteo. Ove vrijednosti nisu mjerenja fizičke stanice za lokaciju ${name}. Predstavljaju satne procjene najbliže mrežne ćelije i regionalni kontekst, a ne izloženost na nivou pojedinačne ulice.`}
    </p>
    <div className="mt-6 grid gap-3 sm:grid-cols-3">
      <Tile icon={Database} label="Izvor podataka" value={physical ? station?.provider ?? 'Nedostupno' : modeled?.source.name ?? 'Open-Meteo / CAMS'}/>
      <Tile icon={MapPin} label={physical ? 'Mjerna stanica' : hasGrid ? 'CAMS mrežna ćelija' : 'Lokacija upita za CAMS'} value={physical ? station?.name ?? 'Nije odabrana' : modeled ? `${formatNumber(hasGrid ? Number(modeled.source.grid_latitude) : modeled.location.latitude,3)}°, ${formatNumber(hasGrid ? Number(modeled.source.grid_longitude) : modeled.location.longitude,3)}°` : 'Nedostupno'}/>
      <Tile icon={Gauge} label={physical ? 'Zapisi odabrane stanice' : 'Pohranjene CAMS vrijednosti'} value={physical ? station ? formatInteger(station.measurement_count) : '—' : modeled ? formatInteger(modeled.sync.records_stored) : '—'}/>
    </div>
    {physical && station && <p className="mt-4 text-xs leading-5 text-slate-500">
      Posljednje pohranjeno mjerenje: {station.last_measurement_at ? formatDateTime(station.last_measurement_at) : 'Nedostupno'}. Vrsta: fizička mjerna stanica.
      {' '}Validacija: {Object.entries(station.validation_counts ?? {}).map(([key,count]) => `${({unvalidated:'automatski, nevalidirani',provider_flagged:'označeni kod pružaoca',incomplete_hour:'nepotpuni sati',validated:'validirani'} as Record<string,string>)[key] ?? 'drugi status'}: ${formatInteger(count)}`).join('; ') || 'Status nije dostupan'}.
      <span className="block">{station.attribution.replace('upstream provider:', 'izvorni pružalac:')}</span>
    </p>}
    <p className="mt-4 text-xs leading-5 text-slate-500">{physical ? 'Glavna satna kategorija je privremeno izvedena iz mjerenja odabrane stanice prema objavljenim evropskim pragovima i pravilima potpunosti. Odvojeni regionalni AQI i kartice označene „modelirano“ koriste CAMS.' : 'Glavni AQI, zdravstvene preporuke i kartice označene „modelirano“ koriste CAMS.'} Temperatura na grafikonu i meteorološki panel koriste modelirane Open-Meteo podatke; to nisu mjerenja odabrane fizičke stanice. ML prognoza je izračun modela, a ne mjerenje.</p>
    {url && <a href={url} target="_blank" rel="noreferrer" className="mt-6 inline-flex items-center gap-2 text-sm font-bold text-moss hover:underline">Pregledaj metodologiju izvora <ExternalLink size={15}/></a>}
  </article>
}

function Tile({icon: Icon,label,value}: {icon: typeof Database;label:string;value:string}) {
  return <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4"><Icon size={18} className="text-moss"/><p className="mt-3 text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">{label}</p><p className="mt-1 text-sm font-bold text-slate-700">{value}</p></div>
}
