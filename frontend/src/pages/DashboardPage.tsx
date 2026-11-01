import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import type { Summary } from '../api/client'
import { useCategoryBreakdown, useMonthlyTrend, useSummary, useTransactions } from '../api/queries'
import { CategorySplit } from '../components/CategoryBreakdownList'
import { ArrowRightIcon, ChevronLeftIcon, ChevronRightIcon, PlusIcon } from '../components/icons'
import { ChartLegend, ChartSkeleton, LazyCashFlowChart } from '../components/LazyCharts'
import { Sparkline } from '../components/Sparkline'
import { TransactionTable } from '../components/TransactionList'
import { Button, EmptyState, ErrorState, InlineError, linkClass, MiniBars, Section, Skeleton, SkeletonRows, SplitBar } from '../components/ui'
import { ON_DARK, SERIES } from '../lib/chartColors'
import { endOfMonth, formatMonth, toIsoDate } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { cardClass, labelClass } from '../lib/styles'
import { transactionCount } from '../lib/text'
import { useTransactionDialog } from '../lib/transactionDialog'

type SummaryQuery = { data?: Summary; isError: boolean; error: unknown; refetch: () => unknown }

function monthRange(start: Date) {
  return { date_from: toIsoDate(start), date_to: toIsoDate(endOfMonth(start)) }
}

/** Large figure with a smaller, quieter currency sign. Formatting only. */
function Figure({ cents, signClassName = 'text-ink-subtle' }: { cents: number; signClassName?: string }) {
  const amount = formatKzt(cents).replace(/\s₸$/, '')
  return (
    <span className="tabular-nums">
      {amount}
      <span className={`ml-[0.15em] text-[0.5em] font-medium ${signClassName}`}>₸</span>
    </span>
  )
}

