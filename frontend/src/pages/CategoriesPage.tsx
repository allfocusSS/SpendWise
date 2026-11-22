import { useState, type FormEvent, type ReactNode } from 'react'

import { ApiError, type Category, type CategoryBreakdown, type TransactionType } from '../api/client'
import { useCategories, useCategoryBreakdown, useCreateCategory, useDeleteCategory, useUpdateCategory } from '../api/queries'
import { ShareRing } from '../components/CategoryDonut'
import { CategoryIcon } from '../components/CategoryIcon'
import { ChevronDownIcon, PencilIcon, PlusIcon, TrashIcon } from '../components/icons'
import { ConfirmDialog, Modal } from '../components/Modal'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormError,
  IconButton,
  PageHeader,
  SearchInput,
  Segmented,
  Select,
  Skeleton,
  SkeletonRows,
} from '../components/ui'
import { periodRange } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { cardClass, describedBy, flushTh, inputClass, table } from '../lib/styles'
import { transactionCount } from '../lib/text'
import { useToast } from '../lib/toast'
import { useToday } from '../lib/useToday'

const DEFAULT_COLOR = '#64748b'

type Period = 'this-month' | 'all-time'
const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: 'this-month', label: 'This month' },
  { value: 'all-time', label: 'All time' },
]

type BreakdownQuery = { data?: CategoryBreakdown; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }
type Item = CategoryBreakdown['items'][number]

export function CategoriesPage() {
  const toast = useToast()
  const today = useToday()
  const categories = useCategories()
  const [period, setPeriod] = useState<Period>('this-month')
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState<TransactionType | null>(null)
  const [editing, setEditing] = useState<Category | null>(null)
  const [deleting, setDeleting] = useState<Category | null>(null)
  const remove = useDeleteCategory()

  const range = periodRange(period, today)
  const expenses = useCategoryBreakdown({ type: 'expense', ...range })
  const income = useCategoryBreakdown({ type: 'income', ...range })

  function closeDelete() {
    setDeleting(null)
    remove.reset()
  }

  const term = search.trim().toLowerCase()
  // The full category list is loaded, so filtering in the browser covers everything.
  const matching = (categories.data ?? []).filter((c) => !term || c.name.toLowerCase().includes(term))
  const counts = {
    all: categories.data?.length ?? 0,
    expense: categories.data?.filter((c) => c.type === 'expense').length ?? 0,
    income: categories.data?.filter((c) => c.type === 'income').length ?? 0,
  }
  // "November", or "All time": what the figures on this page cover.
  const periodName = period === 'this-month' ? today.toLocaleDateString('en-GB', { month: 'long' }) : 'All time'
  const ledgerProps = { searching: term !== '', periodName, onEdit: setEditing, onDelete: setDeleting }

  return (
    <>
      <PageHeader
        title="Categories"
        description="How much went through each category this month or in total."
        action={
          <div className="flex w-full items-center gap-2.5 lg:w-auto">
            <Segmented label="Period" options={PERIOD_OPTIONS} value={period} onChange={setPeriod} className="max-lg:grid max-lg:flex-1 max-lg:grid-cols-2" />
            <Button variant="secondary" onClick={() => setAdding('expense')} className="pointer-coarse:h-11">
              <PlusIcon strokeWidth={2.2} />
              <span>Add<span className="max-sm:sr-only"> category</span></span>
            </Button>
          </div>
        }
      />

      {categories.isError ? (
        <div className={`${cardClass} p-4`}><ErrorState error={categories.error} onRetry={() => categories.refetch()} /></div>
      ) : categories.isPending ? (
        <div className={`${cardClass} p-4`}><SkeletonRows rows={6} label="Loading categories" /></div>
      ) : counts.all === 0 ? (
        <div className={cardClass}>
          <EmptyState
            title="No categories yet"
            description="Categories group your transactions."
            action={<Button size="sm" onClick={() => setAdding('expense')}><PlusIcon /> Add category</Button>}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3 lg:gap-[18px]">
          <Card title={period === 'this-month' ? `${periodName} so far` : 'All time'} className="lg:col-start-3 lg:row-start-1">
            <dl className="text-[13.5px] text-ink-muted">
              <GlanceRow label="Spent" query={expenses} />
              <GlanceRow label="Earned" query={income} className="text-income" />
              <div className="flex items-baseline justify-between gap-3 border-t border-line py-2.5">
                <dt>Categories</dt>
                <dd className="tabular-nums">
                  <span className="text-[15px] font-semibold text-ink">{counts.all}</span>
                  <span className="text-[12.5px] text-ink-subtle"> · {counts.expense} expense · {counts.income} income</span>
                </dd>
              </div>
            </dl>
            <SearchInput label="Search categories" value={search} onChange={setSearch} placeholder="Search categories" className="mt-3" />
          </Card>

          <Card
            title="Spending distribution"
            action={<span>{period === 'this-month' ? `Share of ${periodName} spending` : 'Share of all spending'}</span>}
            className="lg:col-span-2 lg:col-start-1 lg:row-start-1"
          >
            <Distribution query={expenses} />
          </Card>

          <ExpenseLedger
            categories={matching.filter((c) => c.type === 'expense')}
            breakdown={expenses}
            className="lg:col-span-2"
            {...ledgerProps}
          />
          <IncomeLedger
            categories={matching.filter((c) => c.type === 'income')}
            breakdown={income}
            onAdd={() => setAdding('income')}
            {...ledgerProps}
          />
        </div>
      )}

      <Modal open={adding !== null} title="New category" onClose={() => setAdding(null)}>
        {adding && <CategoryForm defaultType={adding} onDone={() => setAdding(null)} />}
      </Modal>

      <Modal open={editing !== null} title="Edit category" onClose={() => setEditing(null)}>
        {editing && <CategoryForm category={editing} onDone={() => setEditing(null)} />}
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete category?"
        message={
          deleting && (
            <p>
              The category <strong className="text-ink">{deleting.name}</strong> will be deleted. Categories that still have
              transactions cannot be deleted.
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
              closeDelete()
              toast('Category deleted')
            },
          })
        }
        onClose={closeDelete}
      />
    </>
  )
}

