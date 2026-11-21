import type { ReactNode } from 'react'
import { Link } from 'react-router'

import type { TransactionType } from '../../api/client'
import { percentChange } from '../../lib/compare'
import { formatKzt, formatSignedKzt } from '../../lib/money'
import { transactionCount } from '../../lib/text'
import { ArrowRightIcon, BriefcaseIcon, CartIcon, PlusIcon, TagIcon } from '../icons'
import { Button, Figure, linkClass, Skeleton } from '../ui'
import { Change, KpiCard, KpiFigure, KpiNote, type SummaryQuery } from './parts'

/** The shown month, as the four cards name it. */
export type MonthNames = {
  /** "November 2026", for region names. */
  full: string
  /** "November", beside a card's title. */
  long: string
  /** "Nov" */
  short: string
  /** "Oct": the month before, in comparisons. */
  previousShort: string
  /** Whether it is the current month ("this month") or a past one ("in October"). */
  isCurrent: boolean
}

/**
 * The all-time balance (never per month, and says so), with the shown month's net under it: the
 * sign, the arrow and the colour all say the same thing.
 */
export function TotalBalanceCard({ allTime, month, names, className }: {
  allTime: SummaryQuery
  month: SummaryQuery
  names: MonthNames
  className?: string
}) {
  const net = month.data?.balance_cents
  return (
    <KpiCard title="Total balance" meta="All time" className={className}>
      <KpiFigure query={allTime} className="max-lg:text-[34px]">
        {allTime.data ? <Figure cents={allTime.data.balance_cents} /> : null}
      </KpiFigure>
      <KpiNote>
        {net === undefined ? (
          month.isError ? null : <Skeleton className="h-4 w-32" />
        ) : (
          <>
            <Change direction={net} good={net === 0 ? null : net > 0} signed>
              {formatSignedKzt(net)}
            </Change>
            {names.isCurrent ? 'this month' : `in ${names.long}`}
          </>
        )}
      </KpiNote>
    </KpiCard>
  )
}

/**
 * Money in or out for the month against the month before: the change (when there is a base to
 * compare with) and last month's figure. Spending less is the good direction for money out.
 */
export function MoneyCard({ kind, month, previous, names, className }: {
  kind: 'income' | 'expense'
  month: SummaryQuery
  previous: SummaryQuery
  names: MonthNames
  className?: string
}) {
  const title = kind === 'income' ? 'Money in' : 'Money out'
  const pick = (query: SummaryQuery) => (kind === 'income' ? query.data?.total_income_cents : query.data?.total_expense_cents)
  const current = pick(month)
  const before = pick(previous)
  const change = current === undefined || before === undefined ? null : percentChange(current, before)
  return (
    <KpiCard title={title} meta={names.long} label={`${title}, ${names.full}`} className={className}>
      <KpiFigure query={month}>{current === undefined ? null : <Figure cents={current} />}</KpiFigure>
      <KpiNote>
        {previous.isError ? (
          <span>Last month unavailable</span>
        ) : before === undefined ? (
          <Skeleton className="h-4 w-36" />
        ) : (
          <>
            {change === null ? null : (
              <Change direction={change} good={change === 0 ? null : (change > 0) === (kind === 'income')}>
                {Math.abs(change)}%
              </Change>
            )}
            <span>
              vs {names.previousShort} · <span className="tabular-nums">{formatKzt(before)}</span>
            </span>
          </>
        )}
      </KpiNote>
    </KpiCard>
  )
}

/**
 * The month's net as the server calculated it, and how much of what came in went out (the bar's
 * width is presentation only; both labelled amounts are the server's).
 */
export function NetSavingsCard({ month, names, className }: { month: SummaryQuery; names: MonthNames; className?: string }) {
  const data = month.data
  const net = data?.balance_cents ?? 0
  const spent = data && data.total_income_cents > 0 ? Math.min(data.total_expense_cents / data.total_income_cents, 1) : data?.total_expense_cents ? 1 : 0
  return (
    <KpiCard
      title="Net savings"
      meta={data ? transactionCount(data.transaction_count) : names.long}
      label={`Net savings, ${names.full}`}
      className={className}
    >
      <KpiFigure query={month} className={net > 0 ? 'text-income' : net < 0 ? 'text-expense' : ''}>
        {data ? <Figure cents={net} signed /> : null}
      </KpiFigure>
      {data ? (
        <>
          <div className="mt-0.5 h-[7px] overflow-hidden rounded-full bg-surface-selected" aria-hidden="true">
            <span className="block h-full rounded-full bg-income-chart" style={{ width: `${spent * 100}%` }} />
          </div>
          <KpiNote className="justify-between tabular-nums">
            <span>{formatKzt(data.total_expense_cents)} out</span>
            <span>of {formatKzt(data.total_income_cents)} in</span>
          </KpiNote>
        </>
      ) : null}
    </KpiCard>
  )
}

// --- First run --------------------------------------------------------------------------------

function Step({ icon, title, children, action }: { icon: ReactNode; title: string; children: ReactNode; action: ReactNode }) {
  return (
    <li className="flex min-w-0 flex-col gap-1 rounded-xl border border-line-strong bg-white/[0.012] p-3.5">
      <span className="mb-1.5 grid size-8 place-items-center rounded-full bg-accent-soft text-accent" aria-hidden="true">{icon}</span>
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="text-label text-ink-subtle">{children}</p>
      <div className="mt-auto pt-2.5">{action}</div>
    </li>
  )
}

/**
 * A new account's welcome, in place of the month's three figures: what this page becomes and the
 * three things to do first. Nothing here is a number the account doesn't have.
 */
export function WelcomeCard({ onAdd, className }: { onAdd: (type: TransactionType) => void; className?: string }) {
  return (
    <section aria-labelledby="welcome-heading" className={`rounded-[var(--radius-card)] bg-surface p-4 lg:px-5 lg:py-[18px] ${className}`}>
      <h2 id="welcome-heading" className="text-heading text-ink">Welcome to SpendWise</h2>
      <p className="mt-1 text-label text-ink-muted">
        Once you add a transaction, this page shows your balance and how each month went.
      </p>
      <ol className="mt-3.5 grid gap-2.5 sm:grid-cols-3">
        <Step icon={<BriefcaseIcon className="size-4" strokeWidth={1.8} />} title="Add your income" action={
          <Button size="sm" onClick={() => onAdd('income')} className="pointer-coarse:h-11"><PlusIcon /> Add income</Button>
        }>
          Your salary or any other money that comes in.
        </Step>
        <Step icon={<CartIcon className="size-4" strokeWidth={1.8} />} title="Record your spending" action={
          <Button size="sm" variant="secondary" onClick={() => onAdd('expense')} className="pointer-coarse:h-11"><PlusIcon /> Add expense</Button>
        }>
          Each expense goes into a category, like Groceries.
        </Step>
        <Step icon={<TagIcon className="size-4" strokeWidth={1.8} />} title="Review your categories" action={
          <Link to="/categories" className={`${linkClass} h-8 pointer-coarse:h-11`}>Review categories <ArrowRightIcon className="size-3.5" /></Link>
        }>
          Rename them or add your own.
        </Step>
      </ol>
    </section>
  )
}
