import { useState } from 'react'

import { useCategoryBreakdown, useMonthlyTrend, useSummary } from '../api/queries'
import { CategoryBreakdownList } from '../components/CategoryBreakdownList'
import { LazyMonthlyTrendChart } from '../components/LazyMonthlyTrendChart'
import { SummaryTiles } from '../components/SummaryTiles'
import { Card, ErrorState, LoadingState, PageHeader } from '../components/ui'
import { PERIODS, periodRange, type DateRange, type PeriodKey } from '../lib/dates'
import { inputClass } from '../lib/styles'

type Selection = PeriodKey | 'custom'

export function AnalyticsPage() {
  const [selection, setSelection] = useState<Selection>('this-month')
  const [custom, setCustom] = useState<Required<DateRange>>({ date_from: '', date_to: '' })

  const invalidCustom =
    selection === 'custom' && !!custom.date_from && !!custom.date_to && custom.date_from > custom.date_to
  const range: DateRange =
    selection === 'custom'
      ? { date_from: custom.date_from || undefined, date_to: custom.date_to || undefined }
      : periodRange(selection)

  return (
    <>
      <PageHeader title="Analytics" description="Where your money comes from and where it goes. All figures are calculated by the server." />

      <div className="mb-6 flex flex-col gap-3">
        <div role="group" aria-label="Period" className="flex flex-wrap gap-1.5">
          {[...PERIODS, { key: 'custom' as const, label: 'Custom' }].map((period) => (
            <button
              key={period.key}
              type="button"
              aria-pressed={selection === period.key}
              onClick={() => setSelection(period.key)}
              className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 ${
                selection === period.key
                  ? 'border-indigo-600 bg-indigo-600 text-white'
                  : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
              }`}
            >
              {period.label}
            </button>
          ))}
        </div>
        {selection === 'custom' && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex flex-col gap-1">
              <label htmlFor="a-from" className="text-xs font-medium text-slate-600">From</label>
              <input id="a-from" type="date" value={custom.date_from} aria-invalid={invalidCustom}
                onChange={(e) => setCustom({ ...custom, date_from: e.target.value })} className={inputClass(invalidCustom)} />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="a-to" className="text-xs font-medium text-slate-600">To</label>
              <input id="a-to" type="date" value={custom.date_to} aria-invalid={invalidCustom}
                onChange={(e) => setCustom({ ...custom, date_to: e.target.value })} className={inputClass(invalidCustom)} />
            </div>
            {invalidCustom && (
              <p role="alert" className="text-xs font-medium text-red-700 sm:pb-2.5">“From” must be on or before “To”.</p>
            )}
          </div>
        )}
      </div>

      {invalidCustom ? null : <PeriodAnalytics range={range} />}

      <Card title="Income vs expenses, last 12 months" className="mt-6">
        <TrendSection />
      </Card>
    </>
  )
}

function PeriodAnalytics({ range }: { range: DateRange }) {
  const summary = useSummary(range)
  const expenses = useCategoryBreakdown({ type: 'expense', ...range })
  const income = useCategoryBreakdown({ type: 'income', ...range })

  return (
    <div className="flex flex-col gap-6">
      {summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => summary.refetch()} />
      ) : summary.isPending ? (
        <LoadingState />
      ) : (
        <SummaryTiles summary={summary.data} />
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {([['Expenses by category', expenses], ['Income by category', income]] as const).map(([title, query]) => (
          <Card key={title} title={title}>
            {query.isError ? (
              <ErrorState error={query.error} onRetry={() => query.refetch()} />
            ) : query.isPending ? (
              <LoadingState />
            ) : (
              <CategoryBreakdownList breakdown={query.data} />
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}

function TrendSection() {
  const trend = useMonthlyTrend({ months: 12 })
  if (trend.isError) return <ErrorState error={trend.error} onRetry={() => trend.refetch()} />
  if (trend.isPending) return <LoadingState />
  return <LazyMonthlyTrendChart trend={trend.data} />
}
