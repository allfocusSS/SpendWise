import { useState, type FormEvent } from 'react'

import { ApiError, type Transaction, type TransactionType } from '../api/client'
import { useCategories, useSaveTransaction } from '../api/queries'
import { todayIso } from '../lib/dates'
import { parseKztToTiyn, tiynToInput } from '../lib/money'
import { describedBy, inputClass } from '../lib/styles'
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

/** Add (transaction = null) or edit a transaction. */
export function TransactionDialog({ open, transaction, onClose }: {
  open: boolean
  transaction: Transaction | null
  onClose: () => void
}) {
  return (
    <Modal open={open} title={transaction ? 'Edit transaction' : 'Add transaction'} onClose={onClose}>
      <TransactionForm transaction={transaction} onDone={onClose} />
    </Modal>
  )
}

function TransactionForm({ transaction, onDone }: { transaction: Transaction | null; onDone: () => void }) {
  const categories = useCategories()
  const save = useSaveTransaction()

  const [type, setType] = useState<TransactionType>(transaction?.type ?? 'expense')
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
    if (Object.keys(result.errors).length > 0 || result.amountTiyn === undefined) return

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

  if (categories.isPending) return <LoadingState label="Loading categories" />
  if (categories.isError) return <FormError message={categories.error.message} />

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <FormError message={formError} />

      <fieldset>
        <legend className="mb-1.5 text-sm font-medium text-slate-700">Type</legend>
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1">
          {(['expense', 'income'] as const).map((option) => (
            <label
              key={option}
              className={`cursor-pointer rounded-md px-3 py-1.5 text-center text-sm font-medium capitalize transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-indigo-600 ${
                type === option ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <input
                type="radio"
                name="type"
                value={option}
                checked={type === option}
                onChange={() => changeType(option)}
                className="sr-only"
              />
              {option}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="tx-amount" label="Amount (₸)" error={errors.amount} hint={AMOUNT_HINT}>
          <input
            id="tx-amount"
            inputMode="decimal"
            autoComplete="off"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            aria-invalid={!!errors.amount}
            aria-describedby={describedBy('tx-amount', errors.amount, AMOUNT_HINT)}
            className={inputClass(!!errors.amount)}
            placeholder="0"
          />
        </Field>
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
      </div>

      <Field
        id="tx-category"
        label="Category"
        error={errors.category}
        hint={categoryHint}
      >
        <select
          id="tx-category"
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          aria-invalid={!!errors.category}
          aria-describedby={describedBy('tx-category', errors.category, categoryHint)}
          className={inputClass(!!errors.category)}
        >
          <option value="">Choose a category…</option>
          {options.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
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

      <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : transaction ? 'Save changes' : 'Add transaction'}
        </Button>
      </div>
    </form>
  )
}
