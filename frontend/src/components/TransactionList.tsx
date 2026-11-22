import type { Transaction } from '../api/client'
import { formatDate, formatRecentDate } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { useToday } from '../lib/useToday'
import { flushTh, table } from '../lib/styles'
import { CategoryIcon } from './CategoryIcon'
import { PencilIcon, TrashIcon } from './icons'
import { CategoryBadge, IconButton } from './ui'

/**
 * Signed amount with tabular figures: "+2 500 ₸" in emerald for income, "−2 500 ₸" in rose for
 * expenses. The sign carries the meaning, the colour repeats it.
 */
export function SignedAmount({ transaction, className = '' }: { transaction: Transaction; className?: string }) {
  const income = transaction.type === 'income'
  return (
    <span className={`font-semibold tabular-nums whitespace-nowrap ${income ? 'text-income' : 'text-expense'} ${className}`}>
      <span className="sr-only">{income ? 'Income' : 'Expense'} </span>
      {income ? '+' : '−'}
      {formatKzt(transaction.amount_cents)}
    </span>
  )
}

export function AiBadge() {
  return (
    <span className="ml-2 inline-flex h-[18px] shrink-0 items-center rounded-md bg-accent-soft px-1.5 text-[10.5px] font-bold text-accent" title="Added with AI">
      AI
    </span>
  )
}

type RowActions = {
  onEdit?: (transaction: Transaction) => void
  onDelete?: (transaction: Transaction) => void
}

/**
 * Edit/delete: revealed on row hover or keyboard focus (always visible on touch screens). `overlay`
 * floats them over the end of a list row instead of keeping a column for them.
 */
function Actions({ transaction, onEdit, onDelete, overlay = false }: RowActions & { transaction: Transaction; overlay?: boolean }) {
  if (!onEdit && !onDelete) return null
  return (
    <div className={`flex shrink-0 justify-end gap-1.5 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 can-hover:opacity-0 ${overlay ? 'row-actions-overlay' : ''}`}>
      {onEdit ? (
        <IconButton label={`Edit ${transaction.description}`} onClick={() => onEdit(transaction)}>
          <PencilIcon />
        </IconButton>
      ) : null}
      {onDelete ? (
        <IconButton label={`Delete ${transaction.description}`} tone="danger" onClick={() => onDelete(transaction)}>
          <TrashIcon />
        </IconButton>
      ) : null}
    </div>
  )
}

/** Card rows: the small-screen layout of the ledger (name over category, amount over date). */
export function TransactionList({ transactions, onEdit, onDelete }: { transactions: Transaction[] } & RowActions) {
  const today = useToday()
  return (
    <ul className="flex flex-col gap-[9px]">
      {transactions.map((t) => (
        <li key={t.id} className="group relative flex items-center gap-3 rounded-xl border border-line-strong bg-white/[0.012] px-3 py-2.5 transition-colors can-hover:hover:bg-surface-raised">
          <CategoryIcon name={t.category.name} color={t.category.color} />
          <div className="min-w-0 flex-1">
            <p className="flex items-center text-sm font-semibold text-ink">
              <span className="truncate">{t.description}</span>
              {t.source === 'ai' ? <AiBadge /> : null}
            </p>
            <p className="truncate text-xs text-ink-subtle">{t.category.name}</p>
          </div>
          <div className="shrink-0 text-right">
            <SignedAmount transaction={t} className="block text-sm" />
            <time dateTime={t.occurred_on} title={formatDate(t.occurred_on)} className="text-xs text-ink-subtle">
              {formatRecentDate(t.occurred_on, today)}
            </time>
          </div>
          <Actions transaction={t} onEdit={onEdit} onDelete={onDelete} overlay />
        </li>
      ))}
    </ul>
  )
}

/**
 * The ledger: a table of bordered rows on wide screens (description first, sticky header,
 * right-aligned amounts), card rows below lg. Sits inside a card.
 */
export function TransactionTable({ transactions, onEdit, onDelete, caption = 'Transactions' }: {
  transactions: Transaction[]
  caption?: string
} & RowActions) {
  const hasActions = Boolean(onEdit || onDelete)
  const th = `${flushTh} sticky top-0 z-10`
  return (
    <>
      <div className="lg:hidden">
        <TransactionList transactions={transactions} onEdit={onEdit} onDelete={onDelete} />
      </div>
      <div className="hidden lg:block">
        <table className={table.table}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>Description</th>
              <th scope="col" className={`${th} w-56 2xl:w-64`}>Category</th>
              <th scope="col" className={`${th} w-36`}>Date</th>
              <th scope="col" className={`${th} w-36 text-right`}>Amount</th>
              {hasActions ? (
                <th scope="col" className={`${th} ${onEdit && onDelete ? 'w-24' : 'w-14'}`}>
                  <span className="sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {transactions.map((t) => (
              <tr key={t.id} className={table.row}>
                <td className={table.td}>
                  <div className="flex min-w-0 items-center gap-3">
                    <CategoryIcon name={t.category.name} color={t.category.color} size="sm" />
                    <span className="truncate font-semibold text-ink">{t.description}</span>
                    {t.source === 'ai' ? <AiBadge /> : null}
                  </div>
                </td>
                <td className={table.td}>
                  <CategoryBadge name={t.category.name} color={t.category.color} />
                </td>
                <td className={`${table.td} whitespace-nowrap text-ink-muted tabular-nums`}>
                  <time dateTime={t.occurred_on}>{formatDate(t.occurred_on)}</time>
                </td>
                <td className={`${table.td} text-right`}>
                  <SignedAmount transaction={t} />
                </td>
                {hasActions ? (
                  <td className={`${table.td} px-2`}>
                    <Actions transaction={t} onEdit={onEdit} onDelete={onDelete} />
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
