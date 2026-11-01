import { useRef, useState, type FormEvent } from 'react'

import { ApiError, type Transaction, type TransactionType } from '../api/client'
import { useCategories, useSaveTransaction } from '../api/queries'
import { todayIso } from '../lib/dates'
import { parseKztToTiyn, tiynToInput } from '../lib/money'
import { describedBy, inputClass } from '../lib/styles'
import { CategoryIcon } from './CategoryIcon'
import { ArrowDownLeftIcon, ArrowUpRightIcon } from './icons'
import { Modal } from './Modal'
import { Button, Field, FormError, LoadingState } from './ui'

const AMOUNT_HINT = 'e.g. 2500 or 2 500,50'

type FormErrors = Partial<Record<'amount' | 'type' | 'category' | 'description' | 'date', string>>

// Backend field names → form field names, for FastAPI validation errors.
const SERVER_FIELDS: Record<string, keyof FormErrors> = {
  amount_cents: 'amount',
  type: 'type',
  category_id: 'category',
  description: 'description',
  occurred_on: 'date',
}

/** Add (transaction = null) or edit a transaction. `defaultType` preselects the type when adding. */
export function TransactionDialog({ open, transaction, defaultType = 'expense', onClose }: {
  open: boolean
  transaction: Transaction | null
  defaultType?: TransactionType
  onClose: () => void
}) {
  return (
    <Modal open={open} size="sheet" title={transaction ? 'Edit transaction' : 'New transaction'} onClose={onClose}>
      <TransactionForm transaction={transaction} defaultType={defaultType} onDone={onClose} />
    </Modal>
  )
}

