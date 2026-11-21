import type { ReactNode } from 'react'

import { formatKzt, formatSignedKzt } from '../../lib/money'
import { ChartIcon } from '../icons'
import { ChartEmpty, ChartLegend, LazyCashFlowChart, LazyNetBarsChart, TrendQueryBody, type TrendQuery } from '../LazyCharts'
import { Card, Skeleton } from '../ui'
import type { SummaryQuery } from './parts'

const noCashFlow = (
  <ChartEmpty
    icon={<ChartIcon className="size-5" />}
    title="No cash flow yet"
    description="Add income or an expense to start the chart."
    height="h-44"
  />
)

/**
 * Income, expenses and net for the chart's months, from the backend's summary of that date range
 * (not added up here).
 */
function WindowTotals({ query }: { query: SummaryQuery }) {
  const data = query.data
  if (query.isError) return null
  const value = (render: (d: NonNullable<SummaryQuery['data']>) => ReactNode) => (data ? render(data) : <Skeleton className="h-4 w-20" />)
  const net = data?.balance_cents ?? 0
  return (
    <dl className="flex flex-wrap gap-x-[18px] gap-y-1 text-[12.5px] text-ink-subtle">
      <div className="flex items-center gap-1.5">
        <dt>Income</dt>
        <dd className="font-semibold text-ink tabular-nums">{value((d) => formatKzt(d.total_income_cents))}</dd>
      </div>
      <div className="flex items-center gap-1.5">
        <dt>Expenses</dt>
        <dd className="font-semibold text-ink tabular-nums">{value((d) => formatKzt(d.total_expense_cents))}</dd>
      </div>
      <div className="flex items-center gap-1.5">
        <dt>Net</dt>
        <dd className={`font-semibold tabular-nums ${net > 0 ? 'text-income' : net < 0 ? 'text-expense' : 'text-ink'}`}>
          {value((d) => formatSignedKzt(d.balance_cents))}
        </dd>
      </div>
    </dl>
  )
}

/** Six months of income and expenses ending with the shown month, which is highlighted. */
export function CashFlowCard({ trend, totals, historyLabel, highlight, className }: {
  trend: TrendQuery
  totals: SummaryQuery
  /** "6 months to Nov 2026" */
  historyLabel: string
  /** The shown month, "YYYY-MM". */
  highlight: string
  className?: string
}) {
  const height = 'h-[232px]'
  return (
    <Card
      title="Cash flow"
      action={
        <>
          <ChartLegend />
          <span>{historyLabel}</span>
        </>
      }
      className={className}
    >
      <TrendQueryBody trend={trend} height={height}>
        {(data) => (
          <LazyCashFlowChart trend={data} height={height} highlight={highlight} summary={<WindowTotals query={totals} />} empty={noCashFlow} />
        )}
      </TrendQueryBody>
    </Card>
  )
}

/** The same months' net, saved above the line and overspent below it. */
export function NetByMonthCard({ trend, historyLabel, highlight, className }: {
  trend: TrendQuery
  historyLabel: string
  highlight: string
  className?: string
}) {
  const height = 'h-[158px]'
  return (
    <Card title="Net by month" action={<ChartLegend kind="net" />} className={className}>
      <TrendQueryBody trend={trend} height={height}>
        {(data) => <LazyNetBarsChart trend={data} label={`Monthly net, ${historyLabel}`} height={height} highlight={highlight} />}
      </TrendQueryBody>
    </Card>
  )
}
