import { ChevronLeftIcon, ChevronRightIcon } from '../icons'

const arrowClass =
  'grid size-9 shrink-0 place-items-center rounded-[9px] text-ink-muted transition-colors hover:bg-surface-raised hover:text-ink focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent max-lg:size-10 pointer-coarse:size-11'

/**
 * Previous / month / next, plus "This month" while a past month is shown. 36px targets with a
 * mouse, 44px on touch screens.
 */
export function MonthNavigator({ label, onPrevious, onNext, onCurrent, canGoNext }: {
  label: string
  onPrevious: () => void
  onNext: () => void
  /** Back to the current month (and to following the calendar). */
  onCurrent: () => void
  canGoNext: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {canGoNext ? (
        <button
          type="button"
          onClick={onCurrent}
          className="inline-flex h-10 items-center rounded-[var(--radius-control)] px-3 text-label font-semibold text-accent transition-colors hover:bg-surface hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus pointer-coarse:h-11"
        >
          This month
        </button>
      ) : null}
      <div role="group" aria-label="Month" className="inline-flex items-center gap-0.5 rounded-xl border border-line bg-surface p-[3px]">
        <button type="button" onClick={onPrevious} aria-label="Previous month" className={arrowClass}>
          <ChevronLeftIcon className="size-4" />
        </button>
        <span className="min-w-[136px] text-center text-sm font-semibold text-ink tabular-nums" aria-live="polite">
          {label}
        </span>
        <button type="button" onClick={onNext} disabled={!canGoNext} aria-label="Next month" className={arrowClass}>
          <ChevronRightIcon className="size-4" />
        </button>
      </div>
    </div>
  )
}