function TransactionForm({ transaction, defaultType, onDone }: {
  transaction: Transaction | null
  defaultType: TransactionType
  onDone: () => void
}) {
  const categories = useCategories()
  const save = useSaveTransaction()
  const formRef = useRef<HTMLFormElement>(null)

  const [type, setType] = useState<TransactionType>(transaction?.type ?? defaultType)
  const [amount, setAmount] = useState(transaction ? tiynToInput(transaction.amount_cents) : '')
  const [categoryId, setCategoryId] = useState(transaction ? String(transaction.category_id) : '')
  const [description, setDescription] = useState(transaction?.description ?? '')
  const [date, setDate] = useState(transaction?.occurred_on ?? todayIso())
  const [errors, setErrors] = useState<FormErrors>({})
  const [formError, setFormError] = useState<string | null>(null)

  const options = (categories.data ?? []).filter((c) => c.type === type)
  const categoryHint =
    options.length === 0 ? `No ${type} categories yet. Add one on the Categories page.` : undefined

  function changeType(next: TransactionType) {
    setType(next)
    // A category belongs to one type; clear the choice if it no longer fits.
    if (!categories.data?.some((c) => String(c.id) === categoryId && c.type === next)) setCategoryId('')
  }

  function validate(): { errors: FormErrors; amountTiyn?: number } {
    const found: FormErrors = {}
    const parsed = parseKztToTiyn(amount)
    if (!parsed.ok) found.amount = parsed.error
    if (!categoryId) found.category = 'Choose a category.'
    if (!description.trim()) found.description = 'Enter a description.'
    if (!date) found.date = 'Choose a date.'
    return { errors: found, amountTiyn: parsed.ok ? parsed.tiyn : undefined }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    const result = validate()
    setErrors(result.errors)
    if (Object.keys(result.errors).length > 0 || result.amountTiyn === undefined) {
      focusFirstInvalid(result.errors)
      return
    }

    try {
      await save.mutateAsync({
        id: transaction?.id,
        body: {
          amount_cents: result.amountTiyn,
          type,
          category_id: Number(categoryId),
          description: description.trim(),
          occurred_on: date,
          source: transaction?.source ?? 'manual',
        },
      })
      onDone()
    } catch (error) {
      if (error instanceof ApiError) {
        const serverErrors: FormErrors = {}
        for (const [field, message] of Object.entries(error.fieldErrors)) {
          const formField = SERVER_FIELDS[field]
          if (formField) serverErrors[formField] = message
        }
        setErrors(serverErrors)
        setFormError(error.message)
      } else {
        setFormError('Could not save the transaction.')
      }
    }
  }

  /** After a failed submit, move focus to the first field (in visual order) that needs fixing. */
  function focusFirstInvalid(found: FormErrors) {
    const form = formRef.current
    if (!form) return
    const selectors: [keyof FormErrors, string][] = [
      ['amount', '#tx-amount'],
      ['category', 'input[name="category"]:checked, input[name="category"]'],
      ['date', '#tx-date'],
      ['description', '#tx-description'],
    ]
    const first = selectors.find(([field]) => found[field])
    if (first) form.querySelector<HTMLElement>(first[1])?.focus()
  }

  if (categories.isPending) return <LoadingState label="Loading categories" />
  if (categories.isError) return <FormError message={categories.error.message} />

  const primaryLabel = transaction ? 'Save changes' : type === 'income' ? 'Add income' : 'Add expense'

  return (
    <form ref={formRef} onSubmit={handleSubmit} noValidate className="flex flex-1 flex-col gap-6">
      <FormError message={formError} />

      <fieldset>
        <legend className="sr-only">Type</legend>
        <div className="grid grid-cols-2 gap-2">
          {(['expense', 'income'] as const).map((option) => {
            const active = type === option
            const income = option === 'income'
            const Icon = income ? ArrowDownLeftIcon : ArrowUpRightIcon
            return (
              <label
                key={option}
                className={`flex cursor-pointer items-center gap-3 rounded-[var(--radius-control)] border px-3 py-2.5 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
                  active
                    ? income
                      ? 'border-income/35 bg-income-soft'
                      : 'border-expense/35 bg-expense-soft'
                    : 'border-line bg-surface-sunken hover:border-line-strong'
                }`}
              >
                <input type="radio" name="type" value={option} checked={active} onChange={() => changeType(option)} className="sr-only" />
                <span
                  className={`grid size-8 shrink-0 place-items-center rounded-md ${
                    active ? (income ? 'bg-income-solid text-white' : 'bg-expense-solid text-white') : 'bg-surface-raised text-ink-subtle'
                  }`}
                  aria-hidden="true"
                >
                  <Icon className="size-4" strokeWidth={2} />
                </span>
                <span className="min-w-0">
                  <span className="block text-label font-semibold text-ink">{income ? 'Income' : 'Expense'}</span>
                  <span className="block truncate text-xs text-ink-subtle">{income ? 'Money coming in' : 'Money going out'}</span>
                </span>
              </label>
            )
          })}
        </div>
      </fieldset>

      <div>
        <label htmlFor="tx-amount" className="text-label font-medium text-ink">Amount</label>
        <div
          className={`mt-2 flex items-center gap-3 rounded-[var(--radius-control)] border bg-surface-sunken px-4 py-4 transition-colors focus-within:ring-3 ${
            errors.amount
              ? 'border-danger/60 focus-within:ring-danger/15'
              : 'border-line hover:border-line-strong focus-within:border-accent focus-within:ring-accent/15'
          }`}
        >
          <span className="text-2xl text-ink-subtle" aria-hidden="true">₸</span>
          <input
            id="tx-amount"
            inputMode="decimal"
            autoComplete="off"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            aria-invalid={!!errors.amount}
            aria-describedby={describedBy('tx-amount', errors.amount, AMOUNT_HINT)}
            className="w-full min-w-0 bg-transparent text-figure-lg tabular-nums text-ink caret-accent placeholder:text-ink-subtle/40 focus:outline-none"
            placeholder="0"
          />
        </div>
        {errors.amount ? (
          <p id="tx-amount-error" className="mt-1.5 text-xs font-medium text-danger">{errors.amount}</p>
        ) : (
          <p id="tx-amount-hint" className="mt-1.5 text-xs text-ink-subtle">{AMOUNT_HINT}</p>
        )}
      </div>

      <fieldset aria-describedby={errors.category ? 'tx-category-error' : categoryHint ? 'tx-category-hint' : undefined}>
        <legend className="mb-1.5 text-label font-medium text-ink">Category</legend>
        {options.length > 0 && (
          <div
            className={`grid grid-cols-2 gap-1.5 rounded-[var(--radius-control)] p-0.5 ${errors.category ? 'ring-1 ring-danger/50' : ''}`}
          >
            {options.map((c) => {
              const selected = categoryId === String(c.id)
              return (
                <label
                  key={c.id}
                  className={`flex min-w-0 cursor-pointer items-center gap-2 rounded-[var(--radius-control)] border px-2 py-1.5 text-label transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-accent ${
                    selected ? 'border-ink-muted bg-surface-raised font-medium text-ink' : 'border-line bg-surface-sunken text-ink-muted hover:border-line-strong hover:text-ink'
                  }`}
                >
                  <input
                    type="radio"
                    name="category"
                    value={c.id}
                    checked={selected}
                    onChange={() => setCategoryId(String(c.id))}
                    className="sr-only"
                  />
                  <CategoryIcon name={c.name} color={c.color} size="sm" />
                  <span className="truncate">{c.name}</span>
                </label>
              )
            })}
          </div>
        )}
        {categoryHint && !errors.category && (
          <p id="tx-category-hint" className="text-xs text-ink-subtle">{categoryHint}</p>
        )}
        {errors.category && (
          <p id="tx-category-error" className="mt-1.5 text-xs font-medium text-danger">{errors.category}</p>
        )}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-[10.5rem_1fr]">
        <Field id="tx-date" label="Date" error={errors.date}>
          <input
            id="tx-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            aria-invalid={!!errors.date}
            aria-describedby={describedBy('tx-date', errors.date)}
            className={inputClass(!!errors.date)}
          />
        </Field>
        <Field id="tx-description" label="Description" error={errors.description}>
          <input
            id="tx-description"
            value={description}
            maxLength={255}
            onChange={(e) => setDescription(e.target.value)}
            aria-invalid={!!errors.description}
            aria-describedby={describedBy('tx-description', errors.description)}
            className={inputClass(!!errors.description)}
            placeholder="e.g. Groceries at Magnum"
          />
        </Field>
      </div>

      <div className="sticky bottom-0 -mx-5 mt-auto flex flex-col-reverse gap-2 border-t border-line bg-surface px-5 py-4 sm:-mx-6 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="hidden text-xs text-ink-subtle sm:block">Amounts in tenge (₸)</p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <Button variant="secondary" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Saving…' : primaryLabel}
          </Button>
        </div>
      </div>
    </form>
  )
}
