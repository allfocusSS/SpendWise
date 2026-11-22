import { useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, type ComponentType, type ReactNode } from 'react'

import type { MonthlyTrend } from '../api/client'
import { SERIES } from '../lib/chartColors'
import { retryableLoader } from '../lib/recovery'
import { ChartErrorFallback, ErrorBoundary } from './ErrorBoundary'
import { EmptyIcon, ErrorState, Skeleton } from './ui'

/**
 * A lazily loaded chart whose import can be tried again: React.lazy keeps a failed import's error
 * for good, so `retry()` swaps in a new lazy component (only after a failure).
 */
function retryableLazy<P extends object>(load: () => Promise<ComponentType<P>>) {
  const loader = retryableLoader(load)
  const create = () => lazy(async () => ({ default: await loader.load() }))
  let Loaded = create()
  return {
    Chart: (props: P) => <Loaded {...props} />,
    retry: () => {
      if (loader.retry()) Loaded = create()
    },
  }
}

// Recharts is the largest dependency, so it is loaded only when a chart is on screen.
const cashFlow = retryableLazy(() => import('./MonthlyTrendChart').then((m) => m.CashFlowChart))
const netBars = retryableLazy(() => import('./MonthlyTrendChart').then((m) => m.NetBarsChart))

/**
 * One chart's boundary: a chart that fails to load or throws shows a fallback at its own height,
 * and the rest of the card and the page keep working. "Try again" loads the chart again with
 * fresh figures, since a chart that threw may have been given bad data.
 */
function ChartBoundary({ chart, height, children }: { chart: { retry: () => void }; height: string; children: ReactNode }) {
  const client = useQueryClient()
  return (
    <ErrorBoundary
      name="chart"
      onRetry={() => {
        chart.retry()
        return client.resetQueries({ queryKey: ['analytics'] })
      }}
      fallback={(props) => <ChartErrorFallback {...props} height={height} />}
    >
      <Suspense fallback={<ChartSkeleton height={height} />}>{children}</Suspense>
    </ErrorBoundary>
  )
}

/** What a chart card needs from a monthly-trend query (React Query's result fits it). */
export type TrendQuery = { data?: MonthlyTrend; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }

/** A trend query's loading and error states at the chart's height; `children` once the data is there. */
export function TrendQueryBody({ trend, height, children }: {
  trend: TrendQuery
  height: string
  children: (data: MonthlyTrend) => ReactNode
}) {
  if (trend.isError) {
    return (
      <div className={`flex items-center ${height}`}>
        <div className="w-full"><ErrorState error={trend.error} onRetry={() => trend.refetch()} /></div>
      </div>
    )
  }
  if (trend.isPending || !trend.data) return <ChartSkeleton height={height} />
  return children(trend.data)
}

const trendIsEmpty = (trend: MonthlyTrend) =>
  trend.months.every((m) => m.income_cents === 0 && m.expense_cents === 0)

const LEGENDS = {
  flow: [
    { label: 'Expenses', color: SERIES.expense },
    { label: 'Income', color: SERIES.income },
  ],
  net: [
    { label: 'Saved', color: SERIES.income },
    { label: 'Overspent', color: SERIES.expense },
  ],
}

/** Legend for the cash-flow areas or the net bars; kept outside the chart chunk so card headers can show it. */
export function ChartLegend({ kind = 'flow' }: { kind?: keyof typeof LEGENDS }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-muted" aria-label="Legend">
      {LEGENDS[kind].map((item) => (
        <li key={item.label} className="flex items-center gap-[7px]">
          <span className="size-[9px] rounded-full" style={{ backgroundColor: item.color }} aria-hidden="true" />
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
export function ChartEmpty({ title, description, action, icon, height = 'h-40' }: {
  title: string
  description?: string
  action?: ReactNode
  /** Optional decorative icon above the title. */
  icon?: ReactNode
  height?: string
}) {
  return (
    <div className={`flex items-center justify-center ${height}`}>
      <div className="flex max-w-xs flex-col items-center gap-1 px-4 text-center">
        {icon ? <EmptyIcon>{icon}</EmptyIcon> : null}
        <p className="text-label font-medium text-ink">{title}</p>
        {description && <p className="text-label text-ink-subtle">{description}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  )
}

export function LazyCashFlowChart({ trend, height = 'h-72', highlight, band, summary, empty }: {
  trend: MonthlyTrend
  height?: string
  /** A month ("YYYY-MM") to emphasise, e.g. the one the page is showing. */
  highlight?: string
  /** First and last month ("YYYY-MM") of a period to shade, e.g. the Analytics period. */
  band?: [string, string]
  /** Shown under the chart, beside the table toggle. */
  summary?: ReactNode
  /** Shown instead of the chart when no month has any income or expenses. */
  empty?: ReactNode
}) {
  if (trendIsEmpty(trend)) {
    return empty ?? <ChartEmpty title="No cash flow yet" description="Add income or an expense to start the chart." />
  }
  return (
    <ChartBoundary chart={cashFlow} height={height}>
      <cashFlow.Chart trend={trend} height={height} highlight={highlight} band={band} summary={summary} />
    </ChartBoundary>
  )
}

export function LazyNetBarsChart({ trend, label, height = 'h-40', highlight, shortLabels }: {
  trend: MonthlyTrend
  /** What the bars show, for screen readers ("Monthly net, 6 months to Nov 2026"). */
  label: string
  height?: string
  highlight?: string
  shortLabels?: boolean
}) {
  if (trendIsEmpty(trend)) {
    return <ChartEmpty title="No monthly net yet" description="Once a month has income or expenses, you’ll see whether you saved or overspent." height={height} />
  }
  return (
    <ChartBoundary chart={netBars} height={height}>
      <netBars.Chart trend={trend} label={label} height={height} highlight={highlight} shortLabels={shortLabels} />
    </ChartBoundary>
  )
}
