export type Location = {
  id: number
  slug: string
  name: string
  country: string
  country_code: string
  latitude: number
  longitude: number
  timezone: string
}

export type SensorStation = {
  id: number
  name: string
  provider: string
  source_url: string
  attribution: string
  measurement_count: number
  first_measurement_at: string | null
  last_measurement_at: string | null
}

export type Reading = {
  measured_at: string
  pm2_5: number | null
  pm10: number | null
  nitrogen_dioxide: number | null
  sulphur_dioxide: number | null
  carbon_monoxide: number | null
  ozone: number | null
  european_aqi: number | null
  source_name: string
  source_type: 'modeled' | 'sensor'
  model_name: string | null
  is_forecast: boolean
}

export type DashboardData = {
  location: Location
  latest: Reading | null
  history: Reading[]
  units: Record<string, string>
  source: {
    name: string
    model: string
    type: string
    url: string
    disclaimer: string
  }
  sync: {
    status: string
    last_successful_sync: string | null
    records_stored: number
    cache_age_minutes: number | null
  }
  requested_hours: number
  generated_at: string
}

export type HistoryGrouping = 'hourly' | 'daily'
export type HistoryAggregation = 'average' | 'maximum'
export type HistorySeriesKey =
  | 'pm2_5'
  | 'pm10'
  | 'nitrogen_dioxide'
  | 'sulphur_dioxide'
  | 'carbon_monoxide'
  | 'ozone'
  | 'temperature_2m'

export type HistoricalPoint = Record<HistorySeriesKey, number | null> & {
  timestamp: string
  local_date: string
  sample_counts: Record<HistorySeriesKey, number>
  peak_timestamps: Record<HistorySeriesKey, string | null>
  expected_samples: number
}

export type HistoricalData = {
  location: Location
  grouping: HistoryGrouping
  aggregation: HistoryAggregation
  requested_hours: number
  points: HistoricalPoint[]
  units: Record<HistorySeriesKey, string>
  pollution_source: { name: string; model?: string; station?: string; type: 'modeled' | 'sensor'; url: string }
  weather_sources: Array<{ name: string; type: string; url: string }>
  timezone: string
  generated_at: string
  completeness_note: string
}

export type ForecastData = {
  status: 'ready' | 'insufficient_data' | 'comparison_ready_forecast_unavailable'
  message: string
  model: string | null
  trained_samples: number
  metrics: null | {
    test_samples: number
    evaluation_horizon_hours: number
    evaluation_origins: number
    mae: number
    rmse: number
    baseline_mae: number
    baseline_rmse: number
    improvement_over_baseline_percent: number
    train_start: string
    train_end: string
    test_start: string
    test_end: string
  }
  forecast: Array<{ timestamp: string; predicted_pm2_5: number }>
  generated_at: string
  target: string
  target_unit: string
  provenance: string
}

export type WeatherReading = {
  measured_at: string
  temperature_2m: number | null
  relative_humidity_2m: number | null
  wind_speed_10m: number | null
  precipitation: number | null
  source_name: string
  source_type: string
  is_forecast: boolean
}

export type WeatherData = {
  location: Location
  latest: WeatherReading | null
  daily: null | {
    date: string
    temperature_min: number | null
    temperature_max: number | null
    temperature_mean: number | null
    source_type: string
    is_forecast: boolean
  }
  forecast: WeatherReading[]
  units: Record<string, string>
  source: {
    name: string
    type: string
    url: string
    disclaimer: string
  }
  last_successful_sync: string | null
}

export type WeatherModelComparison = {
  provenance: string
  by_horizon: Record<string, Record<string, number>>
  status: 'ready' | 'comparison_ready_forecast_unavailable' | 'insufficient_data'
  message: string
  comparison_is_fair: boolean
  limitation: string
  evaluation_horizon_hours: number
  aligned_samples: number
  training_samples: number
  evaluation_origins: number
  test_samples: number
  train_start: string | null
  train_end: string | null
  test_start: string | null
  test_end: string | null
  pollution_only: null | { mae: number; rmse: number }
  weather_aware: null | { mae: number; rmse: number }
  persistence: null | { mae: number; rmse: number }
  weather_mae_change_percent: number | null
  features: string[]
  forecast: Array<{ timestamp: string; predicted_pm2_5: number }>
  generated_at: string
}

export type SensorData = {
  status: 'live' | 'stale' | 'unavailable'
  is_live: boolean
  location: Location
  station_name: string | null
  provider: string | null
  source_url: string | null
  measurements: Array<{
    pollutant: string
    value: number
    unit: string
    measured_at: string
  }>
  latest_measurement_at: string | null
  freshness_minutes: number | null
  validation_status: string | null
  message: string
  disclaimer: string
}

