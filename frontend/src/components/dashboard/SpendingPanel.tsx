import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import type { CategoryBreakdown } from '../../api/client'
import { REST } from '../../lib/chartColors'
import { formatKzt } from '../../lib/money'
import { DonutTotal } from '../CategoryBreakdownList'
import { CategoryDonut, ShareRing } from '../CategoryDonut'
import { ArrowRightIcon, PieIcon } from '../icons'
import { ChartEmpty } from '../LazyCharts'
import { Card, ErrorState, linkClass, Skeleton, SkeletonRows } from '../ui'

/** How many categories the donut's legend names; Analytics has them all. */
const NAMED = 4
/** How many rings the top-categories card shows. */
const RINGS = 5

type BreakdownQuery = { data?: CategoryBreakdown; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }

const analyticsLink = (
  <Link to="/analytics" className={`${linkClass} min-h-8 pointer-coarse:min-h-11`}>
    Analytics <ArrowRightIcon className="size-3.5" />
  </Link>
)

/** A month without expenses; `action` is offered under the message. */
function NoSpending({ action }: { action?: ReactNode }) {
  return (
    <ChartEmpty
      icon={<PieIcon className="size-5" />}
      title="No spending in this period"
      description="When you add expenses, you’ll see which categories take the most."
      action={action}
      height="h-44"
    />
  )
}

/** The breakdown's loading, error and empty states; `children` once there is spending to show. */
function BreakdownBody({ query, loading, empty = <NoSpending />, children }: {
  query: BreakdownQuery
  loading: ReactNode
  empty?: ReactNode
  children: (breakdown: CategoryBreakdown) => ReactNode
}) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  if (query.isPending || !query.data) return loading
  if (query.data.items.length === 0) return empty
  return children(query.data)
}

/**
 * The month's spending: a ring with the total in the middle over the largest categories (backend
 * order, largest first) and their shares. Pointing at a row or an arc picks out the same category
 * in both.
 */
function Breakdown({ breakdown }: { breakdown: CategoryBreakdown }) {
  const [active, setActive] = useState<number | null>(null)
  const listed = breakdown.items.slice(0, NAMED)
  const more = breakdown.items.length - listed.length
  return (
    <div className="flex flex-col items-center">
      <CategoryDonut items={breakdown.items} total={breakdown.total_cents} named={NAMED} active={active} onActive={setActive} size="size-[150px] mt-1 mb-4">
        <DonutTotal cents={breakdown.total_cents} label="spent" />
      </CategoryDonut>
      <ul className="flex w-full flex-col gap-[9px]">
        {listed.map((item, i) => (
          <li
            key={item.category_id}
            onMouseEnter={() => setActive(i)}
            onMouseLeave={() => setActive(null)}
            className={`flex items-center gap-[9px] text-label text-ink-muted transition-opacity motion-reduce:transition-none ${active === null || active === i ? '' : 'opacity-45'}`}
          >
            <span className="size-[9px] shrink-0 rounded-full" style={{ backgroundColor: item.color }} aria-hidden="true" />
            <span className="min-w-0 truncate">{item.category_name}</span>
            <span className="ml-auto shrink-0 font-semibold text-ink tabular-nums">{item.percentage}%</span>
          </li>
        ))}
      </ul>
      <div className="mt-[3px] flex w-full items-center justify-between gap-3">
        {more > 0 ? (
          <p className="flex items-center gap-[9px] text-label text-ink-subtle">
            <span className="size-[9px] shrink-0 rounded-full" style={{ backgroundColor: REST }} aria-hidden="true" />
            {more} more
          </p>
        ) : null}
        <span className="ml-auto">{analyticsLink}</span>
      </div>
    </div>
  )
}

export function SpendingCard({ query, monthShort, className }: { query: BreakdownQuery; monthShort: string; className?: string }) {
  return (
    <Card title="Spending by category" action={<span>{monthShort}</span>} className={className}>
      {/* Analytics is linked whatever the month holds: it has every period and category. */}
      <BreakdownBody
        query={query}
        empty={<NoSpending action={analyticsLink} />}
        loading={
          <div role="status" aria-label="Loading spending" className="flex flex-col items-center gap-4">
            <div className="mt-1 size-[150px] animate-pulse rounded-full border-[16px] border-white/[0.06]" aria-hidden="true" />
            <div className="w-full"><SkeletonRows rows={4} label="Loading spending" /></div>
          </div>
        }
      >
        {(breakdown) => <Breakdown breakdown={breakdown} />}
      </BreakdownBody>
    </Card>
  )
}

/**
 * The month's largest categories, each as its share of the month's spending (a ring) with the
 * amount. Shares are the backend's; the ring shows them rounded, the text says them exactly.
 */
export function TopCategoriesCard({ query, monthLong, className }: { query: BreakdownQuery; monthLong: string; className?: string }) {
  return (
    <Card title="Top categories" action={<span>Share of {monthLong} spending</span>} className={className}>
      <BreakdownBody
        query={query}
        loading={
          <div role="status" aria-label="Loading top categories" className="grid grid-cols-3 gap-2 xl:grid-cols-5">
            {Array.from({ length: RINGS }, (_, i) => <Skeleton key={i} className="mx-auto size-[92px] rounded-full" />)}
          </div>
        }
      >
        {(breakdown) => (
          <ul className="grid grid-cols-3 gap-x-2 gap-y-4 xl:grid-cols-5">
            {breakdown.items.slice(0, RINGS).map((item) => (
              <li key={item.category_id} className="flex min-w-0 flex-col items-center gap-1.5 text-center">
                <ShareRing percentage={item.percentage}>
                  <span className="text-[17px] font-semibold text-ink tabular-nums" aria-hidden="true">{Math.round(item.percentage)}%</span>
                </ShareRing>
                <p className="text-label leading-tight font-medium text-ink">{item.category_name}</p>
                <p className="text-xs text-ink-subtle tabular-nums">
                  {formatKzt(item.total_cents)}
                  <span className="sr-only">, {item.percentage}%</span>
                </p>
              </li>
            ))}
          </ul>
        )}
      </BreakdownBody>
    </Card>
  )
}
