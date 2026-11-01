import { useState, type FormEvent } from 'react'

import { ApiError, type Category, type TransactionType } from '../api/client'
import { useCategories, useCreateCategory, useDeleteCategory, useUpdateCategory } from '../api/queries'
import { PencilIcon, PlusIcon, TrashIcon } from '../components/icons'
import { ConfirmDialog, Modal } from '../components/Modal'
import { Button, Card, EmptyState, ErrorState, Field, FormError, LoadingState, PageHeader } from '../components/ui'
import { describedBy, inputClass } from '../lib/styles'

const DEFAULT_COLOR = '#64748b'

export function CategoriesPage() {
  const categories = useCategories()
  const [editing, setEditing] = useState<Category | null>(null)
  const [deleting, setDeleting] = useState<Category | null>(null)
  const remove = useDeleteCategory()

  function closeDelete() {
    setDeleting(null)
    remove.reset()
  }

  return (
    <>
      <PageHeader title="Categories" description="Group your income and expenses. Each category belongs to one type." />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Add a category" className="lg:col-span-1 lg:self-start">
          <CategoryForm />
        </Card>

        <div className="grid gap-6 sm:grid-cols-2 lg:col-span-2">
          {categories.isError ? (
            <div className="sm:col-span-2">
              <ErrorState error={categories.error} onRetry={() => categories.refetch()} />
            </div>
          ) : categories.isPending ? (
            <div className="sm:col-span-2">
              <LoadingState label="Loading categories" />
            </div>
          ) : (
            (['expense', 'income'] as const).map((type) => (
              <Card key={type} title={type === 'expense' ? 'Expense categories' : 'Income categories'}>
                <CategoryGroup
                  categories={categories.data.filter((c) => c.type === type)}
                  onEdit={setEditing}
                  onDelete={setDeleting}
                />
              </Card>
            ))
          )}
        </div>
      </div>

      <Modal open={editing !== null} title="Edit category" onClose={() => setEditing(null)}>
        {editing && <CategoryForm category={editing} onDone={() => setEditing(null)} />}
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        title="Delete category?"
        message={
          deleting && (
            <p>
              The category <strong>{deleting.name}</strong> will be deleted. Categories that still have
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

function CategoryGroup({ categories, onEdit, onDelete }: {
  categories: Category[]
  onEdit: (category: Category) => void
  onDelete: (category: Category) => void
}) {
  if (categories.length === 0) {
    return <EmptyState title="No categories yet" description="Add one with the form." />
  }
  return (
    <ul className="divide-y divide-slate-100">
      {categories.map((c) => (
        <li key={c.id} className="flex items-center gap-3 py-2.5">
          <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: c.color }} aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate text-sm text-slate-900">{c.name}</span>
          {c.is_default && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">Default</span>}
          <Button variant="ghost" size="sm" onClick={() => onEdit(c)} aria-label={`Edit ${c.name}`}>
            <PencilIcon />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onDelete(c)} aria-label={`Delete ${c.name}`}>
            <TrashIcon />
          </Button>
        </li>
      ))}
    </ul>
  )
}

/** Create (no `category`) or edit a category. */
function CategoryForm({ category, onDone }: { category?: Category; onDone?: () => void }) {
  const create = useCreateCategory()
  const update = useUpdateCategory()
  const mutation = category ? update : create

  const [name, setName] = useState(category?.name ?? '')
  const [type, setType] = useState<TransactionType>(category?.type ?? 'expense')
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
            className="h-9 w-14 cursor-pointer rounded border border-slate-300 bg-white p-1"
          />
          <span className="font-mono text-xs text-slate-500">{color}</span>
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