/** A period total from the breakdown (the backend's), or its loading / error state. */
function GlanceRow({ label, query, className = 'text-ink' }: { label: string; query: BreakdownQuery; className?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-2.5">
      <dt>{label}</dt>
      <dd className={`text-[15px] font-semibold tabular-nums ${className}`}>
        {query.isError ? <span className="text-ink-subtle">—</span> : query.data ? formatKzt(query.data.total_cents) : <Skeleton className="h-4 w-24" />}
      </dd>
    </div>
  )
}

/** Every category with spending in the period as a ring of its share (the backend's percentage). */
function Distribution({ query }: { query: BreakdownQuery }) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  if (query.isPending || !query.data) {
    return (
      <div role="status" aria-label="Loading spending" className="grid grid-cols-3 gap-2 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="mx-auto size-[86px] rounded-full" />)}
      </div>
    )
  }
  if (query.data.items.length === 0) {
    return <EmptyState size="sm" title="No spending in this period" description="Add an expense and you’ll see how your spending splits." />
  }
  return (
    <ul className="grid grid-cols-3 gap-x-2 gap-y-4 xl:grid-cols-6">
      {query.data.items.map((item) => (
        <li key={item.category_id} className="flex min-w-0 flex-col items-center gap-1.5 text-center">
          <ShareRing percentage={item.percentage} size="size-[86px]">
            <span className="text-base font-semibold text-ink tabular-nums" aria-hidden="true">{Math.round(item.percentage)}%</span>
          </ShareRing>
          <p className="text-label leading-tight font-medium text-ink">{item.category_name}</p>
          <p className="text-xs text-ink-subtle tabular-nums">
            {formatKzt(item.total_cents)}
            <span className="sr-only">, {item.percentage}%</span>
          </p>
        </li>
      ))}
    </ul>
  )
}

type SortKey = 'name' | 'amount' | 'count'
type Sort = { key: SortKey; dir: 'asc' | 'desc' }

/**
 * Categories in the chosen order, each with its activity in the period (if any). The full list is
 * loaded, so sorting here covers every row (ordering only, no maths).
 */
