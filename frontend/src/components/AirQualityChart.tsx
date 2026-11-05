import { useId, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  HistoricalData,
  HistoricalPoint,
  HistoryAggregation,
  HistoryGrouping,
  HistorySeriesKey,
} from '../types'
import { formatDate, formatDateTime, formatNumber } from '../locale'

type Props = {
  history: HistoricalData | null
  loading: boolean
}

const series: Array<{
  key: HistorySeriesKey
  label: string
  color: string
  width: number
  defaultVisible: boolean
  temperature?: boolean
}> = [
  { key: 'pm2_5', label: 'PM2.5', color: '#397253', width: 3, defaultVisible: true },
  { key: 'pm10', label: 'PM10', color: '#ef8d58', width: 2, defaultVisible: true },
  { key: 'nitrogen_dioxide', label: 'NO₂', color: '#7868d8', width: 2, defaultVisible: true },
  { key: 'sulphur_dioxide', label: 'SO₂', color: '#3d8fb7', width: 2, defaultVisible: false },
  { key: 'ozone', label: 'O₃', color: '#d0619e', width: 2, defaultVisible: false },
  { key: 'carbon_monoxide', label: 'CO', color: '#887258', width: 2, defaultVisible: false },
  { key: 'temperature_2m', label: 'Temperatura', color: '#d13b45', width: 2.5, defaultVisible: true, temperature: true },
]

const initialVisibility = Object.fromEntries(
  series.map((item) => [item.key, item.defaultVisible]),
) as Record<HistorySeriesKey, boolean>

const dateFormatter = (_timezone: string, grouping: HistoryGrouping) =>
  ({ format: (value: Date) => grouping === 'daily' ? formatDate(value) : formatDateTime(value) })

const formatTimestamp = (value: string, _timezone: string) => formatDateTime(value)

export function AirQualityChart({ history, loading }: Props) {
  const gradientId = useId().replace(/:/g, '')
  const [visible, setVisible] = useState(initialVisibility)
  const data = history?.points ?? []
  const grouping = history?.grouping ?? 'hourly'
  const aggregation = history?.aggregation ?? 'average'
  const timezone = history?.timezone ?? 'Europe/Sarajevo'
  const tickFormatter = dateFormatter(timezone, grouping)

  if (loading && !history) {
    return (
      <div className="flex h-[320px] items-center justify-center text-sm text-slate-500" role="status">
        Učitavanje historijskih podataka i temperature…
      </div>
    )
  }

  if (!data.some(point => series.some(item => point[item.key] != null))) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-2xl bg-slate-50 px-5 text-center text-sm text-slate-500">
        Za odabrani period nema dostupnih podataka o zagađenju ni modeliranih meteoroloških podataka.
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2" aria-label="Odabir serija grafikona">
        {series.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={visible[item.key]}
            onClick={() => setVisible((current) => ({ ...current, [item.key]: !current[item.key] }))}
            className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold transition ${
              visible[item.key]
                ? 'border-slate-200 bg-white text-slate-700 shadow-sm'
                : 'border-transparent bg-slate-100 text-slate-400'
            }`}
          >
            <span
              className={`h-0.5 w-4 ${item.temperature ? 'border-t-2 border-dashed bg-transparent' : ''}`}
              style={item.temperature ? { borderColor: item.color } : { backgroundColor: item.color }}
            />
            {item.label}
          </button>
        ))}
      </div>

      <div className="h-[320px] w-full" aria-label="Grafikon historijskih koncentracija i temperature">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 14, left: 8, bottom: 4 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#b7e45e" />
                <stop offset="100%" stopColor="#245c47" />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#e7ece8" strokeDasharray="4 5" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={(value: string) => tickFormatter.format(new Date(value))}
              tick={{ fill: '#718078', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              minTickGap={36}
            />
            <YAxis
              yAxisId="pollution"
              tickFormatter={value => formatNumber(Number(value), 0)}
              tick={{ fill: '#718078', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={52}
              label={{ value: 'μg/m³', angle: -90, position: 'insideLeft', fill: '#718078', fontSize: 11 }}
            />
            <YAxis
              yAxisId="temperature"
              tickFormatter={value => formatNumber(Number(value), 0)}
              orientation="right"
              tick={{ fill: '#b13b45', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={48}
              label={{ value: '°C', angle: 90, position: 'insideRight', fill: '#b13b45', fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const point = payload[0].payload as HistoricalPoint
                return (
                  <div className="max-w-[290px] rounded-2xl bg-white p-4 text-xs shadow-[0_16px_40px_rgba(20,35,29,.14)]">
                    <p className="font-bold text-slate-800">
                      {grouping === 'daily'
                        ? formatDate(point.timestamp)
                        : formatTimestamp(point.timestamp, timezone)}
                    </p>
                    <div className="mt-3 space-y-2">
                      {payload.map((item) => {
                        const key = String(item.dataKey) as HistorySeriesKey
                        const definition = series.find((candidate) => candidate.key === key)
                        if (!definition || item.value == null) return null
                        const peak = point.peak_timestamps[key]
                        return (
                          <div key={key}>
                            <div className="flex items-center justify-between gap-5">
                              <span className="flex items-center gap-2 text-slate-600">
                                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: definition.color }} />
                                {definition.label}
                              </span>
                              <strong className="text-slate-800">
                                {formatNumber(Number(item.value))} {definition.temperature ? '°C' : 'μg/m³'}
                              </strong>
                            </div>
                            <p className="mt-0.5 pl-4 text-[0.65rem] text-slate-400">
                              {point.sample_counts[key]} dostupnih uzoraka · očekivano {point.expected_samples} sati
                              {aggregation === 'maximum' && peak ? ` · vrh ${formatTimestamp(peak, timezone)}` : ''}
                            </p>
                          </div>
                        )
                      })}
                    </div>
                    {grouping === 'daily' && series.some(item => visible[item.key] && point.sample_counts[item.key] < point.expected_samples) && (
                      <p className="mt-3 border-t border-slate-100 pt-2 text-[0.65rem] leading-4 text-amber-700">
                        Dan je nepotpun; nedostajući sati nisu procijenjeni niti dopunjeni.
                      </p>
                    )}
                  </div>
                )
              }}
            />
            <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
            {series.map((item) => visible[item.key] && (
              <Line
                key={item.key}
                yAxisId={item.temperature ? 'temperature' : 'pollution'}
                type="monotone"
                dataKey={item.key}
                name={item.label}
                stroke={item.key === 'pm2_5' ? `url(#${gradientId})` : item.color}
                strokeWidth={item.width}
                strokeDasharray={item.temperature ? '7 5' : undefined}
                dot={data.filter(point => point[item.key] != null).length === 1 ? { r: 3 } : false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export const historyControlLabels: Record<HistoryGrouping | HistoryAggregation, string> = {
  hourly: 'Satno',
  daily: 'Dnevno',
  average: 'Prosjek',
  maximum: 'Maksimum',
}
