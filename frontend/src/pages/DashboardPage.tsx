import { useState } from 'react'

import { useCategoryBreakdown, useMonthlyTrend, useSummary, useTransactions } from '../api/queries'
import { CashFlowCard, NetByMonthCard } from '../components/dashboard/CashFlowPanel'
import { MoneyCard, NetSavingsCard, TotalBalanceCard, WelcomeCard, type MonthNames } from '../components/dashboard/MetricTiles'
import { MonthNavigator } from '../components/dashboard/MonthNavigator'
import { RecentActivity } from '../components/dashboard/RecentActivity'
import { SpendingCard, TopCategoriesCard } from '../components/dashboard/SpendingPanel'
import { PageHeader } from '../components/ui'
import { addMonths, endOfMonth, formatMonth, monthKey, shownMonth, stepMonth, toIsoDate, trendWindow } from '../lib/dates'
import { useTransactionDialog } from '../lib/transactionDialog'
import { useToday } from '../lib/useToday'

/** Length of the monthly history (cash flow, net by month). It ends with the shown month. */
const HISTORY_MONTHS = 6

/**
 * Where each card sits. Below lg, two columns in reading order (the balance and the net full
 * width). From lg, four columns: the cash flow full width, spending and top categories beside the
 * recent transactions, the net below. From xl, the reference layout: spending, cash flow and the
 * recent transactions in one row, top categories and the net under the first two.
 */
const PLACE = {
  balance: 'col-span-2 lg:col-span-1',
  kpi: 'lg:col-span-1',
  net: 'col-span-2 lg:col-span-1',
  welcome: 'col-span-2 lg:col-span-3',
  cashFlow: 'col-span-2 lg:col-span-4 lg:row-start-2 xl:col-span-2 xl:col-start-2',
  spending: 'col-span-2 lg:col-start-1 lg:row-start-3 xl:col-span-1 xl:row-start-2',
  top: 'col-span-2 lg:col-start-1 lg:row-start-4 xl:row-start-3',
  netByMonth: 'col-span-2 lg:col-span-4 lg:row-start-5 xl:col-span-1 xl:col-start-3 xl:row-start-3',
  recent: 'col-span-2 lg:col-start-3 lg:row-span-2 lg:row-start-3 xl:col-span-1 xl:col-start-4 xl:row-start-2',
}
/** A new account has no top categories or net yet: the recent list only spans the one row. */
const FIRST_RUN_RECENT = 'col-span-2 lg:col-start-3 lg:row-start-3 xl:col-span-1 xl:col-start-4 xl:row-start-2'

function dateRange(first: Date, last: Date) {
  return { date_from: toIsoDate(first), date_to: toIsoDate(endOfMonth(last)) }
}

/**
 * The Overview: the all-time balance and the shown month's money in, money out and net across the
 * top; then the cash flow and net of the six months to it, its spending by category and the latest
 * transactions. A new account sees the first steps in place of the month's figures. Every figure
 * comes from the backend; this page only chooses the month and lays the cards out.
 */
export function DashboardPage() {
  const openTransaction = useTransactionDialog()
  const today = useToday() // moves on at midnight, so a tab left open never shows yesterday
  // The month the user went back to ("YYYY-MM"), or null for the current month.
  const [selected, setSelected] = useState<string | null>(null)

  const start = shownMonth(selected, today)
  const previousStart = addMonths(start, -1)
  const historyStart = addMonths(start, -(HISTORY_MONTHS - 1))
  const highlight = monthKey(start)
  const names: MonthNames = {
    full: start.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' }),
    long: start.toLocaleDateString('en-GB', { month: 'long' }),
    short: start.toLocaleDateString('en-GB', { month: 'short' }),
    previousShort: previousStart.toLocaleDateString('en-GB', { month: 'short' }),
    isCurrent: highlight === monthKey(today),
  }
  const historyLabel = `${HISTORY_MONTHS} months to ${formatMonth(highlight)}`

  const allTime = useSummary()
  const month = useSummary(dateRange(start, start))
  const previous = useSummary(dateRange(previousStart, previousStart))
  const historyTotals = useSummary(dateRange(historyStart, start))
  const trend = useMonthlyTrend(trendWindow(start, HISTORY_MONTHS))
  const expenses = useCategoryBreakdown({ type: 'expense', ...dateRange(start, start) })
  const recent = useTransactions({ limit: 8 })

  const isNewAccount = allTime.data?.transaction_count === 0
  const todayLong = today.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  const todayShort = today.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

  return (
    <>
      <PageHeader
        title="Overview"
        eyebrow={todayLong}
        action={
          <div className="flex w-full flex-wrap items-center justify-between gap-2.5 lg:w-auto">
            <p className="text-label text-ink-subtle lg:hidden">{todayShort}</p>
            <MonthNavigator
              label={names.full}
              onPrevious={() => setSelected((current) => stepMonth(current, today, -1))}
              onNext={() => setSelected((current) => stepMonth(current, today, 1))}
              onCurrent={() => setSelected(null)}
              canGoNext={!names.isCurrent}
            />
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-[18px] xl:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.3fr)]">
        <TotalBalanceCard allTime={allTime} month={month} names={names} className={PLACE.balance} />
        {isNewAccount ? (
          <WelcomeCard onAdd={(type) => openTransaction({ type })} className={PLACE.welcome} />
        ) : (
          <>
            <MoneyCard kind="income" month={month} previous={previous} names={names} className={PLACE.kpi} />
            <MoneyCard kind="expense" month={month} previous={previous} names={names} className={PLACE.kpi} />
            <NetSavingsCard month={month} names={names} className={PLACE.net} />
          </>
        )}

        <CashFlowCard trend={trend} totals={historyTotals} historyLabel={historyLabel} highlight={highlight} className={PLACE.cashFlow} />
        <SpendingCard query={expenses} monthShort={names.short} className={PLACE.spending} />
        {isNewAccount ? null : (
          <>
            <TopCategoriesCard query={expenses} monthLong={names.long} className={PLACE.top} />
            <NetByMonthCard trend={trend} historyLabel={historyLabel} highlight={highlight} className={PLACE.netByMonth} />
          </>
        )}
        <RecentActivity
          query={recent}
          today={today}
          onEdit={(transaction) => openTransaction({ transaction })}
          className={isNewAccount ? FIRST_RUN_RECENT : PLACE.recent}
        />
      </div>
    </>
  )
}
