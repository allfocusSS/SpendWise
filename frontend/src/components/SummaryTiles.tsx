import type { Summary } from '../api/client'
import { SERIES } from '../lib/chartColors'
import { formatKzt } from '../lib/money'
import { cardClass } from '../lib/styles'

function Tile({ label, value, marker, note }: { label: string; value: number; marker?: string; note?: string }) {
  return (
    <div className={`${cardClass} p-4`}>
      <dt className="flex items-center gap-2 text-sm text-slate-600">
        {marker && <span className="size-2.5 rounded-sm" style={{ backgroundColor: marker }} aria-hidden="true" />}
        {label}
      </dt>
      <dd className="mt-1 truncate text-2xl font-semibold tracking-tight text-slate-900">{formatKzt(value)}</dd>
      {note && <dd className="mt-0.5 text-xs text-slate-500">{note}</dd>}
    </div>
  )
}

/** Income / expenses / net for one period. All numbers are computed by the backend. */
export function SummaryTiles({ summary, netLabel = 'Net' }: { summary: Summary; netLabel?: string }) {
  return (
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Tile label="Income" value={summary.total_income_cents} marker={SERIES.income} />
      <Tile label="Expenses" value={summary.total_expense_cents} marker={SERIES.expense} />
      <Tile
        label={netLabel}
        value={summary.balance_cents}
        note={`${summary.transaction_count} transaction${summary.transaction_count === 1 ? '' : 's'}`}
      />
    </dl>
  )
}
