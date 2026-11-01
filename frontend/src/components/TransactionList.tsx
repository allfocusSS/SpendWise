import type { Transaction } from '../api/client'
import { formatDate } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { flushTh, table } from '../lib/styles'
import { PencilIcon, TrashIcon } from './icons'
import { CategoryBadge, IconButton } from './ui'

/**
 * Signed amount with tabular figures: "+2 500 ₸" in emerald for income, "−2 500 ₸" in the normal
 * text colour for expenses, as on a bank statement. The sign carries the meaning, not the colour.
 */
export function SignedAmount({ transaction, className = '' }: { transaction: Transaction; className?: string }) {
  const income = transaction.type === 'income'
  return (
    <span className={`font-medium tabular-nums whitespace-nowrap ${income ? 'text-income' : 'text-ink'} ${className}`}>
      <span className="sr-only">{income ? 'Income' : 'Expense'} </span>
      {income ? '+' : '−'}
      {formatKzt(transaction.amount_cents)}
    </span>
  )
}

function AiBadge() {
  return (
    <span className="ml-2 shrink-0 rounded-sm border border-line-strong px-1 text-[11px] leading-4 font-medium text-ink-subtle" title="Added with AI">
      AI
    </span>
  )
}

type RowActions = {
  onEdit?: (transaction: Transaction) => void
  onDelete?: (transaction: Transaction) => void
}

/** Edit/delete: revealed on row hover or keyboard focus (always visible on touch screens). */
function Actions({ transaction, onEdit, onDelete }: RowActions & { transaction: Transaction }) {
  if (!onEdit && !onDelete) return null
  return (
    <div className="flex shrink-0 justify-end gap-0.5 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:hover)]:opacity-0">
      {onEdit && (
        <IconButton label={`Edit ${transaction.description}`} onClick={() => onEdit(transaction)}>
          <PencilIcon />
        </IconButton>
      )}
      {onDelete && (
        <IconButton label={`Delete ${transaction.description}`} tone="danger" onClick={() => onDelete(transaction)}>
          <TrashIcon />
        </IconButton>
      )}
    </div>
  )
}

/** Compact rows: the small-screen layout of the table, like a bank statement. */
export function TransactionList({ transactions, onEdit, onDelete }: { transactions: Transaction[] } & RowActions) {
  return (
    <ul className="divide-y divide-line">
      {transactions.map((t) => (
        <li key={t.id} className="group flex items-center gap-3 py-3">
          <div className="min-w-0 flex-1">
            <p className="flex items-center text-label font-medium text-ink">
              <span className="truncate">{t.description}</span>
              {t.source === 'ai' && <AiBadge />}
            </p>
            <p className="mt-0.5 truncate text-xs text-ink-subtle">
              {t.category.name} · <time dateTime={t.occurred_on}>{formatDate(t.occurred_on)}</time>
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end">
            <SignedAmount transaction={t} className="text-label" />
            <Actions transaction={t} onEdit={onEdit} onDelete={onDelete} />
          </div>
        </li>
      ))}
    </ul>
  )
}

/**
 * Ledger table on wide screens (date first, sticky header, right-aligned amounts), compact rows on
 * small screens. `layout`: "framed" draws its own border, "card" sits flush inside a card, "open"
 * sits directly on the page under a section heading.
 */
export function TransactionTable({ transactions, onEdit, onDelete, caption = 'Transactions', layout = 'framed' }: {
  transactions: Transaction[]
  caption?: string
  layout?: 'framed' | 'card' | 'open'
} & RowActions) {
  const hasActions = Boolean(onEdit || onDelete)
  const open = layout === 'open'
  // Open tables sit on the page canvas and line up with the section heading (no outer padding).
  const th = open
    ? 'sticky top-16 z-10 h-9 border-b border-line-strong bg-canvas px-3 text-xs font-medium text-ink-subtle first:pl-0 last:pr-0'
    : `${layout === 'framed' ? table.th : flushTh} sticky top-16 z-10`
  const td = open ? 'h-11 border-b border-line px-3 first:pl-0 last:pr-0' : table.td
  return (
    <>
      <div className={`md:hidden ${layout === 'card' ? 'px-5' : ''} ${open ? 'border-t border-line' : ''}`}>
        <TransactionList transactions={transactions} onEdit={onEdit} onDelete={onDelete} />
      </div>
      <div className={`hidden md:block ${layout === 'framed' ? table.wrap : ''}`}>
        <table className={table.table}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col" className={`${th} w-32`}>Date</th>
              <th scope="col" className={th}>Description</th>
              <th scope="col" className={`${th} w-52 2xl:w-60`}>Category</th>
              <th scope="col" className={`${th} w-36 text-right`}>Amount</th>
              {hasActions && (
                <th scope="col" className={`${th} ${onEdit && onDelete ? 'w-20' : 'w-12'}`}>
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {transactions.map((t) => (
              <tr key={t.id} className={table.row}>
                <td className={`${td} whitespace-nowrap text-ink-muted tabular-nums`}>
                  <time dateTime={t.occurred_on}>{formatDate(t.occurred_on)}</time>
                </td>
                <td className={td}>
                  <div className="flex min-w-0 items-center">
                    <span className="truncate text-ink">{t.description}</span>
                    {t.source === 'ai' && <AiBadge />}
                  </div>
                </td>
                <td className={td}>
                  <CategoryBadge name={t.category.name} color={t.category.color} />
                </td>
                <td className={`${td} text-right`}>
                  <SignedAmount transaction={t} />
                </td>
                {hasActions && (
                  <td className={`${td} ${open ? '' : 'px-2'}`}>
                    <Actions transaction={t} onEdit={onEdit} onDelete={onDelete} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
