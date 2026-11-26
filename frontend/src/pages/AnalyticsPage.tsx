import { useState } from 'react'

import type { CategoryBreakdown, MonthlyTrend, Summary } from '../api/client'
import { useCategoryBreakdown, useMonthlyTrend, useSummary } from '../api/queries'
import { CategorySplit } from '../components/CategoryBreakdownList'
import { ChartEmpty, ChartLegend, LazyCashFlowChart, LazyNetBarsChart, TrendQueryBody, type TrendQuery } from '../components/LazyCharts'
import { SummaryTiles } from '../components/SummaryTiles'
import { Card, ErrorState, PageHeader, Segmented, Skeleton, SkeletonRows } from '../components/ui'
import { SERIES } from '../lib/chartColors'
import { formatDateRange, formatMonthSpan, fromMonthKey, PERIODS, periodRange, trendWindow, type DateRange, type PeriodKey } from '../lib/dates'
import { formatKzt, formatSignedKzt } from '../lib/money'
import { cardClass, inputClass, labelClass } from '../lib/styles'
import { transactionCount } from '../lib/text'
import { useToday } from '../lib/useToday'

type Selection = PeriodKey | 'custom'

const PERIOD_OPTIONS: { value: Selection; label: string }[] = [
  ...PERIODS.map((period) => ({ value: period.key, label: period.label })),
  { value: 'custom', label: 'Custom' },
]

/** The cash-flow and net charts: always the last 12 months, whatever period is selected. */
const TREND_MONTHS = 12

/** Months listed one by one in "Income vs expenses" (longer periods have the net chart). */
const LISTED_MONTHS = 6

type BreakdownQuery = { data?: CategoryBreakdown; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }

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

/** The period's months that fall in the chart's window ("YYYY-MM", first and last), if any. */
function bandFor(range: DateRange, trend: MonthlyTrend | undefined): [string, string] | undefined {
  const months = trend?.months.map((m) => m.month) ?? []
  if (months.length === 0 || (!range.date_from && !range.date_to)) return undefined
  const first = range.date_from?.slice(0, 7) ?? months[0]
  const last = range.date_to?.slice(0, 7) ?? months[months.length - 1]
  const from = first > months[0] ? first : months[0]
  const to = last < months[months.length - 1] ? last : months[months.length - 1]
  return from <= to ? [from, to] : undefined
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
  const periodName = selection === 'custom' ? formatDateRange(range) : PERIOD_OPTIONS.find((option) => option.value === selection)?.label ?? ''
  // Both charts ask for the same 12 months, so they share one request; `until` keeps the window on
  // the browser's month, not the server's UTC one.
  const trend = useMonthlyTrend(trendWindow(today, TREND_MONTHS))

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Where your money came from and where it went, for any period."
        action={<Segmented label="Period" options={PERIOD_OPTIONS} value={selection} onChange={setSelection} />}
      />

      {selection === 'custom' && (
        <div className={`${cardClass} mb-3.5 flex flex-col gap-3 p-4 sm:flex-row sm:items-end lg:mb-[18px]`}>
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
          {invalidCustom && <p role="alert" className="text-xs font-medium text-danger sm:pb-3">“From” must be on or before “To”.</p>}
        </div>
      )}

      {invalidCustom ? (
        <CashFlowCard trend={trend} />
      ) : (
        <PeriodAnalytics range={range} periodLabel={periodLabel} periodName={periodName} trend={trend} />
      )}
    </>
  )
}

function PeriodAnalytics({ range, periodLabel, periodName, trend }: {
  range: DateRange
  /** "This month · 1–30 Nov 2026" */
  periodLabel: string
  /** "This month" */
  periodName: string
  trend: TrendQuery
}) {
  // Open and multi-month periods can show a comparison. Single months and all-time use totals only.
  const spansMonths = range.date_from?.slice(0, 7) !== range.date_to?.slice(0, 7)
  const summary = useSummary(spansMonths ? { ...range, include_monthly: true } : range)
  const expenses = useCategoryBreakdown({ type: 'expense', ...range })
  const income = useCategoryBreakdown({ type: 'income', ...range })
  const categories = (query: BreakdownQuery, kind: string) => {
    const n = query.data?.items.length
    return n === undefined ? null : `${n} ${kind} ${n === 1 ? 'category' : 'categories'}`
  }

  return (
    <div className="flex flex-col gap-3.5 lg:gap-[18px]">
      <SummaryTiles
        query={summary}
        period={periodLabel}
        notes={{
          net: 'Money in minus money out',
          income: categories(income, 'income'),
          expense: categories(expenses, 'expense'),
          count: formatDateRange(range),
        }}
      />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:gap-[18px] xl:grid-cols-4">
        <CashFlowCard trend={trend} band={bandFor(range, trend.data)} className="lg:col-span-2 xl:col-span-3" />
        <Comparison query={summary} />
        <BreakdownCard title="Spending by category" query={expenses} meta={periodName} className="xl:col-span-2" />
        <BreakdownCard title="Income by category" query={income} />
        <NetCard trend={trend} />
      </div>
    </div>
  )
}

