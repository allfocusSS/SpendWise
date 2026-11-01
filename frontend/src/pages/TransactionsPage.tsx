import { useState } from 'react'

import type { Transaction, TransactionType } from '../api/client'
import { useCategories, useDeleteTransaction, useSummary, useTransactions } from '../api/queries'
import { PlusIcon } from '../components/icons'
import { ConfirmDialog } from '../components/Modal'
import { SummaryTiles } from '../components/SummaryTiles'
import { SignedAmount, TransactionTable } from '../components/TransactionList'
import { Button, EmptyState, ErrorState, PageHeader, SearchInput, Segmented, SkeletonRows } from '../components/ui'
import { formatDate } from '../lib/dates'
import { cardClass, inputClass } from '../lib/styles'
import { useTransactionDialog } from '../lib/transactionDialog'

const PAGE_SIZE = 20

type Filters = { type: TransactionType | ''; category_id: string; date_from: string; date_to: string }
const NO_FILTERS: Filters = { type: '', category_id: '', date_from: '', date_to: '' }

const TYPE_OPTIONS: { value: Filters['type']; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'income', label: 'Income' },
  { value: 'expense', label: 'Expenses' },
]

function rangeLabel(from: string, to: string): string {
  if (from && to) return `${formatDate(from)} – ${formatDate(to)}`
  if (from) return `From ${formatDate(from)}`
  if (to) return `Until ${formatDate(to)}`
  return 'All time'
}

export function TransactionsPage() {
  const openTransaction = useTransactionDialog()
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [deleting, setDeleting] = useState<Transaction | null>(null)

  const invalidRange = !!filters.date_from && !!filters.date_to && filters.date_from > filters.date_to
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
  // The summary endpoint filters by date only; a note below says so when other filters are on.
  const summary = useSummary(
    invalidRange ? {} : { date_from: filters.date_from || undefined, date_to: filters.date_to || undefined },
  )

  const hasFilters = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS)

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
  const term = search.trim().toLowerCase()
  // Search runs in the browser over the rows on this page (the API has no text search).
  const visible = data
    ? data.items.filter(
        (t) => !term || t.description.toLowerCase().includes(term) || t.category.name.toLowerCase().includes(term),
      )
    : []

  return (
    <>
      <PageHeader title="Transactions" description="Every income and expense you have recorded." />

      {!invalidRange && (
        <div className="mb-8">
          <SummaryTiles query={summary} period={rangeLabel(filters.date_from, filters.date_to)} />
          {(filters.type || filters.category_id) && (
            <p className="mt-2 text-xs text-ink-subtle">Totals use the date range only; type and category filters apply to the table.</p>
          )}
        </div>
      )}

      <section className={cardClass} aria-label="Transaction ledger">
        <form
          className="flex flex-wrap items-center gap-2 border-b border-line p-4"
          onSubmit={(e) => e.preventDefault()}
          aria-label="Search and filter transactions"
        >
          <SearchInput label="Search transactions on this page" value={search} onChange={setSearch} placeholder="Search this page…" className="w-full sm:w-60" />
          <Segmented label="Type" options={TYPE_OPTIONS} value={filters.type} onChange={(type) => updateFilter({ type })} />
          <div className="w-full sm:w-44">
            <label htmlFor="f-category" className="sr-only">Category</label>
            <select id="f-category" value={filters.category_id} onChange={(e) => updateFilter({ category_id: e.target.value })} className={inputClass()}>
              <option value="">All categories</option>
              {categoryOptions.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="flex w-full items-center gap-1.5 sm:w-auto">
            <div className="min-w-0 flex-1 sm:w-36 sm:flex-none">
              <label htmlFor="f-from" className="sr-only">From</label>
              <input id="f-from" type="date" value={filters.date_from} aria-invalid={invalidRange}
                onChange={(e) => updateFilter({ date_from: e.target.value })} className={inputClass(invalidRange)} />
            </div>
            <span className="text-ink-subtle" aria-hidden="true">–</span>
            <div className="min-w-0 flex-1 sm:w-36 sm:flex-none">
              <label htmlFor="f-to" className="sr-only">To</label>
              <input id="f-to" type="date" value={filters.date_to} aria-invalid={invalidRange}
                onChange={(e) => updateFilter({ date_to: e.target.value })} className={inputClass(invalidRange)} />
            </div>
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={() => updateFilter(NO_FILTERS)}>
              Clear
            </Button>
          )}
          {data && !invalidRange && (
            <p className="ml-auto text-label whitespace-nowrap text-ink-subtle" aria-live="polite">
              <span className="font-semibold text-ink tabular-nums">{data.total}</span> transaction{data.total === 1 ? '' : 's'}
            </p>
          )}
        </form>
        {invalidRange && (
          <p role="alert" className="border-b border-line px-4 py-2 text-xs font-medium text-expense">“From” must be on or before “To”.</p>
        )}

        {invalidRange ? (
          <EmptyState title="Fix the date range to see transactions" />
        ) : transactions.isError ? (
          <div className="p-4"><ErrorState error={transactions.error} onRetry={() => transactions.refetch()} /></div>
        ) : transactions.isPending || !data ? (
          <div className="px-4"><SkeletonRows rows={8} label="Loading transactions" /></div>
        ) : data.total === 0 ? (
          hasFilters ? (
            <EmptyState
              title="No transactions match these filters"
              description="Try a different type, category or date range."
              action={<Button size="sm" variant="secondary" onClick={() => updateFilter(NO_FILTERS)}>Clear filters</Button>}
            />
          ) : (
            <EmptyState
              title="No transactions yet"
              action={<Button size="sm" onClick={() => openTransaction()}><PlusIcon /> Add transaction</Button>}
            />
          )
        ) : (
          <>
            <div aria-busy={transactions.isFetching} className={transactions.isPlaceholderData ? 'opacity-60 transition-opacity' : ''}>
              {visible.length === 0 ? (
                <EmptyState size="sm" title={`No matches for “${search.trim()}” on this page`} description="Search looks at the rows shown on this page." />
              ) : (
                <TransactionTable
                  layout="card"
                  transactions={visible}
                  onEdit={(transaction) => openTransaction({ transaction })}
                  onDelete={setDeleting}
                />
              )}
            </div>
            <nav aria-label="Pagination" className="flex flex-col items-center justify-between gap-3 border-t border-line px-4 py-3 sm:flex-row">
              <p className="text-label text-ink-subtle tabular-nums" aria-live="polite">
                Showing <span className="font-medium text-ink">{data.offset + 1}–{data.offset + data.items.length}</span> of{' '}
                <span className="font-medium text-ink">{data.total}</span>
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
      </section>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete transaction?"
        message={
          deleting && (
            <p>
              <strong className="text-ink">{deleting.description}</strong> (<SignedAmount transaction={deleting} />,{' '}
              {formatDate(deleting.occurred_on)}) will be permanently deleted.
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
