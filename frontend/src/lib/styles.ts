/** Shared Tailwind class strings so controls, cards and tables look the same everywhere. */

/** Text input boundary and focus ring; `fieldFrame` alone is for a box that holds an input and a button. */
export function fieldFrame(hasError = false): string {
  return hasError
    ? 'border-danger focus:border-danger focus:ring-danger/20 focus-within:border-danger focus-within:ring-danger/20'
    : 'border-field focus:border-focus focus:ring-focus/25 focus-within:border-focus focus-within:ring-focus/25'
}

export function inputClass(hasError = false, size: 'md' | 'lg' = 'md'): string {
  return [
    // 16px text on phones prevents iOS zoom-on-focus; 14px from the sm breakpoint.
    'block w-full min-w-0 rounded-[var(--radius-control)] border bg-surface-raised px-3 text-base text-ink sm:text-sm',
    size === 'lg' ? 'h-12' : 'h-[42px] pointer-coarse:h-11',
    'placeholder:text-ink-subtle focus:outline-none focus:ring-3 focus:ring-offset-0',
    'disabled:cursor-not-allowed disabled:bg-surface-muted',
    fieldFrame(hasError),
  ].join(' ')
}

/** The Plum card: a borderless surface one layer above the canvas. */
export const cardClass = 'rounded-[var(--radius-card)] bg-surface'

/** Quiet sentence-case label above a figure. */
export const labelClass = 'text-label text-ink-subtle'

/**
 * Data table as a stack of bordered rows (the Plum ledger): rows sit 8px apart, each outlined with
 * rounded ends. No overflow on the wrapper so the header can stay sticky.
 */
export const table = {
  wrap: 'rounded-[var(--radius-card)] bg-surface px-5 pb-3',
  table: 'w-full table-fixed border-separate border-spacing-y-2 text-left text-sm',
  th: 'h-8 bg-surface px-3 text-xs font-semibold text-ink-subtle',
  row: 'group',
  td: 'h-[52px] border-y border-line-strong bg-white/[0.015] px-3 transition-colors group-hover:bg-surface-raised first:rounded-l-xl first:border-l last:rounded-r-xl last:border-r',
}

/** Header cell for a table that sits flush inside a card (same as th: rows carry their own borders). */
export const flushTh = table.th

/** aria-describedby value pointing at a Field's error or hint paragraph. */
export function describedBy(id: string, error?: string, hint?: string): string | undefined {
  if (error) return `${id}-error`
  if (hint) return `${id}-hint`
  return undefined
}

/** A translucent tint of a category colour, for dark surfaces (backend colours are "#rrggbb"). */
export function tint(color: string, percent = 12): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`
}