function BreakdownCard({ title, query, meta, className = '' }: { title: string; query: BreakdownQuery; meta?: string; className?: string }) {
  return (
    <Card title={title} action={meta ? <span>{meta}</span> : undefined} className={className}>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending || !query.data ? (
        <div role="status" aria-label={`Loading ${title.toLowerCase()}`} className="flex flex-col gap-4">
          <Skeleton className="h-6 w-32" />
          <SkeletonRows rows={3} label={`Loading ${title.toLowerCase()}`} />
        </div>
      ) : (
        <CategorySplit breakdown={query.data} />
      )}
    </Card>
  )
}

/** "Last 12 months · Dec 2025 – Nov 2026", from the months the server actually returned. */
function windowLabel(trend: MonthlyTrend | undefined): string {
  const months = trend?.months ?? []
  const span = months.length > 0 ? ` · ${formatMonthSpan(months[0].month, months[months.length - 1].month)}` : ''
  return `Last ${TREND_MONTHS} months${span}`
}

/** Says, beside a rolling chart, that the period picker above doesn't apply to it. */
const rollingNote = <p className="text-xs text-ink-subtle">The period above doesn’t change this chart.</p>

/** The hero chart: 12 months of income and expenses, the selected period shaded. */
function CashFlowCard({ trend, band, className = '' }: { trend: TrendQuery; band?: [string, string]; className?: string }) {
  return (
    <Card
      title="Cash flow"
      subtitle={windowLabel(trend.data)}
      action={
        <>
          <ChartLegend />
          {band ? <span>Shaded months are your period</span> : null}
        </>
      }
      className={className}
    >
      <TrendQueryBody trend={trend} height="h-[250px]">
        {(data) => <LazyCashFlowChart trend={data} height="h-[250px]" band={band} summary={rollingNote} />}
      </TrendQueryBody>
    </Card>
  )
}

function NetCard({ trend }: { trend: TrendQuery }) {
  const label = windowLabel(trend.data)
  return (
    <Card title="Net by month" subtitle={label}>
      <div className="-mt-1 mb-1.5"><ChartLegend kind="net" /></div>
      <TrendQueryBody trend={trend} height="h-[170px]">
        {(data) => <LazyNetBarsChart trend={data} label={`Monthly net, ${label}`} height="h-[170px]" shortLabels />}
      </TrendQueryBody>
      <div className="mt-2">{rollingNote}</div>
    </Card>
  )
}

/**
 * Income against expenses for the period as two bars (widths are presentation only), each month's
 * net for short periods, and the period's net change. All values use the same date boundaries.
 */
function Comparison({ query }: {
  query: { data?: Summary; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }
}) {
  const data = query.data
  const largest = data ? Math.max(data.total_income_cents, data.total_expense_cents) : 0
  const rows = data
    ? [
        { label: 'Income', value: data.total_income_cents, color: SERIES.income },
        { label: 'Expenses', value: data.total_expense_cents, color: SERIES.expense },
      ]
    : []
  const months = data?.monthly_breakdown ?? []
  const listMonths = months.length > 1 && months.length <= LISTED_MONTHS
  return (
    <Card title="Income vs expenses">
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending || !data ? (
        <div role="status" aria-label="Loading comparison" className="flex flex-col gap-5 pt-1">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : data.transaction_count === 0 ? (
        <ChartEmpty height="h-56" title="Nothing to compare yet" description="No transactions in this period." />
      ) : (
        <div className="flex h-full flex-col gap-4">
          <ul className="flex flex-col gap-4">
            {rows.map((row) => (
              <li key={row.label}>
                <p className="mb-[7px] flex items-baseline justify-between gap-3 text-label text-ink-muted">
                  {row.label}
                  <span className="font-semibold text-ink tabular-nums">{formatKzt(row.value)}</span>
                </p>
                <div className="h-2.5 overflow-hidden rounded-full bg-surface-selected" aria-hidden="true">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${largest > 0 && row.value > 0 ? Math.max((row.value / largest) * 100, 1.5) : 0}%`, backgroundColor: row.color }}
                  />
                </div>
              </li>
            ))}
          </ul>
          {listMonths ? (
            <div className="border-t border-line pt-3">
              <p className="mb-1 text-xs text-ink-subtle">Net by month in this period</p>
              <dl>
                {months.map((m) => (
                  <div key={m.month} className="flex justify-between gap-3 py-[5px] text-label text-ink-muted">
                    <dt>{fromMonthKey(m.month).toLocaleDateString('en-GB', { month: 'long' })}</dt>
                    <dd className={`font-semibold tabular-nums ${m.net_cents > 0 ? 'text-income' : m.net_cents < 0 ? 'text-expense' : 'text-ink'}`}>
                      {formatSignedKzt(m.net_cents)}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
          <div className="mt-auto border-t border-line pt-3.5">
            <p className="text-xs text-ink-subtle">Net change · {transactionCount(data.transaction_count)}</p>
            <p className={`mt-1 text-figure tabular-nums ${data.balance_cents > 0 ? 'text-income' : data.balance_cents < 0 ? 'text-expense' : 'text-ink'}`}>
              {formatSignedKzt(data.balance_cents)}
            </p>
          </div>
        </div>
      )}
    </Card>
  )
}
