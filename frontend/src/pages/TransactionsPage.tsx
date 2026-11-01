import { useState } from 'react'

import type { Transaction, TransactionType } from '../api/client'
import { useCategories, useDeleteTransaction, useTransactions } from '../api/queries'
import { PlusIcon } from '../components/icons'
import { ConfirmDialog } from '../components/Modal'
import { SignedAmount, TransactionList } from '../components/TransactionList'
import { TransactionDialog } from '../components/TransactionDialog'
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader } from '../components/ui'
import { formatDate } from '../lib/dates'
import { inputClass } from '../lib/styles'

const PAGE_SIZE = 20

type Filters = { type: TransactionType | ''; category_id: string; date_from: string; date_to: string }
const NO_FILTERS: Filters = { type: '', category_id: '', date_from: '', date_to: '' }

export function TransactionsPage() {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<{ open: boolean; transaction: Transaction | null }>({
    open: false,
    transaction: null,
  })
  const [deleting, setDeleting] = useState<Transaction | null>(null)

  const categories = useCategories()
  const remove = useDeleteTransaction()
  const transactions = useTransactions({
    type: filters.type || undefined,
    category_id: filters.category_id ? Number(filters.category_id) : undefined,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const hasFilters = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS)
  const invalidRange = !!filters.date_from && !!filters.date_to && filters.date_from > filters.date_to

  function updateFilter(patch: Partial<Filters>) {
    setFilters((current) => {
      const next = { ...current, ...patch }
      // Keep the category filter consistent with the type filter.
      if (patch.type && next.category_id) {
        const category = categories.data?.find((c) => String(c.id) === next.category_id)
        if (category && category.type !== patch.type) next.category_id = ''
      }
      return next
    })
    setOffset(0)
  }

  function closeDelete() {
    setDeleting(null)
    remove.reset()
  }

  const categoryOptions = (categories.data ?? []).filter((c) => !filters.type || c.type === filters.type)
  const data = transactions.data

  return (
    <>
      <PageHeader
        title="Transactions"
        description="Every income and expense you have recorded."
        action={
          <Button onClick={() => setEditing({ open: true, transaction: null })}>
            <PlusIcon /> Add transaction
          </Button>
        }
      />

      <Card className="mb-6">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" onSubmit={(e) => e.preventDefault()} aria-label="Filter transactions">
          <div className="flex flex-col gap-1">
            <label htmlFor="f-type" className="text-xs font-medium text-slate-600">Type</label>
            <select
              id="f-type"
              value={filters.type}
              onChange={(e) => updateFilter({ type: e.target.value as Filters['type'] })}
              className={inputClass()}
            >
              <option value="">All types</option>
              <option value="income">Income</option>
              <option value="expense">Expense</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="f-category" className="text-xs font-medium text-slate-600">Category</label>
            <select
              id="f-category"
              value={filters.category_id}
              onChange={(e) => updateFilter({ category_id: e.target.value })}
              className={inputClass()}
            >
              <option value="">All categories</option>
              {categoryOptions.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="f-from" className="text-xs font-medium text-slate-600">From</label>
            <input
              id="f-from"
              type="date"
              value={filters.date_from}
              onChange={(e) => updateFilter({ date_from: e.target.value })}
              aria-invalid={invalidRange}
              className={inputClass(invalidRange)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="f-to" className="text-xs font-medium text-slate-600">To</label>
            <input
              id="f-to"
              type="date"
              value={filters.date_to}
              onChange={(e) => updateFilter({ date_to: e.target.value })}
              aria-invalid={invalidRange}
              className={inputClass(invalidRange)}
            />
          </div>
          <div className="flex items-end">
            <Button variant="secondary" className="w-full" disabled={!hasFilters} onClick={() => updateFilter(NO_FILTERS)}>
              Clear filters
            </Button>
          </div>
        </form>
        {invalidRange && (
          <p role="alert" className="mt-2 text-xs font-medium text-red-700">
            “From” must be on or before “To”.
          </p>
        )}
      </Card>

      <Card>
        {invalidRange ? (
          <EmptyState title="Fix the date range to see transactions" />
        ) : transactions.isError ? (
          <ErrorState error={transactions.error} onRetry={() => transactions.refetch()} />
        ) : transactions.isPending || !data ? (
          <LoadingState label="Loading transactions" />
        ) : data.total === 0 ? (
          hasFilters ? (
            <EmptyState
              title="No transactions match these filters"
              action={<Button variant="secondary" onClick={() => updateFilter(NO_FILTERS)}>Clear filters</Button>}
            />
          ) : (
            <EmptyState
              title="No transactions yet"
              description="Add your first income or expense to get started."
              action={<Button onClick={() => setEditing({ open: true, transaction: null })}><PlusIcon /> Add transaction</Button>}
            />
          )
        ) : (
          <>
            <div aria-busy={transactions.isFetching} className={transactions.isPlaceholderData ? 'opacity-60' : ''}>
              <TransactionList
                transactions={data.items}
                onEdit={(transaction) => setEditing({ open: true, transaction })}
                onDelete={setDeleting}
              />
            </div>
            <nav aria-label="Pagination" className="mt-4 flex flex-col items-center justify-between gap-3 border-t border-slate-100 pt-4 sm:flex-row">
              <p className="text-sm text-slate-600" aria-live="polite">
                Showing {data.offset + 1}–{data.offset + data.items.length} of {data.total}
              </p>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                  Previous
                </Button>
                <Button variant="secondary" size="sm" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                  Next
                </Button>
              </div>
            </nav>
          </>
        )}
      </Card>

      <TransactionDialog
        open={editing.open}
        transaction={editing.transaction}
        onClose={() => setEditing({ open: false, transaction: null })}
      />

      <ConfirmDialog
        open={deleting !== null}
        title="Delete transaction?"
        message={
          deleting && (
            <p>
              <strong>{deleting.description}</strong> (<SignedAmount transaction={deleting} />, {formatDate(deleting.occurred_on)})
              will be permanently deleted.
            </p>
          )
        }
        confirmLabel="Delete"
        pending={remove.isPending}
        error={remove.error?.message}
        onConfirm={() =>
          deleting &&
          remove.mutate(deleting.id, {
            onSuccess: () => {
              // Deleting the only row on the last page: step back so the page isn't empty.
              if (data?.items.length === 1 && offset > 0) setOffset(Math.max(0, offset - PAGE_SIZE))
              closeDelete()
            },
          })
        }
        onClose={closeDelete}
      />
    </>
  )
}
