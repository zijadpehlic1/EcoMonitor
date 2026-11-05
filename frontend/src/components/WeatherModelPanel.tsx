import { AlertTriangle, BarChart3, BrainCircuit, CheckCircle2 } from 'lucide-react'
import { formatDateTime, formatInteger, formatNumber } from '../locale'
import type { WeatherModelComparison } from '../types'

type Props = {
  comparison: WeatherModelComparison | null
  loading: boolean
}

export function WeatherModelPanel({ comparison, loading }: Props) {
  if ((loading && !comparison) || comparison?.status === 'pending') {
    return <section className="card p-7 text-sm text-slate-500">Izračunavanje poređenja modela…</section>
  }

  const ready = comparison?.comparison_is_fair && comparison.pollution_only && comparison.weather_aware && comparison.persistence
  const change = comparison?.weather_mae_change_percent
  const improved = change != null && change > 0

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:px-7">
        <div>
          <p className="label">Mašinsko učenje</p>
          <h2 className="mt-1 font-display text-2xl font-bold">Utjecaj vremena na PM2.5 prognozu</h2>
          {comparison && <p className="mt-2 text-xs text-slate-500">{comparison.provenance} Izračunato: {formatDateTime(comparison.generated_at)}.</p>}
        </div>
        <div className="flex items-center gap-2 rounded-full bg-violet-50 px-3 py-2 text-xs font-bold text-violet-800">
          <BrainCircuit size={15} /> 24-satna walk-forward evaluacija
        </div>
      </div>

      {!ready ? (
        <div className="flex items-start gap-3 p-5 text-sm leading-6 text-slate-600 sm:p-7">
          <AlertTriangle size={20} className="mt-0.5 shrink-0 text-amber-600" />
          <div>
            <strong className="text-slate-800">Pošteno poređenje još nije moguće.</strong>{' '}
            {comparison ? 'Nedostaje dovoljno neprekidnih PM2.5 podataka ili vremenski poravnatih arhiviranih meteoroloških prognoza. Sistem ne koristi naknadno poznata opažanja kao zamjenu.' : 'Usluga nije dostupna ili nije odabrana mjerna stanica.'}
          </div>
        </div>
      ) : (
        <div className="p-5 sm:p-7">
          <div className="grid gap-3 md:grid-cols-3">
            <MetricCard title="Model samo s PM2.5" mae={comparison.pollution_only!.mae} rmse={comparison.pollution_only!.rmse} />
            <MetricCard title="Model s meteorološkim podacima" mae={comparison.weather_aware!.mae} rmse={comparison.weather_aware!.rmse} highlighted />
            <MetricCard title="Bazni model perzistencije" mae={comparison.persistence!.mae} rmse={comparison.persistence!.rmse} />
          </div>

          <div className={`mt-5 flex items-start gap-3 rounded-2xl p-4 text-sm ${improved ? 'bg-emerald-50 text-emerald-900' : 'bg-amber-50 text-amber-900'}`}>
            {improved ? <CheckCircle2 size={19} className="mt-0.5 shrink-0" /> : <BarChart3 size={19} className="mt-0.5 shrink-0" />}
            <div>
              <strong>{improved ? 'Na ovom testnom periodu meteorološki model ima niži MAE.' : 'Na ovom testnom periodu nije zabilježeno poboljšanje MAE.'}</strong>{' '}
              {change != null
                ? improved
                  ? `Smanjenje iznosi ${formatNumber(change, 1)}%.`
                  : `MAE modela s vremenom veći je za ${formatNumber(Math.abs(change), 1)}%.`
                : ''}
            </div>
          </div>

          <div className="mt-5 grid gap-3 text-xs text-slate-500 sm:grid-cols-4">
            <div>Trening uzorci: <strong className="text-slate-700">{formatInteger(comparison.training_samples)}</strong></div>
            <div>Evaluacijska polazišta: <strong className="text-slate-700">{formatInteger(comparison.evaluation_origins)}</strong></div>
            <div>Testni koraci: <strong className="text-slate-700">{formatInteger(comparison.test_samples)}</strong></div>
            <div>Period do: <strong className="text-slate-700">{comparison.test_end ? formatDateTime(comparison.test_end) : '—'}</strong></div>
          </div>
          <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">
            <strong className="text-slate-800">Meteorološki podržana prognoza:</strong>{' '}
            {comparison.forecast.length
              ? `${formatInteger(comparison.forecast.length)} sata; prva vrijednost ${formatNumber(comparison.forecast[0].predicted_pm2_5)} μg/m³ u ${formatDateTime(comparison.forecast[0].timestamp)}.`
              : 'nije objavljena: potrebni su neprekidni svježi PM2.5 podaci i potpuna, svježa meteorološka prognoza.'}
          </div>
          <p className="mt-5 text-xs leading-5 text-slate-500">
            MAE je Prosječna apsolutna greška, a RMSE korijen srednje kvadratne greške. Niža vrijednost je bolja. Historijski backtest koristi arhivirane prognoze vremena koje su bile dostupne prije ciljnog sata; ograničenje metodologije dokumentirano je u tehničkoj dokumentaciji.
          </p>
          {comparison.by_horizon && <details className="mt-4 text-xs text-slate-600">
            <summary className="cursor-pointer font-semibold">Greške po prognoznom satu (μg/m³)</summary>
            <div className="mt-3 overflow-x-auto"><table className="w-full text-left"><thead><tr><th>Sat</th><th>PM2.5 MAE / RMSE</th><th>Vrijeme MAE / RMSE</th><th>Perzistencija MAE / RMSE</th></tr></thead><tbody>
              {Object.entries(comparison.by_horizon).map(([hour, score]) => <tr key={hour}><td className="py-1">{hour}</td>{['pollution_only', 'weather_aware', 'persistence'].map(key => <td key={key}>{formatNumber(score[`${key}_mae`], 3)} / {formatNumber(score[`${key}_rmse`], 3)}</td>)}</tr>)}
            </tbody></table></div>
          </details>}
        </div>
      )}
    </section>
  )
}

function MetricCard({ title, mae, rmse, highlighted = false }: { title: string; mae: number; rmse: number; highlighted?: boolean }) {
  return (
    <article className={`rounded-2xl border p-4 ${highlighted ? 'border-moss/20 bg-[#eef5e8]' : 'border-slate-100 bg-slate-50/70'}`}>
      <p className="text-xs font-bold text-slate-700">{title}</p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div><p className="text-[0.62rem] font-bold uppercase tracking-wider text-slate-400">MAE</p><p className="mt-1 font-display text-xl font-extrabold">{formatNumber(mae, 3)}</p></div>
        <div><p className="text-[0.62rem] font-bold uppercase tracking-wider text-slate-400">RMSE</p><p className="mt-1 font-display text-xl font-extrabold">{formatNumber(rmse, 3)}</p></div>
      </div>
      <p className="mt-2 text-[0.65rem] text-slate-400">μg/m³</p>
    </article>
  )
}
