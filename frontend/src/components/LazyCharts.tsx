import { lazy, Suspense, type ReactNode } from 'react'

import type { CategoryBreakdown, MonthlyTrend } from '../api/client'
import { SERIES } from '../lib/chartColors'
import { Skeleton } from './ui'

// Recharts is the largest dependency, so it is loaded only when a chart is on screen.
const CashFlowChart = lazy(() => import('./MonthlyTrendChart').then((m) => ({ default: m.CashFlowChart })))
const NetBarsChart = lazy(() => import('./MonthlyTrendChart').then((m) => ({ default: m.NetBarsChart })))
const CategoryTreemap = lazy(() => import('./CategoryTreemap').then((m) => ({ default: m.CategoryTreemap })))

const trendIsEmpty = (trend: MonthlyTrend) =>
  trend.months.every((m) => m.income_cents === 0 && m.expense_cents === 0)

/** Legend in series order; kept outside the chart chunk so card headers can show it. */
export function ChartLegend({ net = false }: { net?: boolean }) {
  const items = [
    { label: 'Income', color: SERIES.income },
    { label: 'Expenses', color: SERIES.expense },
    ...(net ? [{ label: 'Net', color: SERIES.net, line: true }] : []),
  ]
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted" aria-label="Legend">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          {'line' in item ? (
            <span className="h-0.5 w-4" style={{ backgroundColor: item.color }} aria-hidden="true" />
          ) : (
            <span className="size-2.5 rounded-[2px]" style={{ backgroundColor: item.color }} aria-hidden="true" />
          )}
          {item.label}
        </li>
      ))}
    </ul>
  )
}

export function ChartSkeleton({ height = 'h-64' }: { height?: string }) {
  return (
    <div role="status" aria-label="Loading chart" className={`relative ${height}`}>
      <div className="absolute inset-0 flex flex-col justify-between py-2" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => <div key={i} className="border-t border-dashed border-line" />)}
      </div>
      <Skeleton className="absolute inset-x-0 bottom-0 h-1/2 rounded-md opacity-60" />
    </div>
  )
}

/** Plain empty state that keeps the chart's footprint, so the layout doesn't jump when data arrives. */
export function ChartEmpty({ title, description, action, height = 'h-40' }: {
  title: string
  description?: string
  action?: ReactNode
  height?: string
}) {
  return (
    <div className={`flex items-center justify-center ${height}`}>
      <div className="flex max-w-xs flex-col items-center gap-1 px-4 text-center">
        <p className="text-label font-medium text-ink">{title}</p>
        {description && <p className="text-label text-ink-subtle">{description}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  )
}

export function LazyCashFlowChart({ trend, height = 'h-72', showNet = true, emptyAction }: {
  trend: MonthlyTrend
  height?: string
  showNet?: boolean
  emptyAction?: ReactNode
}) {
  if (trendIsEmpty(trend)) {
    return (
      <ChartEmpty
        title="No cash flow yet"
        description="Monthly income and expenses will be charted here."
        action={emptyAction}
      />
    )
  }
  return (
    <Suspense fallback={<ChartSkeleton height={height} />}>
      <CashFlowChart trend={trend} height={height} showNet={showNet} />
    </Suspense>
  )
}

export function LazyNetBarsChart({ trend, height = 'h-52' }: { trend: MonthlyTrend; height?: string }) {
  if (trendIsEmpty(trend)) {
    return <ChartEmpty title="No monthly net yet" description="Each month's income minus expenses (from the server) appears here." />
  }
  return (
    <Suspense fallback={<ChartSkeleton height={height} />}>
      <NetBarsChart trend={trend} height={height} />
    </Suspense>
  )
}


export function LazyCategoryTreemap({ breakdown, height = 'h-56' }: { breakdown: CategoryBreakdown; height?: string }) {
  return (
    <Suspense fallback={<Skeleton className={`w-full rounded-[var(--radius-control)] ${height}`} />}>
      <CategoryTreemap breakdown={breakdown} height={height} />
    </Suspense>
  )
}