function sortRows(categories: Category[], items: Item[], sort: Sort): { category: Category; item?: Item }[] {
  const byId = new Map(items.map((item) => [item.category_id, item]))
  const value = (c: Category) =>
    sort.key === 'name' ? 0 : sort.key === 'count' ? (byId.get(c.id)?.transaction_count ?? 0) : (byId.get(c.id)?.total_cents ?? 0)
  return [...categories]
    .sort((a, b) => {
      const byName = a.name.localeCompare(b.name)
      if (sort.key === 'name') return sort.dir === 'asc' ? byName : -byName
      // Equal amounts or counts stay in name order (A to Z) in either direction.
      return (sort.dir === 'asc' ? value(a) - value(b) : value(b) - value(a)) || byName
    })
    .map((category) => ({ category, item: byId.get(category.id) }))
}

type LedgerProps = {
  categories: Category[]
  breakdown: BreakdownQuery
  searching: boolean
  periodName: string
  onEdit: (category: Category) => void
  onDelete: (category: Category) => void
}

function NoMatches({ searching, type, action }: { searching: boolean; type: TransactionType; action?: ReactNode }) {
  return (
    <EmptyState
      size="sm"
      title={searching ? 'No categories match your search' : `No ${type} categories yet`}
      action={searching ? undefined : action}
    />
  )
}

/** "Default" or nothing: the seeded categories are marked, the user's own are not. */
function DefaultTag() {
  return <span className="ml-1 hidden shrink-0 rounded-md border border-line-strong px-1.5 text-[11px] leading-[18px] font-semibold text-ink-subtle xl:inline">Default</span>
}

