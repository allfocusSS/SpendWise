import { useState } from 'react'

import type { MonthlyTrend, Summary } from '../api/client'
import { useCategoryBreakdown, useMonthlyTrend, useSummary } from '../api/queries'
import { CategorySplit } from '../components/CategoryBreakdownList'
import { ChartEmpty, ChartLegend, ChartSkeleton, LazyCashFlowChart, LazyNetBarsChart } from '../components/LazyCharts'
import { SummaryTiles } from '../components/SummaryTiles'
import { Card, ErrorState, PageHeader, Segmented, Skeleton, SkeletonRows } from '../components/ui'
import { SERIES } from '../lib/chartColors'
import { formatDateRange, formatMonthSpan, PERIODS, periodRange, trendWindow, type DateRange, type PeriodKey } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { cardClass, labelClass, inputClass } from '../lib/styles'
import { transactionCount } from '../lib/text'
import { useToday } from '../lib/useToday'

type Selection = PeriodKey | 'custom'

const PERIOD_OPTIONS: { value: Selection; label: string }[] = [
  ...PERIODS.map((period) => ({ value: period.key, label: period.label })),
  { value: 'custom', label: 'Custom' },
]

/** The cash-flow and net charts: always the last 12 months, whatever period is selected. */
const TREND_MONTHS = 12

/**
 * What the figures cover, with the exact dates sent to the API: "This month · 1–30 Nov 2026",
 * "1 Mar – 30 Apr 2026", "From 1 Mar 2026", or "All time" (also for a custom range without dates,
 * which the API answers for all time).
 */
function periodLabelFor(selection: Selection, range: DateRange): string {
  if (selection === 'custom' || selection === 'all-time') return formatDateRange(range)
  const name = PERIOD_OPTIONS.find((option) => option.value === selection)?.label ?? ''
  return `${name} · ${formatDateRange(range)}`
}

export function AnalyticsPage() {
  const today = useToday() // "This month" moves on at midnight in a tab left open
  const [selection, setSelection] = useState<Selection>('this-month')
  const [custom, setCustom] = useState<Required<DateRange>>({ date_from: '', date_to: '' })

  const invalidCustom =
    selection === 'custom' && !!custom.date_from && !!custom.date_to && custom.date_from > custom.date_to
  const range: DateRange =
    selection === 'custom'
      ? { date_from: custom.date_from || undefined, date_to: custom.date_to || undefined }
      : periodRange(selection, today)
  const periodLabel = periodLabelFor(selection, range)

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Where your money comes from and where it goes. Every figure is calculated by the server."
        action={<Segmented label="Period" options={PERIOD_OPTIONS} value={selection} onChange={setSelection} />}
      />

      {selection === 'custom' && (
        <div className={`${cardClass} mb-4 flex flex-col gap-3 p-4 sm:flex-row sm:items-end`}>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="a-from" className={labelClass}>From</label>
            <input id="a-from" type="date" value={custom.date_from} aria-invalid={invalidCustom}
              onChange={(e) => setCustom({ ...custom, date_from: e.target.value })} className={inputClass(invalidCustom)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="a-to" className={labelClass}>To</label>
            <input id="a-to" type="date" value={custom.date_to} aria-invalid={invalidCustom}
              onChange={(e) => setCustom({ ...custom, date_to: e.target.value })} className={inputClass(invalidCustom)} />
          </div>
          {invalidCustom && <p role="alert" className="text-xs font-medium text-expense sm:pb-2.5">“From” must be on or before “To”.</p>}
        </div>
      )}

      {invalidCustom ? (
        <TrendSection today={today} />
      ) : (
        <PeriodAnalytics range={range} periodLabel={periodLabel} today={today} />
      )}
    </>
  )
}

function PeriodAnalytics({ range, periodLabel, today }: { range: DateRange; periodLabel: string; today: Date }) {
  const summary = useSummary(range)
  const expenses = useCategoryBreakdown({ type: 'expense', ...range })
  const income = useCategoryBreakdown({ type: 'income', ...range })

  return (
    <div className="flex flex-col gap-4">
      <SummaryTiles query={summary} period={periodLabel} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <TrendSection today={today} />
        </div>
        <Comparison query={summary} periodLabel={periodLabel} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {(
          [
            ['Spending by category', expenses, 'xl:col-span-7', 'wide'],
            ['Income by category', income, 'xl:col-span-5', 'stacked'],
          ] as const
        ).map(([title, query, span, layout]) => (
          <Card key={title} title={title} subtitle={periodLabel} className={span}>
            {query.isError ? (
              <ErrorState error={query.error} onRetry={() => query.refetch()} />
            ) : query.isPending ? (
              <div role="status" aria-label={`Loading ${title.toLowerCase()}`} className="flex flex-col gap-4">
                <Skeleton className="h-6 w-32" />
                <Skeleton className="h-2.5 w-full" />
                <SkeletonRows rows={3} label={`Loading ${title.toLowerCase()}`} />
              </div>
            ) : (
              <CategorySplit breakdown={query.data} layout={layout} limit={layout === 'stacked' ? 5 : undefined} treemapHeight={layout === 'wide' ? 'h-60' : 'h-48'} />
            )}
          </Card>
        ))}
      </div>

      <NetSection today={today} />
    </div>
  )
}

