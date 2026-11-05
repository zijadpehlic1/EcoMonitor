import type {
  DashboardData,
  ForecastData,
  HistoricalData,
  HistoryAggregation,
  HistoryGrouping,
  Location,
  SensorData,
  SensorStation,
  WeatherData,
  WeatherModelComparison,
} from './types'

const API_BASE = import.meta.env.VITE_API_URL ?? '/api/v1'

async function request<T>(path: string, init?: RequestInit, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: init?.signal ?? controller.signal })
    if (!response.ok) {
      throw new Error(`Zahtjev nije uspješno izvršen (HTTP ${response.status}).`)
    }
    return await response.json() as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Zahtjev je predugo trajao. Pokušajte ponovo kasnije.')
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

const datasetQuery = (source: string, station?: number) => `&source=${source}${source === 'sensor' && station ? `&station_id=${station}` : ''}`

export const api = {
  stations: (location: string) => request<SensorStation[]>(`/sensors/stations?location=${encodeURIComponent(location)}`),
  locations: () => request<Location[]>('/locations'),
  dashboard: (location: string, hours: number) =>
    request<DashboardData>(`/dashboard?location=${encodeURIComponent(location)}&hours=${hours}`),
  history: (location: string, hours: number, grouping: HistoryGrouping, aggregation: HistoryAggregation, source = 'modeled', station?: number) =>
    request<HistoricalData>(
      `/history?location=${encodeURIComponent(location)}&hours=${hours}&grouping=${grouping}&aggregation=${aggregation}${datasetQuery(source, station)}`,
    ),
  forecast: (location: string, horizon = 24, source = 'modeled', station?: number) =>
    request<ForecastData>(`/forecast/pm25?location=${encodeURIComponent(location)}&horizon=${horizon}${datasetQuery(source, station)}`, undefined, 120_000),
  weather: (location: string) =>
    request<WeatherData>(`/weather?location=${encodeURIComponent(location)}`),
  weatherComparison: (location: string, horizon = 24, source = 'modeled', station?: number) =>
    request<WeatherModelComparison>(
      `/forecast/pm25/weather-comparison?location=${encodeURIComponent(location)}&horizon=${horizon}${datasetQuery(source, station)}`,
      undefined,
      120_000,
    ),
  sensors: (location: string) =>
    request<SensorData>(`/sensors/current?location=${encodeURIComponent(location)}`),
  refresh: (location: string, force = false) =>
    request<{ status: string; message: string }>(
      `/refresh?location=${encodeURIComponent(location)}&force=${force}`,
      { method: 'POST' },
    ),
  refreshWeather: (location: string, force = false) =>
    request<{ status: string; message: string }>(
      `/weather/refresh?location=${encodeURIComponent(location)}&force=${force}`,
      { method: 'POST' },
    ),
  refreshSensors: (location: string, force = false) =>
    request<{ status: string; message: string }>(
      `/sensors/refresh?location=${encodeURIComponent(location)}&force=${force}`,
      { method: 'POST' },
    ),
}