/** Expense categories: a table of bordered rows from lg (sortable), card rows below. */
function ExpenseLedger({ categories, breakdown, searching, periodName, onEdit, onDelete, className = '' }: LedgerProps & { className?: string }) {
  const [sort, setSort] = useState<Sort>({ key: 'amount', dir: 'desc' })
  const rows = sortRows(categories, breakdown.data?.items ?? [], sort)
  const toggleSort = (key: SortKey) =>
    setSort((current) => (current.key === key ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'name' ? 'asc' : 'desc' }))
  const largest = breakdown.data?.items[0]?.total_cents ?? 0
  const quiet = periodName === 'All time' ? 'No spending yet' : `No spending in ${periodName}`

  return (
    <section className={`${cardClass} p-4 lg:px-5 lg:py-[18px] ${className}`} aria-labelledby="ledger-expense">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 id="ledger-expense" className="text-heading text-ink">Expense categories</h2>
        <span className="text-[12.5px] text-ink-subtle tabular-nums">{categories.length}</span>
      </div>
      {breakdown.isError && <div className="py-2"><ErrorState error={breakdown.error} onRetry={() => breakdown.refetch()} /></div>}

      {rows.length === 0 ? (
        <NoMatches searching={searching} type="expense" />
      ) : (
        <>
          <ul className="flex flex-col gap-[9px] pt-2 lg:hidden">
            {rows.map(({ category: c, item }) => (
              <li key={c.id} className="group relative flex items-center gap-3 rounded-xl border border-line-strong bg-white/[0.012] px-3 py-2.5 transition-colors can-hover:hover:bg-surface-raised">
                <CategoryIcon name={c.name} color={c.color} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{c.name}</p>
                  <p className="truncate text-[12.5px] text-ink-subtle">{item ? `${item.percentage}% · ${transactionCount(item.transaction_count)}` : quiet}</p>
                </div>
                <span className={`shrink-0 text-sm font-semibold tabular-nums ${item ? 'text-ink' : 'text-ink-subtle'}`}>{item ? formatKzt(item.total_cents) : '—'}</span>
                <RowActions category={c} onEdit={onEdit} onDelete={onDelete} overlay />
              </li>
            ))}
          </ul>
          <table className={`${table.table} hidden lg:table`}>
            <caption className="sr-only">Expense categories</caption>
            <thead>
              <tr>
                <SortHeader label="Category" sortKey="name" sort={sort} onSort={toggleSort} />
                <SortHeader label="Spent" sortKey="amount" sort={sort} onSort={toggleSort} className="w-28" align="right" />
                <th scope="col" className={`${flushTh} w-36 xl:w-44`}>Share</th>
                <SortHeader label="Count" sortKey="count" sort={sort} onSort={toggleSort} className="w-[72px]" align="right" />
                <th scope="col" className={`${flushTh} w-[84px]`}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ category: c, item }) => {
                // Bar width is presentation only; the percentage text comes from the backend.
                const width = item && largest > 0 ? Math.max((item.total_cents / largest) * 100, 3) : 0
                return (
                  <tr key={c.id} className={table.row}>
                    <td className={table.td}>
                      <div className="flex min-w-0 items-center gap-3">
                        <CategoryIcon name={c.name} color={c.color} size="sm" />
                        <span className="truncate font-semibold text-ink" title={c.name}>{c.name}</span>
                        {c.is_default ? <DefaultTag /> : null}
                      </div>
                    </td>
                    {item ? (
                      <>
                        <td className={`${table.td} text-right font-semibold text-ink tabular-nums`}>{formatKzt(item.total_cents)}</td>
                        <td className={table.td}>
                          <div className="flex items-center gap-2.5">
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-selected" aria-hidden="true">
                              <span className="block h-full rounded-full" style={{ width: `${width}%`, backgroundColor: c.color }} />
                            </div>
                            <span className="w-[52px] text-right text-[12.5px] text-ink-subtle tabular-nums">{item.percentage}%</span>
                          </div>
                        </td>
                        <td className={`${table.td} text-right text-ink-muted tabular-nums`}>{item.transaction_count}</td>
                      </>
                    ) : (
                      <td colSpan={3} className={`${table.td} text-center text-label text-ink-subtle`}>
                        {breakdown.isPending ? <Skeleton className="mx-auto h-3 w-32" /> : quiet}
                      </td>
                    )}
                    <td className={`${table.td} px-2`}>
                      <RowActions category={c} onEdit={onEdit} onDelete={onDelete} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

/** Income categories: a short list of card rows, largest first, and a button to add one. */
function IncomeLedger({ categories, breakdown, searching, periodName, onEdit, onDelete, onAdd }: LedgerProps & { onAdd: () => void }) {
  const rows = sortRows(categories, breakdown.data?.items ?? [], { key: 'amount', dir: 'desc' })
  const quiet = periodName === 'All time' ? 'No income yet' : `No income in ${periodName}`
  const add = (
    <Button variant="secondary" onClick={onAdd} className="w-full pointer-coarse:h-11">
      <PlusIcon strokeWidth={2.2} /> Add income category
    </Button>
  )
  return (
    <section className={`${cardClass} flex flex-col p-4 lg:px-5 lg:py-[18px]`} aria-labelledby="ledger-income">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id="ledger-income" className="text-heading text-ink">Income categories</h2>
        <span className="text-[12.5px] text-ink-subtle tabular-nums">{categories.length}</span>
      </div>
      {breakdown.isError && <div className="pb-2"><ErrorState error={breakdown.error} onRetry={() => breakdown.refetch()} /></div>}
      {rows.length === 0 ? (
        <NoMatches searching={searching} type="income" />
      ) : (
        <ul className="flex flex-col gap-[9px]">
          {rows.map(({ category: c, item }) => (
            <li key={c.id} className="group relative flex items-center gap-3 rounded-xl border border-line-strong bg-white/[0.012] px-3 py-2.5 transition-colors can-hover:hover:bg-surface-raised">
              <CategoryIcon name={c.name} color={c.color} />
              <div className="min-w-0 flex-1">
                <p className="flex items-center text-sm font-semibold text-ink">
                  <span className="truncate">{c.name}</span>
                </p>
                <p className="truncate text-[12.5px] text-ink-subtle">{item ? transactionCount(item.transaction_count) : quiet}</p>
              </div>
              <span className={`shrink-0 text-sm font-semibold tabular-nums ${item ? 'text-income' : 'text-ink-subtle'}`}>
                {item ? `+${formatKzt(item.total_cents)}` : '—'}
              </span>
              <RowActions category={c} onEdit={onEdit} onDelete={onDelete} overlay />
            </li>
          ))}
        </ul>
      )}
      <div className="pt-3">{add}</div>
    </section>
  )
}

/** Column header that sorts the ledger; announces the current order with aria-sort. */
function SortHeader({ label, sortKey, sort, onSort, className = '', align = 'left' }: {
  label: string
  sortKey: SortKey
  sort: Sort
  onSort: (key: SortKey) => void
  className?: string
  align?: 'left' | 'right'
}) {
  const active = sort.key === sortKey
  return (
    <th scope="col" aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} className={`${flushTh} ${className} ${align === 'right' ? 'text-right' : ''}`}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 rounded-sm hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${active ? 'text-ink' : ''}`}
      >
        {label}
        <ChevronDownIcon
          className={`size-3 transition-transform ${active ? '' : 'opacity-30'} ${active && sort.dir === 'asc' ? 'rotate-180' : ''}`}
          strokeWidth={2}
        />
      </button>
    </th>
  )
}

/** Edit/delete, revealed on hover or focus; `overlay` floats them over the end of a list row. */
function RowActions({ category, onEdit, onDelete, overlay = false }: {
  category: Category
  onEdit: (category: Category) => void
  onDelete: (category: Category) => void
  overlay?: boolean
}) {
  return (
    <div className={`flex shrink-0 justify-end gap-1.5 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 can-hover:opacity-0 ${overlay ? 'row-actions-overlay' : ''}`}>
      <IconButton label={`Edit ${category.name}`} onClick={() => onEdit(category)}>
        <PencilIcon />
      </IconButton>
      <IconButton label={`Delete ${category.name}`} tone="danger" onClick={() => onDelete(category)}>
        <TrashIcon />
      </IconButton>
    </div>
  )
}

/** Create (no `category`) or edit a category. */
function CategoryForm({ category, defaultType = 'expense', onDone }: {
  category?: Category
  defaultType?: TransactionType
  onDone: () => void
}) {
  const toast = useToast()
  const create = useCreateCategory()
  const update = useUpdateCategory()
  const mutation = category ? update : create

  const [name, setName] = useState(category?.name ?? '')
  const [type, setType] = useState<TransactionType>(category?.type ?? defaultType)
  const [color, setColor] = useState(category?.color ?? DEFAULT_COLOR)
  const [nameError, setNameError] = useState<string>()
  const [formError, setFormError] = useState<string | null>(null)
  const idPrefix = category ? `edit-${category.id}` : 'new'

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    const trimmed = name.trim()
    if (!trimmed) {
      setNameError('Enter a name.')
      return
    }
    setNameError(undefined)

    try {
      if (category) {
        await update.mutateAsync({ id: category.id, body: { name: trimmed, type, color } })
        toast('Category updated')
      } else {
        await create.mutateAsync({ name: trimmed, type, color })
        toast(`Added “${trimmed}”`)
      }
      onDone()
    } catch (error) {
      if (error instanceof ApiError) {
        setNameError(error.fieldErrors.name)
        setFormError(error.message)
      } else {
        setFormError('Could not save the category.')
      }
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <FormError message={formError} />
      <Field id={`${idPrefix}-name`} label="Name" error={nameError}>
        <input
          id={`${idPrefix}-name`}
          value={name}
          maxLength={50}
          onChange={(e) => setName(e.target.value)}
          aria-invalid={!!nameError}
          aria-describedby={describedBy(`${idPrefix}-name`, nameError)}
          className={inputClass(!!nameError)}
          placeholder="For example, Pets"
        />
      </Field>
      <Field
        id={`${idPrefix}-type`}
        label="Type"
        hint={category ? 'The type can only change while no transactions use this category.' : undefined}
      >
        <Select
          id={`${idPrefix}-type`}
          value={type}
          onChange={(e) => setType(e.target.value as TransactionType)}
          aria-describedby={category ? `${idPrefix}-type-hint` : undefined}
        >
          <option value="expense">Expense</option>
          <option value="income">Income</option>
        </Select>
      </Field>
      <Field id={`${idPrefix}-color`} label="Colour">
        <div className="flex items-center gap-3">
          <input
            id={`${idPrefix}-color`}
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="h-[42px] w-16 cursor-pointer rounded-[var(--radius-control)] border border-field bg-surface-raised p-1 focus:border-focus focus:ring-3 focus:ring-focus/25 focus:outline-none"
          />
          <span className="font-mono text-xs text-ink-subtle">{color}</span>
        </div>
      </Field>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving…' : category ? 'Save changes' : (<><PlusIcon /> Add category</>)}
        </Button>
      </div>
    </form>
  )
}
