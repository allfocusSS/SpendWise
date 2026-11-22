import { useState } from 'react'

import type { Transaction, TransactionType } from '../api/client'
import { useCategories, useDeleteTransaction, useSummary, useTransactions } from '../api/queries'
import { CalendarIcon, CloseIcon, PlusIcon } from '../components/icons'
import { ConfirmDialog } from '../components/Modal'
import { SummaryTiles } from '../components/SummaryTiles'
import { SignedAmount, TransactionTable } from '../components/TransactionList'
import { Button, EmptyState, ErrorState, PageHeader, SearchInput, Segmented, Select, SkeletonRows } from '../components/ui'
import { formatDate } from '../lib/dates'
import { cardClass } from '../lib/styles'
import { transactionCount } from '../lib/text'
import { useToast } from '../lib/toast'
import { useTransactionDialog } from '../lib/transactionDialog'

const PAGE_SIZE = 20

type Filters = { type: TransactionType | ''; category_id: string; date_from: string; date_to: string }
const NO_FILTERS: Filters = { type: '', category_id: '', date_from: '', date_to: '' }

const TYPE_OPTIONS: { value: Filters['type']; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'income', label: 'Income' },
  { value: 'expense', label: 'Expenses' },
]

/** A removable filter: its value as text; the button's name says what pressing it does. */
function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={`Remove filter: ${label}`}
      className="inline-flex h-[30px] items-center gap-1.5 rounded-full border border-accent/35 bg-accent-soft px-2.5 text-[12.5px] font-medium text-ink transition-colors hover:border-accent/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus pointer-coarse:h-11"
    >
      {label}
      <CloseIcon className="size-3 text-ink-muted" strokeWidth={2.4} />
    </button>
  )
}

function rangeLabel(from: string, to: string): string {
  if (from && to) return `${formatDate(from)} – ${formatDate(to)}`
  if (from) return `From ${formatDate(from)}`
  if (to) return `Until ${formatDate(to)}`
  return 'All time'
}

