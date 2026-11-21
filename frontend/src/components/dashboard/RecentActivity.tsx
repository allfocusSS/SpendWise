import { Link } from 'react-router'

import type { Transaction, TransactionList } from '../../api/client'
import { formatRecentDate } from '../../lib/dates'
import { CategoryIcon } from '../CategoryIcon'
import { ArrowRightIcon, ReceiptIcon } from '../icons'
import { AiBadge, SignedAmount } from '../TransactionList'
import { Card, EmptyState, ErrorState, linkClass, SkeletonRows } from '../ui'

type RecentQuery = { data?: TransactionList; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }

/**
 * One transaction as a bordered row: category mark, description over category, amount over date.
 * The whole row is its edit button: a transparent overlay (positioned, so it sits above the text),
 * which makes the target the size of the row.
 */
function ActivityRow({ transaction: t, today, onEdit }: { transaction: Transaction; today: Date; onEdit: (transaction: Transaction) => void }) {
  return (
    <li className="relative flex min-w-0 items-center gap-3 rounded-xl border border-line-strong bg-white/[0.012] px-3 py-2.5 transition-colors has-[button:hover]:bg-surface-raised">
      <button
        type="button"
        aria-label={`Edit ${t.description}`}
        onClick={() => onEdit(t)}
        className="absolute inset-0 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      />
      <CategoryIcon name={t.category.name} color={t.category.color} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center text-sm font-semibold text-ink">
          <span className="truncate">{t.description}</span>
          {t.source === 'ai' ? <AiBadge /> : null}
        </span>
        <span className="block truncate text-[12.5px] text-ink-subtle">{t.category.name}</span>
      </span>
      <span className="shrink-0 text-right">
        <SignedAmount transaction={t} className="block text-sm" />
        <time dateTime={t.occurred_on} className="text-xs text-ink-subtle">{formatRecentDate(t.occurred_on, today)}</time>
      </span>
    </li>
  )
}

/** The latest transactions, newest first, each editable in place. */
export function RecentActivity({ query, today, onEdit, className }: {
  query: RecentQuery
  today: Date
  onEdit: (transaction: Transaction) => void
  className?: string
}) {
  const items = query.data?.items
  return (
    <Card
      title="Recent transactions"
      action={
        <Link to="/transactions" className={`${linkClass} min-h-8 pointer-coarse:min-h-11`}>
          All transactions <ArrowRightIcon className="size-3.5" />
        </Link>
      }
      className={className}
    >
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending || !items ? (
        <SkeletonRows rows={5} label="Loading recent transactions" />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ReceiptIcon className="size-5" />}
          title="No transactions yet"
          description="Add your first one with the + button."
        />
      ) : (
        <ul className="flex flex-col gap-[9px]">
          {items.map((transaction) => (
            <ActivityRow key={transaction.id} transaction={transaction} today={today} onEdit={onEdit} />
          ))}
        </ul>
      )}
    </Card>
  )
}
