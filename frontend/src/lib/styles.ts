/** Shared Tailwind class strings so controls, cards and tables look the same everywhere. */

export function inputClass(hasError = false): string {
  return [
    // 16px text on phones prevents iOS zoom-on-focus; 14px from the sm breakpoint.
    'block h-10 w-full min-w-0 rounded-[var(--radius-control)] border bg-surface-sunken px-3 text-base text-ink sm:h-9 sm:text-sm',
    'placeholder:text-ink-subtle/70 focus:outline-none focus:ring-3 focus:ring-offset-0',
    'disabled:cursor-not-allowed disabled:bg-surface-muted',
    hasError
      ? 'border-danger/60 focus:border-danger focus:ring-danger/15'
      : 'border-line hover:border-line-strong focus:border-accent focus:ring-accent/15',
  ].join(' ')
}

/** Bordered surface: 1px border, no shadow, tight radius. */
export const cardClass = 'rounded-[var(--radius-card)] border border-line bg-surface'

/** Quiet sentence-case label above a figure. */
export const labelClass = 'text-label text-ink-subtle'

/** Data table pieces: strong header row, compact rows, hairline separators. No overflow on the
 * wrapper so the header can stay sticky. */
export const table = {
  wrap: 'rounded-[var(--radius-card)] border border-line bg-surface',
  table: 'w-full table-fixed border-separate border-spacing-0 text-left text-sm',
  th: 'h-9 border-b border-line-strong bg-surface px-4 text-xs font-medium text-ink-subtle first:rounded-tl-[var(--radius-card)] last:rounded-tr-[var(--radius-card)]',
  row: 'group transition-colors hover:bg-white/[0.025]',
  td: 'h-11 border-b border-line px-4 group-last:border-b-0',
}

/** Header cell for a table that sits flush inside a card (no rounded corners of its own). */
export const flushTh = table.th.replace(/\s(first|last):rounded-\S+/g, '')

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
