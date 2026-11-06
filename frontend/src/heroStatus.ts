import { aqiBand } from './aqi'
import type { DashboardData, SensorData, SensorStation } from './types'

export function heroStatus(source: 'sensor' | 'modeled', city: string, station: SensorStation | undefined,
  sensor: SensorData | null, dashboard: DashboardData | null, now = Date.now()) {
  const modeled = dashboard?.location.slug === city && dashboard.latest &&
    new Date(dashboard.latest.measured_at).getTime() <= now ? dashboard.latest : null
  const modelFresh = modeled && now - new Date(modeled.measured_at).getTime() <= 3 * 3600_000
  const modelAqi = modelFresh ? modeled?.european_aqi : null
  const modelBand = aqiBand(modelAqi)
  if (source === 'modeled') {
    const known = modelBand.label !== 'Nedostupno'
    return { value: known ? modelAqi ?? null : null, band: modelBand, known, categoryLabel: modelBand.label,
      label: 'Evropski AQI · CAMS (modelirano)', timestamp: modeled?.measured_at ?? null,
      timestampLabel: 'Posljednja dostupna modelirana procjena',
      badge: modeled ? modelFresh ? 'Modelirani podaci dostupni' : 'Modelirani podaci su zastarjeli' : 'Čeka se modelirana procjena',
      dataType: 'Modelirana procjena · CAMS', secondary: '',
      guidance: known ? modelBand.text : 'Trenutni modelirani AQI nije dostupan; ne izvodite zdravstveni zaključak iz nedostajućih vrijednosti.',
      healthGeneral: known ? modelAqi! > 60 ? 'Smanjiti' : 'Uobičajeno' : 'Nepoznato',
      healthSensitive: known ? modelAqi! > 40 ? 'Potreban oprez' : 'Nizak rizik' : 'Nepoznato',
      guidanceAvailable: known }
  }
  const selected = sensor?.location.slug === city && sensor.station_id === station?.id ? sensor : null
  const time = selected?.latest_measurement_at
  const timeValid = !!time && new Date(time).getTime() <= now
  const age = timeValid ? Math.max(0, Math.floor((now-new Date(time!).getTime())/60_000)) : null
  const ageText = age === null ? '' : age < 180 ? `${age} min` : age < 2880 ? `${Math.floor(age/60)} h ${age%60} min` : `${Math.floor(age/1440)} d ${Math.floor(age%1440/60)} h`
  const localToday = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Sarajevo', year: 'numeric', month: '2-digit', day: '2-digit' })
  const sameDay = timeValid && localToday.format(new Date(time!)) === localToday.format(new Date(now))
  const live = !!selected?.is_live && sameDay && age !== null && age <= 180
  const category = selected?.aqi_category ?? null
  const complete = !!selected?.aqi_complete
  const known = category !== null && category >= 1 && category <= 6
  const guidanceAvailable = live && complete && known && !!selected?.health_general && !!selected?.health_sensitive
  const colors = ['#51a56d', '#91bd54', '#e0b444', '#e98943', '#d95854', '#8b455f']
  const band = { ...aqiBand(null), color: known ? colors[category!-1] : '#94a3b8' }
  return { value: known ? category : null, band, known, categoryLabel: known ? selected!.aqi_label ?? 'Nedostupno' : 'AQI nije dostupan',
    label: `Fizička stanica · ${station?.name ?? 'nije odabrana'}`, timestamp: timeValid ? time! : null,
    timestampLabel: 'Posljednje mjerenje odabrane stanice',
    badge: live ? age! <= 90 ? 'Trenutna fizička mjerenja' : 'Nedavna fizička mjerenja' : timeValid ? 'Fizička mjerenja su zastarjela' : 'Fizička mjerenja nisu dostupna',
    dataType: `Stvarna mjerenja · ${station?.name ?? 'stanica nije odabrana'}`,
    guidance: !timeValid ? 'Nema valjanog satnog mjerenja odabrane stanice.'
      : !live ? `Historijska kategorija (${ageText} starosti); ne opisuje trenutno stanje zraka. Provjerite novija službena mjerenja.`
      : !known ? 'Nedovoljna pokrivenost zagađujućim materijama za pouzdanu kategoriju. Pratite službene lokalne preporuke.'
      : !complete ? 'Visok nivo je zabilježen uz nepotpun skup zagađujućih materija; zdravstvene preporuke su ograničene.'
      : `Privremena FHMZ/EEA satna kategorija ${selected!.aqi_label!.toLowerCase()}; automatski podaci nisu konačno validirani.${age! > 90 ? ` Posljednji sat je star ${age} min.` : ''}`,
    healthGeneral: guidanceAvailable ? category! >= 6 ? 'Smanjiti aktivnosti' : category! >= 4 ? 'Oprez uz simptome' : 'Uobičajeno' : 'Nije procjenjivo',
    healthSensitive: guidanceAvailable ? category! >= 6 ? 'Izbjegavati napor' : category! >= 4 ? 'Smanjiti aktivnosti' : category! === 3 ? 'Oprez uz simptome' : 'Uobičajeno' : 'Nije procjenjivo',
    guidanceAvailable,
    secondary: modelBand.label !== 'Nedostupno'
      ? `Odvojeni regionalni pokazatelj: CAMS modelirani evropski AQI ${Math.round(modelAqi!)} (${modelBand.label}); ne predstavlja mjerenje stanice.`
      : 'Odvojeni regionalni CAMS pokazatelj trenutno nije dostupan.' }
}
