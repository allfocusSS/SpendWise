import type { Transaction } from '../api/client'
import { formatDate } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { PencilIcon, TrashIcon } from './icons'
import { Button } from './ui'

/** Signed amount: "+2 500 ₸" for income, "−2 500 ₸" for expenses. The sign carries the meaning. */
export function SignedAmount({ transaction }: { transaction: Transaction }) {
  const income = transaction.type === 'income'
  return (
    <span className={`font-semibold tabular-nums whitespace-nowrap ${income ? 'text-emerald-700' : 'text-slate-900'}`}>
      <span className="sr-only">{income ? 'Income' : 'Expense'} </span>
      {income ? '+' : '−'}
      {formatKzt(transaction.amount_cents)}
    </span>
  )
}

export function TransactionList({ transactions, onEdit, onDelete }: {
  transactions: Transaction[]
  onEdit?: (transaction: Transaction) => void
  onDelete?: (transaction: Transaction) => void
}) {
  return (
    <ul className="divide-y divide-slate-100">
      {transactions.map((t) => (
        <li key={t.id} className="flex items-center gap-3 py-3">
          <span
            className="size-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: t.category.color }}
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-900">{t.description}</p>
            <p className="truncate text-xs text-slate-500">
              {t.category.name} · <time dateTime={t.occurred_on}>{formatDate(t.occurred_on)}</time>
              {t.source === 'ai' && <span className="ml-1 rounded bg-indigo-50 px-1 text-indigo-700">AI</span>}
            </p>
          </div>
          <SignedAmount transaction={t} />
          {(onEdit || onDelete) && (
            <div className="flex shrink-0 gap-0.5">
              {onEdit && (
                <Button variant="ghost" size="sm" onClick={() => onEdit(t)} aria-label={`Edit ${t.description}`}>
                  <PencilIcon />
                </Button>
              )}
              {onDelete && (
                <Button variant="ghost" size="sm" onClick={() => onDelete(t)} aria-label={`Delete ${t.description}`}>
                  <TrashIcon />
                </Button>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