export function TransactionsPage() {
  const openTransaction = useTransactionDialog()
  const toast = useToast()
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
  const typeName = TYPE_OPTIONS.find((option) => option.value === filters.type)?.label
  const categoryName = categories.data?.find((c) => String(c.id) === filters.category_id)?.name
  const dates = filters.date_from || filters.date_to ? rangeLabel(filters.date_from, filters.date_to) : null
  // The ledger's heading says what it lists: "Expenses · 1 Nov 2026 – 30 Nov 2026", "All transactions".
  const ledgerTitle = [categoryName ?? (filters.type ? typeName : null), dates].filter(Boolean).join(' · ') || 'All transactions'
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
      <PageHeader title="Transactions" description="Everything you’ve recorded, newest first." />

      <div className="flex flex-col gap-3.5 lg:gap-[18px]">
        {!invalidRange && <SummaryTiles query={summary} period={rangeLabel(filters.date_from, filters.date_to)} />}

        <form className={`${cardClass} p-4 lg:px-5 lg:py-[18px]`} onSubmit={(e) => e.preventDefault()} aria-label="Search and filter transactions">
          <div className="flex flex-wrap items-center gap-2.5 max-lg:[&>*]:basis-full">
            <SearchInput label="Search transactions on this page" value={search} onChange={setSearch} placeholder="Search this page" className="lg:w-[260px]" />
            <Segmented
              label="Type"
              options={TYPE_OPTIONS}
              value={filters.type}
              onChange={(type) => updateFilter({ type })}
              className="max-lg:grid max-lg:grid-cols-3 max-lg:[&>button]:w-full"
            />
            <div className="lg:w-[210px]">
              <label htmlFor="f-category" className="sr-only">Category</label>
              <Select id="f-category" value={filters.category_id} onChange={(e) => updateFilter({ category_id: e.target.value })}>
                <option value="">All categories</option>
                {categoryOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
            </div>
            <div
              className={`flex h-[42px] min-w-0 items-center gap-2 rounded-[var(--radius-control)] border bg-surface-raised px-3 focus-within:ring-3 pointer-coarse:h-11 ${
                invalidRange ? 'border-danger focus-within:ring-danger/20' : 'border-field focus-within:border-focus focus-within:ring-focus/25'
              }`}
            >
              <CalendarIcon className="size-4 shrink-0 text-ink-subtle" />
              <label htmlFor="f-from" className="sr-only">From</label>
              <input id="f-from" type="date" value={filters.date_from} aria-invalid={invalidRange}
                onChange={(e) => updateFilter({ date_from: e.target.value })}
                className="h-full min-w-0 flex-1 bg-transparent text-base text-ink tabular-nums focus:outline-none sm:text-sm lg:w-[8.5rem] lg:flex-none" />
              <span className="text-ink-subtle" aria-hidden="true">–</span>
              <label htmlFor="f-to" className="sr-only">To</label>
              <input id="f-to" type="date" value={filters.date_to} aria-invalid={invalidRange}
                onChange={(e) => updateFilter({ date_to: e.target.value })}
                className="h-full min-w-0 flex-1 bg-transparent text-base text-ink tabular-nums focus:outline-none sm:text-sm lg:w-[8.5rem] lg:flex-none" />
            </div>
            {hasFilters && (
              <Button variant="ghost" onClick={() => updateFilter(NO_FILTERS)} className="max-lg:hidden lg:ml-auto">
                Clear
              </Button>
            )}
          </div>
          {invalidRange && (
            <p role="alert" className="mt-2.5 text-xs font-medium text-danger">“From” must be on or before “To”.</p>
          )}
          {hasFilters && (
            <div className="mt-3.5 flex flex-wrap items-center gap-2 border-t border-line pt-3.5">
              <span className="text-[12.5px] text-ink-subtle">Filtered by</span>
              {filters.type && typeName ? <FilterChip label={typeName} onRemove={() => updateFilter({ type: '' })} /> : null}
              {categoryName ? <FilterChip label={categoryName} onRemove={() => updateFilter({ category_id: '' })} /> : null}
              {dates ? <FilterChip label={dates} onRemove={() => updateFilter({ date_from: '', date_to: '' })} /> : null}
              {(filters.type || filters.category_id) && (
                <span className="text-[12.5px] text-ink-subtle lg:ml-auto">The totals above use only the dates. Type and category narrow the list below.</span>
              )}
            </div>
          )}
        </form>

        <section className={`${cardClass} p-4 lg:px-5 lg:py-[18px]`} aria-label="Transaction ledger">
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h2 className="text-heading text-ink">{ledgerTitle}</h2>
            {data && !invalidRange && (
              <p className="text-[12.5px] text-ink-subtle tabular-nums" aria-live="polite">{transactionCount(data.total)}</p>
            )}
          </div>

          {invalidRange ? (
            <EmptyState title="Fix the date range to see transactions" />
          ) : transactions.isError ? (
            <div className="pt-2"><ErrorState error={transactions.error} onRetry={() => transactions.refetch()} /></div>
          ) : transactions.isPending || !data ? (
            <SkeletonRows rows={8} label="Loading transactions" />
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
                description="Record your first income or expense to start the list."
                action={<Button size="sm" onClick={() => openTransaction()}><PlusIcon /> Add transaction</Button>}
              />
            )
          ) : (
            <>
              <div aria-busy={transactions.isFetching} className={`max-lg:pt-2 ${transactions.isPlaceholderData ? 'opacity-60 transition-opacity' : ''}`}>
                {visible.length === 0 ? (
                  <EmptyState size="sm" title={`No matches for “${search.trim()}” on this page`} description="Search only covers this page. Use the filters to look further back." />
                ) : (
                  <TransactionTable
                    transactions={visible}
                    onEdit={(transaction) => openTransaction({ transaction })}
                    onDelete={setDeleting}
                  />
                )}
              </div>
              <nav aria-label="Pagination" className="mt-3 flex flex-wrap items-center justify-between gap-3 lg:mt-1.5">
                <p className="text-label text-ink-muted tabular-nums" aria-live="polite">
                  Showing <span className="font-semibold text-ink">{data.offset + 1}–{data.offset + data.items.length}</span> of{' '}
                  <span className="font-semibold text-ink">{data.total}</span>
                </p>
                <div className="flex gap-2">
                  <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="pointer-coarse:h-11">
                    Previous
                  </Button>
                  <Button variant="secondary" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)} className="pointer-coarse:h-11">
                    Next
                  </Button>
                </div>
              </nav>
            </>
          )}
        </section>
      </div>

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
              toast('Transaction deleted')
            },
          })
        }
        onClose={closeDelete}
      />
    </>
  )
}
