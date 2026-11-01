import { useState } from 'react'
import { Link } from 'react-router'

import type { Transaction } from '../api/client'
import { useCategoryBreakdown, useMonthlyTrend, useSummary, useTransactions } from '../api/queries'
import { CategoryBreakdownList } from '../components/CategoryBreakdownList'
import { PlusIcon } from '../components/icons'
import { LazyMonthlyTrendChart } from '../components/LazyMonthlyTrendChart'
import { SummaryTiles } from '../components/SummaryTiles'
import { TransactionDialog } from '../components/TransactionDialog'
import { TransactionList } from '../components/TransactionList'
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader } from '../components/ui'
import { periodRange } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { cardClass } from '../lib/styles'

export function DashboardPage() {
  const [dialog, setDialog] = useState<{ open: boolean; transaction: Transaction | null }>({
    open: false,
    transaction: null,
  })
  const [now] = useState(() => new Date()) // captured once, so renders stay pure
  const thisMonth = periodRange('this-month', now)
  const monthName = now.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })

  const allTime = useSummary()
  const month = useSummary(thisMonth)
  const trend = useMonthlyTrend({ months: 6 })
  const topExpenses = useCategoryBreakdown({ type: 'expense', ...thisMonth })
  const recent = useTransactions({ limit: 5 })

  const openAdd = () => setDialog({ open: true, transaction: null })
  const addButton = (
    <Button onClick={openAdd}>
      <PlusIcon /> Add transaction
    </Button>
  )

  return (
    <>
      <PageHeader title="Dashboard" description={`Overview for ${monthName}`} action={addButton} />

      {allTime.isError ? (
        <ErrorState error={allTime.error} onRetry={() => allTime.refetch()} />
      ) : allTime.isPending ? (
        <LoadingState label="Loading your finances" />
      ) : allTime.data.transaction_count === 0 ? (
        <EmptyState
          title="Welcome to SpendWise"
          description="You have no transactions yet. Add your first income or expense to see your balance and spending."
          action={addButton}
        />
      ) : (
        <div className="flex flex-col gap-6">
          <div className={`${cardClass} bg-gradient-to-br from-indigo-600 to-indigo-700 p-5 text-white`}>
            <p className="text-sm text-indigo-100">Current balance (all time)</p>
            <p className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">{formatKzt(allTime.data.balance_cents)}</p>
            <p className="mt-1 text-xs text-indigo-100">
              {formatKzt(allTime.data.total_income_cents)} income − {formatKzt(allTime.data.total_expense_cents)} expenses
            </p>
          </div>

          <section aria-labelledby="this-month-heading">
            <h2 id="this-month-heading" className="mb-3 text-base font-semibold text-slate-900">
              This month
            </h2>
            {month.isError ? (
              <ErrorState error={month.error} onRetry={() => month.refetch()} />
            ) : month.isPending ? (
              <LoadingState />
            ) : (
              <SummaryTiles summary={month.data} netLabel="Net this month" />
            )}
          </section>

          <div className="grid gap-6 lg:grid-cols-5">
            <Card title="Income vs expenses, last 6 months" className="lg:col-span-3">
              {trend.isError ? (
                <ErrorState error={trend.error} onRetry={() => trend.refetch()} />
              ) : trend.isPending ? (
                <LoadingState />
              ) : (
                <LazyMonthlyTrendChart trend={trend.data} />
              )}
            </Card>

            <Card
              title="Top expenses this month"
              className="lg:col-span-2"
              action={<Link to="/analytics" className="text-sm font-medium text-indigo-700 hover:underline">Analytics</Link>}
            >
              {topExpenses.isError ? (
                <ErrorState error={topExpenses.error} onRetry={() => topExpenses.refetch()} />
              ) : topExpenses.isPending ? (
                <LoadingState />
              ) : (
                <CategoryBreakdownList breakdown={topExpenses.data} limit={5} />
              )}
            </Card>
          </div>

          <Card
            title="Recent transactions"
            action={<Link to="/transactions" className="text-sm font-medium text-indigo-700 hover:underline">View all</Link>}
          >
            {recent.isError ? (
              <ErrorState error={recent.error} onRetry={() => recent.refetch()} />
            ) : recent.isPending ? (
              <LoadingState />
            ) : (
              <TransactionList
                transactions={recent.data.items}
                onEdit={(transaction) => setDialog({ open: true, transaction })}
              />
            )}
          </Card>
        </div>
      )}

      <TransactionDialog
        open={dialog.open}
        transaction={dialog.transaction}
        onClose={() => setDialog({ open: false, transaction: null })}
      />
    </>
  )
}
