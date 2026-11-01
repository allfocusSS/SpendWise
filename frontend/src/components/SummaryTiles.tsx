import type { UseQueryResult } from '@tanstack/react-query'

import type { Summary } from '../api/client'
import { formatKzt } from '../lib/money'
import { labelClass } from '../lib/styles'
import { InlineError, Skeleton } from './ui'

function Cell({ label, value, query, valueClassName = 'text-ink' }: {
  label: string
  value?: string
  valueClassName?: string
  query: UseQueryResult<Summary>
}) {
  return (
    // One row of four on wide screens, 2 × 2 below that; hairlines between cells.
    <div className="flex min-w-0 flex-col gap-1.5 border-line px-4 py-4 odd:pl-0 even:border-l nth-[n+3]:border-t sm:px-6 sm:odd:pl-0 xl:border-l xl:first:border-l-0 xl:nth-3:pl-6 xl:nth-[n+3]:border-t-0">
      <dt className={labelClass}>{label}</dt>
      <dd>
        {query.isError ? (
          <InlineError error={query.error} onRetry={() => query.refetch()} />
        ) : query.isPending || value === undefined ? (
          <Skeleton className="mt-1 h-6 w-2/3" />
        ) : (
          <p className={`truncate text-lg font-semibold tracking-tight tabular-nums sm:text-figure ${valueClassName}`} title={value}>{value}</p>
        )}
      </dd>
    </div>
  )
}

/** Net change / money in / money out / count for one period, as one open row of totals (all from the backend). */
export function SummaryTiles({ query, period }: { query: UseQueryResult<Summary>; period: string }) {
  const data = query.data
  return (
    <section aria-label={`Totals, ${period}`}>
      <p className={labelClass}>
        Totals · <span className="text-ink-muted">{period}</span>
      </p>
      <dl className="mt-2 grid grid-cols-2 border-y border-line xl:grid-cols-4">
        <Cell label="Net change" value={data && formatKzt(data.balance_cents)} valueClassName={data && data.balance_cents < 0 ? 'text-expense' : 'text-ink'} query={query} />
        <Cell label="Money in" value={data && formatKzt(data.total_income_cents)} valueClassName="text-income" query={query} />
        <Cell label="Money out" value={data && formatKzt(data.total_expense_cents)} query={query} />
        <Cell label="Transactions" value={data && String(data.transaction_count)} query={query} />
      </dl>
    </section>
  )
}
