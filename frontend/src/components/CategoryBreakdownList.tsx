import type { CategoryBreakdown } from '../api/client'
import { SERIES } from '../lib/chartColors'
import { formatKzt } from '../lib/money'
import { EmptyState } from './ui'

/**
 * Ranked horizontal bars: one series colour for every bar (bar length shows magnitude);
 * the small dot is the category's own colour, for identity. Doubles as the table view.
 */
export function CategoryBreakdownList({ breakdown, limit }: { breakdown: CategoryBreakdown; limit?: number }) {
  const items = limit ? breakdown.items.slice(0, limit) : breakdown.items
  const largest = breakdown.items[0]?.total_cents ?? 0
  const color = SERIES[breakdown.type]

  if (items.length === 0) {
    return (
      <EmptyState
        title={`No ${breakdown.type === 'expense' ? 'expenses' : 'income'} in this period`}
        description="Add transactions to see where your money goes."
      />
    )
  }

  return (
    <ul className="flex flex-col gap-3">
      {items.map((item) => {
        // Bar width is presentation only; all amounts and percentages come from the backend.
        const width = largest > 0 ? Math.max((item.total_cents / largest) * 100, 1) : 0
        return (
          <li key={item.category_id}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
              <span className="flex min-w-0 items-center gap-2">
                <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: item.color }} aria-hidden="true" />
                <span className="truncate text-slate-800">{item.category_name}</span>
              </span>
              <span className="shrink-0 tabular-nums text-slate-900">
                {formatKzt(item.total_cents)}
                <span className="ml-2 inline-block w-14 text-right text-xs text-slate-500">{item.percentage}%</span>
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100" aria-hidden="true">
              <div className="h-2 rounded-full" style={{ width: `${width}%`, backgroundColor: color }} />
            </div>
          </li>
        )
      })}
    </ul>
  )
}
