/** Shared Tailwind class strings so form controls look the same everywhere. */

export function inputClass(hasError = false): string {
  return [
    'block w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-900 shadow-sm',
    'placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-offset-0',
    'disabled:cursor-not-allowed disabled:bg-slate-50',
    hasError
      ? 'border-red-500 focus:border-red-500 focus:ring-red-200'
      : 'border-slate-300 focus:border-indigo-500 focus:ring-indigo-200',
  ].join(' ')
}

export const cardClass = 'rounded-2xl border border-slate-200 bg-white shadow-sm'

/** aria-describedby value pointing at a Field's error or hint paragraph. */
export function describedBy(id: string, error?: string, hint?: string): string | undefined {
  if (error) return `${id}-error`
  if (hint) return `${id}-hint`
  return undefined
}
