import { describe, expect, it } from 'vitest'
import { heroStatus } from './heroStatus'
import type { DashboardData, SensorData, SensorStation } from './types'

const now = Date.parse('2026-11-05T12:30:00Z')
const city = 'mostar'
const station = { id: 30, name: 'Mostar', location: city } as SensorStation
const dashboard = { location: { slug: city }, latest: { measured_at: '2026-11-05T12:00:00Z', european_aqi: 45 } } as DashboardData
const sensor = { location: { slug: city }, station_id: 30, is_live: true, latest_measurement_at: '2026-11-05T12:00:00Z', validation_status: 'unvalidated' } as SensorData

describe('hero source and validity', () => {
  it('keeps CAMS guidance only in modeled mode', () => {
    const modeled = heroStatus('modeled', city, station, sensor, dashboard, now)
    expect(modeled.value).toBe(45)
    expect(modeled.dataType).toContain('CAMS')
    expect(modeled.guidance).toContain('Osjetljive')
    const physical = heroStatus('sensor', city, station, sensor, dashboard, now)
    expect(physical.value).toBeNull()
    expect(physical.label).toContain('Mostar')
    expect(physical.guidance).toContain('Nedovoljna pokrivenost')
    expect(physical.secondary).toContain('Odvojeni regionalni pokazatelj')
  })
  it('uses the physical category and health advice only for a complete same-day snapshot', () => {
    const complete = { ...sensor, aqi_category: 4, aqi_label: 'Zagađen', aqi_complete: true,
      health_general: 'Razmotrite smanjenje aktivnosti.', health_sensitive: 'Smanjite aktivnosti.' }
    const physical = heroStatus('sensor', city, station, complete, dashboard, now)
    expect(physical.value).toBe(4)
    expect(physical.categoryLabel).toBe('Zagađen')
    expect(physical.guidanceAvailable).toBe(true)
    expect(physical.healthSensitive).toBe('Smanjiti aktivnosti')
    expect(physical.secondary).toContain('CAMS modelirani')
    const incomplete = heroStatus('sensor', city, station, { ...complete, aqi_complete: false }, dashboard, now)
    expect(incomplete.value).toBe(4)
    expect(incomplete.guidanceAvailable).toBe(false)
    const stale = heroStatus('sensor', city, station, { ...complete, latest_measurement_at: '2026-11-04T12:00:00Z' }, dashboard, now)
    expect(stale.value).toBe(4)
    expect(stale.guidanceAvailable).toBe(false)
    expect(stale.badge).toContain('zastarjela')
  })
  it('rejects wrong station, stale and future times', () => {
    expect(heroStatus('sensor', city, { ...station, id: 31 }, sensor, dashboard, now).timestamp).toBeNull()
    expect(heroStatus('sensor', city, station, { ...sensor, latest_measurement_at: '2026-11-05T13:00:00Z' }, dashboard, now).timestamp).toBeNull()
    expect(heroStatus('sensor', city, station, { ...sensor, latest_measurement_at: '2026-11-05T05:00:00Z' }, dashboard, now).badge).toContain('zastarjela')
    const future = heroStatus('modeled', city, station, sensor, { ...dashboard, latest: { ...dashboard.latest!, measured_at: '2026-11-05T13:00:00Z' } }, now)
    expect(future.value).toBeNull()
    expect(future.timestamp).toBeNull()
  })
})
