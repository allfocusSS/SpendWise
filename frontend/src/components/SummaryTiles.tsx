import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import type { Summary } from '../api/client'
import { cardClass } from '../lib/styles'
import { CalendarIcon } from './icons'
import { Figure, InlineError, Skeleton } from './ui'

/** A line under each figure, e.g. "3 income categories". */
export type TileNotes = { net?: ReactNode; income?: ReactNode; expense?: ReactNode; count?: ReactNode }

/** One stat card: its own term and value (so the value's text is exactly the figure), then a note. */
function Tile({ label, query, note, children }: {
  label: string
  query: UseQueryResult<Summary>
  note?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className={`${cardClass} flex min-w-0 flex-col gap-2 p-4 lg:px-5 lg:py-[18px]`}>
      <dl className="flex min-w-0 flex-col gap-2">
        <dt className="text-[15px] font-medium tracking-[-0.005em] text-ink">{label}</dt>
        <dd className="min-w-0">
          {query.isError ? (
            <InlineError error={query.error} onRetry={() => query.refetch()} />
          ) : query.isPending || children === undefined ? (
            <Skeleton className="h-[33px] w-2/3" />
          ) : (
            <p className="truncate text-figure xl:text-figure-lg">{children}</p>
          )}
        </dd>
      </dl>
      {note ? <p className="text-[12.5px] text-ink-subtle">{note}</p> : null}
    </div>
  )
}

/** Net change / money in / money out / count for one period, as four stat cards (all from the backend). */
export function SummaryTiles({ query, period, notes = {} }: { query: UseQueryResult<Summary>; period: string; notes?: TileNotes }) {
  const data = query.data
  const net = data?.balance_cents ?? 0
  return (
    <section aria-label={`Totals, ${period}`}>
      <p className="mb-2.5 flex items-center gap-2 text-label text-ink-muted">
        <CalendarIcon className="size-4 text-ink-subtle" />
        {period}
      </p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-[18px]">
        <Tile label="Net change" query={query} note={notes.net}>
          {data ? <span className={net > 0 ? 'text-income' : net < 0 ? 'text-expense' : ''}><Figure cents={net} signed /></span> : undefined}
        </Tile>
        <Tile label="Money in" query={query} note={notes.income}>{data ? <Figure cents={data.total_income_cents} /> : undefined}</Tile>
        <Tile label="Money out" query={query} note={notes.expense}>{data ? <Figure cents={data.total_expense_cents} /> : undefined}</Tile>
        <Tile label="Transactions" query={query} note={notes.count}>{data ? <span className="tabular-nums">{data.transaction_count}</span> : undefined}</Tile>
      </div>
    </section>
  )
}