export function DashboardPage() {
  const openTransaction = useTransactionDialog()
  const [now] = useState(() => new Date()) // captured once, so renders stay pure
  const [offset, setOffset] = useState(0) // 0 = this month, -1 = last month, …

  const start = new Date(now.getFullYear(), now.getMonth() + offset, 1)
  const previousStart = new Date(start.getFullYear(), start.getMonth() - 1, 1)
  const range = monthRange(start)
  const monthName = start.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
  const monthShort = start.toLocaleDateString('en-GB', { month: 'short' })
  const previousShort = previousStart.toLocaleDateString('en-GB', { month: 'short' })

  const allTime = useSummary()
  const month = useSummary(range)
  const previous = useSummary(monthRange(previousStart))
  const trend = useMonthlyTrend({ months: 6 })
  const expenses = useCategoryBreakdown({ type: 'expense', ...range })
  const recent = useTransactions({ limit: 8 })

  const today = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

  return (
    <>
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-title text-ink">Overview</h1>
          <p className="mt-1 text-sm text-ink-muted">{today}</p>
        </div>
        <MonthSelector label={monthName} onPrevious={() => setOffset((o) => o - 1)} onNext={() => setOffset((o) => o + 1)} canGoNext={offset < 0} />
      </div>

      {/* Hero: balance anchor + solid income/expense cards + net savings */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-12">
        <BalanceCard
          query={allTime}
          month={month}
          previous={previous}
          monthShort={monthShort}
          previousShort={previousShort}
          trendValues={trend.data?.months.map((m) => m.net_cents)}
          trendLabels={trend.data?.months.map((m) => formatMonth(m.month, true))}
          trendFailed={trend.isError}
        />
        <SolidCard
          tone="income"
          label="Money in"
          query={month}
          value={month.data?.total_income_cents}
          period={monthName}
          history={trend.data?.months.map((m) => m.income_cents)}
          historyFailed={trend.isError}
        />
        <SolidCard
          tone="expense"
          label="Money out"
          query={month}
          value={month.data?.total_expense_cents}
          period={monthName}
          history={trend.data?.months.map((m) => m.expense_cents)}
          historyFailed={trend.isError}
        />
        <NetCard query={month} monthName={monthName} />
      </div>

      {/* Cash flow and spending share one panel, split by a hairline. */}
      <div className={`${cardClass} mt-4 grid grid-cols-1 divide-y divide-line xl:grid-cols-12 xl:divide-x xl:divide-y-0`}>
        <PanelSection title="Cash flow" subtitle="Income, expenses and net · last 6 months" action={<ChartLegend net />} className="xl:col-span-8">
          {trend.isError ? (
            <ErrorState error={trend.error} onRetry={() => trend.refetch()} />
          ) : trend.isPending ? (
            <ChartSkeleton height="h-72 xl:h-[25rem]" />
          ) : (
            <LazyCashFlowChart
              trend={trend.data}
              height="h-72 xl:h-[25rem]"
              emptyAction={<Button size="sm" onClick={() => openTransaction()}><PlusIcon /> Add transaction</Button>}
            />
          )}
        </PanelSection>

        <PanelSection
          title="Spending by category"
          subtitle={monthName}
          action={<Link to="/analytics" className={linkClass}>Analytics <ArrowRightIcon className="size-3.5" /></Link>}
          className="xl:col-span-4"
        >
          {expenses.isError ? (
            <ErrorState error={expenses.error} onRetry={() => expenses.refetch()} />
          ) : expenses.isPending ? (
            <div role="status" aria-label="Loading spending" className="flex flex-col gap-4">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-48 w-full rounded-[var(--radius-control)]" />
              <SkeletonRows rows={3} label="Loading spending" />
            </div>
          ) : (
            <CategorySplit breakdown={expenses.data} limit={4} />
          )}
        </PanelSection>
      </div>

      <Section
        title="Recent transactions"
        className="mt-10"
        action={<Link to="/transactions" className={linkClass}>All transactions <ArrowRightIcon className="size-3.5" /></Link>}
      >
        {recent.isError ? (
          <ErrorState error={recent.error} onRetry={() => recent.refetch()} />
        ) : recent.isPending ? (
          <SkeletonRows rows={5} label="Loading recent transactions" />
        ) : recent.data.items.length === 0 ? (
          <div className="border-y border-line">
            <EmptyState
              title="No transactions yet"
              action={<Button size="sm" onClick={() => openTransaction()}><PlusIcon /> Add transaction</Button>}
            />
          </div>
        ) : (
          <TransactionTable
            caption="Recent transactions"
            layout="open"
            transactions={recent.data.items}
            onEdit={(transaction) => openTransaction({ transaction })}
          />
        )}
      </Section>
    </>
  )
}

/** One half of a shared panel: heading row and body, no box of its own. */
function PanelSection({ title, subtitle, action, children, className = '' }: {
  title: string
  subtitle: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  const id = `panel-${title.toLowerCase().replace(/\W+/g, '-')}`
  return (
    <section aria-labelledby={id} className={`min-w-0 p-5 lg:p-6 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h2 id={id} className="text-heading text-ink">{title}</h2>
          <p className="mt-0.5 text-label text-ink-subtle">{subtitle}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function MonthSelector({ label, onPrevious, onNext, canGoNext }: {
  label: string
  onPrevious: () => void
  onNext: () => void
  canGoNext: boolean
}) {
  const arrow =
    'grid h-full w-9 place-items-center text-ink-subtle transition-colors hover:bg-surface-raised hover:text-ink focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent'
  return (
    <div className="inline-flex h-9 items-stretch self-start overflow-hidden rounded-[var(--radius-control)] border border-line-strong sm:self-auto" role="group" aria-label="Month">
      <button type="button" onClick={onPrevious} aria-label="Previous month" className={arrow}>
        <ChevronLeftIcon />
      </button>
      <span className="flex min-w-36 items-center justify-center border-x border-line-strong px-3 text-label font-medium text-ink tabular-nums" aria-live="polite">
        {label}
      </span>
      <button type="button" onClick={onNext} disabled={!canGoNext} aria-label="Next month" className={arrow}>
        <ChevronRightIcon />
      </button>
    </div>
  )
}

/** The anchor: all-time balance, with real supporting figures only. */
function BalanceCard({ query, month, previous, monthShort, previousShort, trendValues, trendLabels, trendFailed }: {
  query: SummaryQuery
  month: SummaryQuery
  previous: SummaryQuery
  monthShort: string
  previousShort: string
  trendValues?: number[]
  trendLabels?: string[]
  trendFailed: boolean
}) {
  const data = query.data
  return (
    <section
      aria-labelledby="balance-heading"
      className={`${cardClass} flex flex-col p-6 sm:col-span-2 lg:col-span-7 lg:row-span-2 lg:p-7 xl:col-span-6`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="balance-heading" className="text-label font-medium text-ink-muted">Total balance</h2>
        <span className="text-xs text-ink-subtle">All time</span>
      </div>

      <div className="mt-5">
        {query.isError ? (
          <InlineError error={query.error} onRetry={() => query.refetch()} />
        ) : !data ? (
          <div role="status" aria-label="Loading balance" className="flex flex-col gap-3">
            <Skeleton className="h-14 w-3/4" />
            <Skeleton className="h-2 w-full" />
          </div>
        ) : (
          <>
            <p className={`text-figure-lg sm:text-display ${data.balance_cents < 0 ? 'text-expense' : 'text-ink'}`}>
              <Figure cents={data.balance_cents} />
            </p>
            <div className="mt-6">
              <SplitBar outCents={data.total_expense_cents} inCents={data.total_income_cents} size="md" />
            </div>
          </>
        )}
      </div>

      <div className="mt-7 flex-1">
        <p className={`${labelClass} mb-3`}>Monthly net, last 6 months</p>
        {trendValues ? (
          <>
            <Sparkline values={trendValues} color={SERIES.net} label="Monthly net, last 6 months" className="h-24 w-full text-ink-subtle" />
            <div className="mt-2 flex justify-between text-xs text-ink-subtle" aria-hidden="true">
              {trendLabels?.map((l, i) => <span key={i}>{l}</span>)}
            </div>
          </>
        ) : trendFailed ? (
          <p className="text-xs text-ink-subtle">History unavailable right now.</p>
        ) : (
          <Skeleton className="h-24 w-full" />
        )}
      </div>

      <dl className="mt-7 grid grid-cols-2 border-t border-line pt-5">
        {[
          { label: `${monthShort} net`, q: month },
          { label: `${previousShort} net`, q: previous },
        ].map(({ label, q }, i) => (
          <div key={label} className={i === 1 ? 'border-l border-line pl-5' : 'pr-5'}>
            <dt className={labelClass}>{label}</dt>
            <dd className="mt-1 text-lg font-medium tabular-nums">
              {q.isError ? (
                <span className="text-ink-subtle">—</span>
              ) : q.data ? (
                <span className={q.data.balance_cents < 0 ? 'text-expense' : 'text-income'}>
                  {q.data.balance_cents > 0 ? '+' : ''}
                  {formatKzt(q.data.balance_cents)}
                </span>
              ) : (
                <Skeleton className="mt-1 h-5 w-24" />
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** Solid emerald / coral KPI card with a 6-month column history (both from the backend). */
function SolidCard({ tone, label, query, value, period, history, historyFailed }: {
  tone: 'income' | 'expense'
  label: string
  query: SummaryQuery
  value?: number
  period: string
  history?: number[]
  historyFailed: boolean
}) {
  return (
    <section
      aria-label={`${label}, ${period}`}
      className={`flex min-h-48 flex-col rounded-[var(--radius-card)] p-5 text-white lg:col-span-5 xl:col-span-3 ${tone === 'income' ? 'bg-income-solid' : 'bg-expense-solid'}`}
    >
      <p className="text-label font-medium text-white/90">{label}</p>
      <div className="mt-4">
        {query.isError ? (
          <InlineError error={query.error} onRetry={() => query.refetch()} inverse />
        ) : value === undefined ? (
          <Skeleton className="h-9 w-2/3 bg-white/20" />
        ) : (
          <p className="text-figure-lg">
            <Figure cents={value} signClassName="text-white/90" />
          </p>
        )}
        <p className="mt-2 text-xs text-white/90">{period}</p>
      </div>
      <div className="mt-auto flex items-end justify-between gap-4 border-t border-white/15 pt-4">
        <span className="text-xs whitespace-nowrap text-white/90">Last 6 months</span>
        {history ? (
          <MiniBars values={history} color={ON_DARK} label={`${label}, last 6 months`} className="h-9 w-28" restOpacity={0.32} lastOpacity={0.9} />
        ) : historyFailed ? (
          <span className="text-xs text-white/90">Unavailable</span>
        ) : (
          <Skeleton className="h-9 w-28 bg-white/20" />
        )}
      </div>
    </section>
  )
}

function NetCard({ query, monthName }: { query: SummaryQuery; monthName: string }) {
  const data = query.data
  return (
    <section
      aria-label={`Net savings, ${monthName}`}
      className={`${cardClass} flex flex-col gap-6 p-5 sm:col-span-2 sm:flex-row sm:items-center sm:gap-10 lg:col-span-12 xl:col-span-6`}
    >
      <div className="min-w-0 shrink-0 sm:w-60">
        <p className="text-label font-medium text-ink-muted">Net savings</p>
        {query.isError ? (
          <div className="mt-2"><InlineError error={query.error} onRetry={() => query.refetch()} /></div>
        ) : !data ? (
          <Skeleton className="mt-2 h-9 w-40" />
        ) : (
          <p className={`mt-3 text-figure-lg ${data.balance_cents < 0 ? 'text-expense' : 'text-ink'}`}>
            <Figure cents={data.balance_cents} />
          </p>
        )}
        <p className="mt-2 text-xs leading-relaxed text-ink-subtle">
          Money in minus money out
          <br />
          {monthName}
          {data && ` · ${transactionCount(data.transaction_count)}`}
        </p>
      </div>
      <div className="min-w-0 flex-1">
        {data ? (
          <SplitBar outCents={data.total_expense_cents} inCents={data.total_income_cents} size="md" />
        ) : query.isError ? null : (
          <Skeleton className="h-6 w-full" />
        )}
      </div>
    </section>
  )
}
