import type { ReactNode } from 'react'

import type { Summary } from '../../api/client'
import { cardClass } from '../../lib/styles'
import { TrendDownIcon, TrendFlatIcon, TrendUpIcon } from '../icons'
import { InlineError, Skeleton } from '../ui'

/** What the Dashboard needs from a summary query (React Query's result fits it). */
export type SummaryQuery = { data?: Summary; isError: boolean; error: unknown; refetch: () => unknown }

/**
 * One of the four figures across the top: title and a short context on one line, the figure, then
 * a line about it. A labelled region ("Money in, November 2026"), so the name says which month.
 */
export function KpiCard({ title, meta, label = title, className = '', children }: {
  title: string
  meta?: ReactNode
  /** The region's name, when the title alone doesn't say what period it covers. */
  label?: string
  className?: string
  children: ReactNode
}) {
  return (
    <section aria-label={label} className={`${cardClass} flex min-w-0 flex-col gap-2 p-4 lg:px-5 lg:py-[18px] ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h2 className="text-[15px] font-medium tracking-[-0.005em] text-ink">{title}</h2>
        {meta ? <span className="text-[12.5px] text-ink-subtle">{meta}</span> : null}
      </div>
      {children}
    </section>
  )
}

/** The card's figure, or its loading / error state. */
export function KpiFigure({ query, className = '', children }: { query: SummaryQuery; className?: string; children?: ReactNode }) {
  if (query.isError) return <InlineError error={query.error} onRetry={() => query.refetch()} />
  if (!query.data) return <Skeleton className="h-[33px] w-2/3" />
  return <p className={`truncate text-figure tabular-nums lg:text-figure-lg ${className}`}>{children}</p>
}

/** The line under a figure. */
export function KpiNote({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`flex min-h-5 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[12.5px] text-ink-subtle ${className}`}>{children}</div>
}

/**
 * A change with its direction: an arrow, a word for screen readers (unless the value carries its own
 * sign), and a colour that says whether it is good news. `good` null means neutral.
 */
export function Change({ direction, good, signed = false, children }: {
  direction: number
  good: boolean | null
  /** The value is written with its sign ("+219 200 ₸"), so the direction needs no word. */
  signed?: boolean
  children: ReactNode
}) {
  const tone = good === null ? 'text-ink-muted' : good ? 'text-income' : 'text-expense'
  const Icon = direction > 0 ? TrendUpIcon : direction < 0 ? TrendDownIcon : TrendFlatIcon
  return (
    <b className={`inline-flex items-center gap-[3px] font-semibold tabular-nums ${tone}`}>
      <Icon className="size-3.5" strokeWidth={2.2} />
      {signed ? null : <span className="sr-only">{direction > 0 ? 'Up' : direction < 0 ? 'Down' : 'No change,'} </span>}
      {children}
    </b>
  )
}