/**
 * The last 12 months to the browser's current month. Both charts ask for the same window, so they
 * share one request; `until` keeps it on the local month, not the server's UTC one.
 */
function useRollingTrend(today: Date) {
  return useMonthlyTrend(trendWindow(today, TREND_MONTHS))
}

/** "Last 12 months · Dec 2025 – Nov 2026", from the months the server actually returned. */
function windowLabel(trend: MonthlyTrend | undefined): string {
  const months = trend?.months ?? []
  const span = months.length > 0 ? ` · ${formatMonthSpan(months[0].month, months[months.length - 1].month)}` : ''
  return `Last ${TREND_MONTHS} months${span}`
}

/** Says, under a rolling chart, that the period picker above doesn't apply to it. */
function RollingNote() {
  return <p className="mb-2 text-xs text-ink-subtle">Not affected by the period selected above.</p>
}

/** Hero chart: 12 months of income and expenses with the net line. */
function TrendSection({ today }: { today: Date }) {
  const trend = useRollingTrend(today)
  return (
    <Card title="Cash flow" subtitle={windowLabel(trend.data)} action={<ChartLegend net />} className="h-full">
      <RollingNote />
      {trend.isError ? (
        <ErrorState error={trend.error} onRetry={() => trend.refetch()} />
      ) : trend.isPending ? (
        <ChartSkeleton height="h-72" />
      ) : (
        <LazyCashFlowChart trend={trend.data} height="h-72" showNet />
      )}
    </Card>
  )
}

function NetSection({ today }: { today: Date }) {
  const trend = useRollingTrend(today)
  return (
    <Card title="Net by month" subtitle={windowLabel(trend.data)}>
      <RollingNote />
      {trend.isError ? (
        <ErrorState error={trend.error} onRetry={() => trend.refetch()} />
      ) : trend.isPending ? (
        <ChartSkeleton height="h-52" />
      ) : (
        <LazyNetBarsChart trend={trend.data} />
      )}
    </Card>
  )
}

/** Income vs expenses for the period as two proportional bars (widths are presentation only). */
function Comparison({ query, periodLabel }: {
  query: { data?: Summary; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }
  periodLabel: string
}) {
  const data = query.data
  const largest = data ? Math.max(data.total_income_cents, data.total_expense_cents) : 0
  const rows = data
    ? [
        { label: 'Income', value: data.total_income_cents, color: SERIES.income },
        { label: 'Expenses', value: data.total_expense_cents, color: SERIES.expense },
      ]
    : []
  return (
    <Card title="Income vs expenses" subtitle={periodLabel} className="xl:col-span-4">
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending || !data ? (
        <div role="status" aria-label="Loading comparison" className="flex flex-col gap-5 pt-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : data.transaction_count === 0 ? (
        <ChartEmpty height="h-56" title="Nothing to compare yet" description="No transactions in this period." />
      ) : (
        <div className="flex h-full flex-col">
          <ul className="flex flex-col gap-5 pt-2">
            {rows.map((row) => (
              <li key={row.label}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className={`${labelClass} flex items-center gap-2`}>
                    <span className="size-2 rounded-[2px]" style={{ backgroundColor: row.color }} aria-hidden="true" />
                    {row.label}
                  </span>
                  <span className="text-xl font-semibold tracking-tight tabular-nums text-ink">{formatKzt(row.value)}</span>
                </div>
                <div className="mt-2 h-3 w-full rounded-sm bg-ink/[0.05]" aria-hidden="true">
                  <div
                    className="h-3 rounded-sm"
                    style={{ width: `${largest > 0 && row.value > 0 ? Math.max((row.value / largest) * 100, 1.5) : 0}%`, backgroundColor: row.color }}
                  />
                </div>
              </li>
            ))}
          </ul>
          <dl className="mt-auto grid grid-cols-2 gap-4 border-t border-line pt-4">
            <div>
              <dt className={labelClass}>Net</dt>
              <dd className={`mt-1 text-lg font-semibold tabular-nums ${data.balance_cents < 0 ? 'text-expense' : 'text-ink'}`}>
                {formatKzt(data.balance_cents)}
              </dd>
            </div>
            <div>
              <dt className={labelClass}>Activity</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums text-ink">{transactionCount(data.transaction_count)}</dd>
            </div>
          </dl>
        </div>
      )}
    </Card>
  )
}
