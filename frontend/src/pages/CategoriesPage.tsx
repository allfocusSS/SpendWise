import { useState, type FormEvent } from 'react'

import { ApiError, type Category, type CategoryBreakdown, type TransactionType } from '../api/client'
import { useCategories, useCategoryBreakdown, useCreateCategory, useDeleteCategory, useUpdateCategory } from '../api/queries'
import { ChevronDownIcon, PencilIcon, PlusIcon, TrashIcon } from '../components/icons'
import { LazyCategoryTreemap } from '../components/LazyCharts'
import { ConfirmDialog, Modal } from '../components/Modal'
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  FormError,
  IconButton,
  PageHeader,
  SearchInput,
  Segmented,
  Skeleton,
  SkeletonRows,
} from '../components/ui'
import { periodRange } from '../lib/dates'
import { formatKzt } from '../lib/money'
import { cardClass, describedBy, labelClass, flushTh, inputClass, table } from '../lib/styles'

const DEFAULT_COLOR = '#64748b'

type Period = 'this-month' | 'all-time'
const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: 'this-month', label: 'This month' },
  { value: 'all-time', label: 'All time' },
]

export function CategoriesPage() {
  const categories = useCategories()
  const [period, setPeriod] = useState<Period>('this-month')
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState<TransactionType | null>(null)
  const [editing, setEditing] = useState<Category | null>(null)
  const [deleting, setDeleting] = useState<Category | null>(null)
  const remove = useDeleteCategory()

  const range = periodRange(period)
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
  const periodLabel = PERIOD_OPTIONS.find((o) => o.value === period)?.label ?? ''

  return (
    <>
      <PageHeader
        title="Categories"
        description="How your money is grouped, with activity for the selected period."
        action={
          <>
            <Segmented label="Period" options={PERIOD_OPTIONS} value={period} onChange={setPeriod} />
            <Button onClick={() => setAdding('expense')}>
              <PlusIcon strokeWidth={2} /> Add category
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-label text-ink-subtle tabular-nums">
          <span className="font-semibold text-ink">{counts.all}</span> categories · {counts.expense} expense · {counts.income} income
        </p>
        <SearchInput label="Search categories" value={search} onChange={setSearch} placeholder="Search categories…" className="sm:w-64" />
      </div>

      {expenses.data && expenses.data.items.length > 0 && (
        <section className={`${cardClass} mb-4 p-5`} aria-labelledby="spending-map">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="spending-map" className={labelClass}>Spending · {periodLabel}</h2>
              <p className="mt-1 text-figure tabular-nums text-ink">{formatKzt(expenses.data.total_cents)}</p>
            </div>
            <p className="text-xs text-ink-subtle">Tile size shows each category’s share</p>
          </div>
          <LazyCategoryTreemap breakdown={expenses.data} height="h-44" />
        </section>
      )}

      {categories.isError ? (
        <div className={`${cardClass} p-4`}><ErrorState error={categories.error} onRetry={() => categories.refetch()} /></div>
      ) : categories.isPending ? (
        <div className={`${cardClass} px-4`}><SkeletonRows rows={6} label="Loading categories" /></div>
      ) : counts.all === 0 ? (
        <div className={cardClass}>
          <EmptyState
            title="No categories yet"
            description="Categories group your transactions."
            action={<Button size="sm" onClick={() => setAdding('expense')}><PlusIcon /> Add category</Button>}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {(['expense', 'income'] as const).map((type) => (
            <CategoryLedger
              key={type}
              type={type}
              categories={matching.filter((c) => c.type === type)}
              breakdown={type === 'expense' ? expenses : income}
              periodLabel={periodLabel}
              searching={term !== ''}
              onAdd={() => setAdding(type)}
              onEdit={setEditing}
              onDelete={setDeleting}
            />
          ))}
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
        onConfirm={() => deleting && remove.mutate(deleting.id, { onSuccess: closeDelete })}
        onClose={closeDelete}
      />
    </>
  )
}

type BreakdownQuery = { data?: CategoryBreakdown; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }

/** One ledger per type: each category with its backend total, share and count for the period. */
function CategoryLedger({ type, categories, breakdown, periodLabel, searching, onAdd, onEdit, onDelete }: {
  type: TransactionType
  categories: Category[]
  breakdown: BreakdownQuery
  periodLabel: string
  searching: boolean
  onAdd: () => void
  onEdit: (category: Category) => void
  onDelete: (category: Category) => void
}) {
  const income = type === 'income'
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'amount', dir: 'desc' })
  const byId = new Map((breakdown.data?.items ?? []).map((item) => [item.category_id, item]))
  // The full category list is loaded, so sorting here covers every row (ordering only, no maths).
  const value = (c: Category) =>
    sort.key === 'name' ? 0 : sort.key === 'count' ? (byId.get(c.id)?.transaction_count ?? 0) : (byId.get(c.id)?.total_cents ?? 0)
  const rows = [...categories].sort((a, b) => {
    const order = sort.key === 'name' ? a.name.localeCompare(b.name) : value(a) - value(b) || a.name.localeCompare(b.name)
    return sort.dir === 'asc' ? order : -order
  })
  const toggleSort = (key: SortKey) =>
    setSort((current) => (current.key === key ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'name' ? 'asc' : 'desc' }))
  const largest = breakdown.data?.items[0]?.total_cents ?? 0
  const amountHeader = income ? 'Earned' : 'Spent'

  return (
    <section className={cardClass} aria-labelledby={`ledger-${type}`}>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 id={`ledger-${type}`} className="text-heading text-ink">{income ? 'Income categories' : 'Expense categories'}</h2>
          <p className="mt-0.5 text-xs text-ink-subtle">{categories.length} shown · {periodLabel}</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className={labelClass}>{amountHeader}</p>
            {breakdown.isError ? (
              <p className="text-sm text-ink-subtle">—</p>
            ) : breakdown.data ? (
              <p className={`text-lg font-semibold tracking-tight tabular-nums ${income ? 'text-income' : 'text-ink'}`}>{formatKzt(breakdown.data.total_cents)}</p>
            ) : (
              <Skeleton className="mt-1 h-5 w-24" />
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={onAdd}><PlusIcon /> New</Button>
        </div>
      </div>

      {breakdown.isError && <div className="border-b border-line p-4"><ErrorState error={breakdown.error} onRetry={() => breakdown.refetch()} /></div>}

      {rows.length === 0 ? (
        <EmptyState
          size="sm"
          title={searching ? 'No categories match your search' : `No ${type} categories yet`}
          action={searching ? undefined : <Button size="sm" variant="secondary" onClick={onAdd}><PlusIcon /> Add one</Button>}
        />
      ) : (
        <>
          <ul className="divide-y divide-line md:hidden">
            {rows.map((c) => {
              const item = byId.get(c.id)
              return (
                <li key={c.id} className="group flex items-center gap-3 px-4 py-3">
                  <span className="size-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: c.color }} aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-label font-medium text-ink">{c.name}</p>
                    <p className="text-xs text-ink-subtle">{item ? `${item.transaction_count} transactions · ${item.percentage}%` : 'No activity'}</p>
                  </div>
                  <span className={`text-label font-semibold tabular-nums ${item ? 'text-ink' : 'text-ink-subtle'}`}>{item ? formatKzt(item.total_cents) : '—'}</span>
                  <RowActions category={c} onEdit={onEdit} onDelete={onDelete} />
                </li>
              )
            })}
          </ul>
          <table className={`${table.table} hidden md:table`}>
            <caption className="sr-only">{income ? 'Income categories' : 'Expense categories'}</caption>
            <thead>
              <tr>
                <SortHeader label="Category" sortKey="name" sort={sort} onSort={toggleSort} />
                <SortHeader label={amountHeader} sortKey="amount" sort={sort} onSort={toggleSort} className="w-36" align="right" />
                <th scope="col" className={`${flushTh} w-56`}>Share</th>
                <SortHeader label="Transactions" sortKey="count" sort={sort} onSort={toggleSort} className="w-36" align="right" />
                <th scope="col" className={`${flushTh} w-20`}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const item = byId.get(c.id)
                // Bar width is presentation only; the percentage text comes from the backend.
                const width = item && largest > 0 ? Math.max((item.total_cents / largest) * 100, 3) : 0
                return (
                  <tr key={c.id} className={table.row}>
                    <td className={table.td}>
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="size-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: c.color }} aria-hidden="true" />
                        <span className="truncate font-medium text-ink">{c.name}</span>
                        <span className="shrink-0 text-xs text-ink-subtle">{c.is_default ? 'Default' : 'Custom'}</span>
                      </div>
                    </td>
                    <td className={`${table.td} text-right font-semibold tabular-nums ${item ? (income ? 'text-income' : 'text-ink') : 'text-ink-subtle'}`}>
                      {breakdown.isPending ? <Skeleton className="ml-auto h-3 w-16" /> : item ? formatKzt(item.total_cents) : '—'}
                    </td>
                    <td className={table.td}>
                      <div className="flex items-center gap-2.5">
                        <div className="h-1 flex-1 bg-ink/[0.06]" aria-hidden="true">
                          <div className="h-1" style={{ width: `${width}%`, backgroundColor: c.color }} />
                        </div>
                        <span className="w-12 text-right text-xs text-ink-subtle tabular-nums">{item ? `${item.percentage}%` : '—'}</span>
                      </div>
                    </td>
                    <td className={`${table.td} text-right text-label tabular-nums ${item ? 'text-ink-muted' : 'text-ink-subtle'}`}>
                      {item ? item.transaction_count : 0}
                    </td>
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

type SortKey = 'name' | 'amount' | 'count'

/** Column header that sorts the ledger; announces the current order with aria-sort. */
function SortHeader({ label, sortKey, sort, onSort, className = '', align = 'left' }: {
  label: string
  sortKey: SortKey
  sort: { key: SortKey; dir: 'asc' | 'desc' }
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
        className={`inline-flex items-center gap-1 rounded-sm hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${active ? 'text-ink' : ''}`}
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

function RowActions({ category, onEdit, onDelete }: {
  category: Category
  onEdit: (category: Category) => void
  onDelete: (category: Category) => void
}) {
  return (
    <div className="flex shrink-0 justify-end gap-0.5 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:hover)]:opacity-0">
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
  onDone?: () => void
}) {
  const create = useCreateCategory()
  const update = useUpdateCategory()
  const mutation = category ? update : create

  const [name, setName] = useState(category?.name ?? '')
  const [type, setType] = useState<TransactionType>(category?.type ?? defaultType)
  const [color, setColor] = useState(category?.color ?? DEFAULT_COLOR)
  const [nameError, setNameError] = useState<string>()
  const [formError, setFormError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const idPrefix = category ? `edit-${category.id}` : 'new'

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    setSaved(null)
    const trimmed = name.trim()
    if (!trimmed) {
      setNameError('Enter a name.')
      return
    }
    setNameError(undefined)

    try {
      if (category) {
        await update.mutateAsync({ id: category.id, body: { name: trimmed, type, color } })
      } else {
        await create.mutateAsync({ name: trimmed, type, color })
        setName('')
        setSaved(`Added “${trimmed}”.`)
      }
      onDone?.()
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
          placeholder="e.g. Pets"
        />
      </Field>
      <Field
        id={`${idPrefix}-type`}
        label="Type"
        hint={category ? 'The type can only change while no transactions use this category.' : undefined}
      >
        <select
          id={`${idPrefix}-type`}
          value={type}
          onChange={(e) => setType(e.target.value as TransactionType)}
          aria-describedby={category ? `${idPrefix}-type-hint` : undefined}
          className={inputClass()}
        >
          <option value="expense">Expense</option>
          <option value="income">Income</option>
        </select>
      </Field>
      <Field id={`${idPrefix}-color`} label="Colour">
        <div className="flex items-center gap-3">
          <input
            id={`${idPrefix}-color`}
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="h-9 w-14 cursor-pointer rounded-lg border border-line bg-surface p-1"
          />
          <span className="font-mono text-xs text-ink-subtle">{color}</span>
        </div>
      </Field>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        {onDone && (
          <Button variant="secondary" onClick={onDone}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving…' : category ? 'Save changes' : (<><PlusIcon /> Add category</>)}
        </Button>
      </div>
      {saved && (
        <p role="status" className="text-sm text-emerald-700">
          {saved}
        </p>
      )}
    </form>
  )
}
