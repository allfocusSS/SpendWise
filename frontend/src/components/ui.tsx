import { useId, type ButtonHTMLAttributes, type ComponentType, type ReactNode, type SVGProps } from 'react'

import { formatKzt } from '../lib/money'
import { cardClass } from '../lib/styles'
import { AlertIcon, RefreshIcon, SearchIcon } from './icons'

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>

// --- Buttons ---------------------------------------------------------------------

const buttonVariants = {
  primary: 'bg-accent text-on-accent hover:bg-accent-strong focus-visible:outline-accent',
  secondary: 'border border-line-strong text-ink hover:bg-white/[0.04] focus-visible:outline-accent',
  danger: 'bg-danger text-on-accent hover:bg-danger-strong focus-visible:outline-danger',
  ghost: 'text-ink-muted hover:bg-white/5 hover:text-ink focus-visible:outline-accent',
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof buttonVariants
  size?: 'sm' | 'md' | 'lg'
}

const buttonSizes = { sm: 'h-8 px-3 text-label', md: 'h-9 px-3.5 text-sm', lg: 'h-11 px-5 text-sm' }

export function Button({ variant = 'primary', size = 'md', className = '', type = 'button', ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${buttonSizes[size]} ${buttonVariants[variant]} ${className}`}
      {...props}
    />
  )
}

/** Square icon-only button; `label` is required for screen readers. */
export function IconButton({ label, children, tone = 'default', className = '', ...props }: Omit<ButtonProps, 'variant' | 'size'> & {
  label: string
  tone?: 'default' | 'danger'
}) {
  const colors =
    tone === 'danger'
      ? 'text-ink-subtle hover:bg-danger-soft hover:text-danger focus-visible:outline-danger'
      : 'text-ink-subtle hover:bg-white/5 hover:text-ink focus-visible:outline-accent'
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`grid size-7 shrink-0 place-items-center rounded-md transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 ${colors} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

// --- Layout pieces ---------------------------------------------------------------

/** Card with an editorial header row (title, optional subtitle and action). */
export function Card({ title, subtitle, action, children, className = '', flush = false }: {
  title?: string
  subtitle?: string
  action?: ReactNode
  children: ReactNode
  className?: string
  /** Body without padding (tables run edge to edge under a hairline). */
  flush?: boolean
}) {
  const headingId = useId()
  return (
    <section className={`${cardClass} flex min-w-0 flex-col ${className}`} aria-labelledby={title ? headingId : undefined}>
      {(title || action) && (
        <div className={`flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-5 pt-4 ${flush ? 'border-b border-line pb-3' : 'pb-1'}`}>
          <div className="min-w-0">
            {title && (
              <h2 id={headingId} className="truncate text-heading text-ink">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 truncate text-label text-ink-subtle">{subtitle}</p>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </div>
      )}
      <div className={`flex-1 ${flush ? '' : 'px-5 pt-3 pb-5'}`}>{children}</div>
    </section>
  )
}

/** Page heading: title and one line of context, controls on the right. */
export function PageHeader({ title, description, action }: {
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 flex-1">
        <h1 className="text-title text-ink">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}

/** "View all →" style link placed in a section header. */
export const linkClass =
  'inline-flex items-center gap-1 rounded-sm text-label font-medium text-ink-muted underline-offset-4 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'

/** Open section: a heading row over a hairline rule, no box. For content that reads as a list or ledger. */
export function Section({ title, action, children, className = '' }: {
  title: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  const headingId = useId()
  return (
    <section className={`min-w-0 ${className}`} aria-labelledby={headingId}>
      <div className="flex items-end justify-between gap-3 pb-3">
        <h2 id={headingId} className="text-heading text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

// --- Inputs ----------------------------------------------------------------------

export function SearchInput({ label, value, onChange, placeholder, className = '' }: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  className?: string
}) {
  return (
    <div className={`relative ${className}`}>
      <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" />
      <input
        type="search"
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface-sunken pr-3 pl-9 text-base text-ink sm:h-9 sm:text-sm placeholder:text-ink-subtle/70 hover:border-line-strong focus:border-accent focus:ring-3 focus:ring-accent/15 focus:outline-none"
      />
    </div>
  )
}

/** Segmented toggle: hairline container with a raised active segment. */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string
  options: { value: T; label: string; icon?: IconComponent }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex max-w-full flex-wrap gap-0.5 rounded-[var(--radius-control)] border border-line bg-surface-sunken p-0.5">
      {options.map(({ value: optionValue, label: optionLabel, icon: Icon }) => {
        const active = value === optionValue
        return (
          <button
            key={optionValue}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(optionValue)}
            className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-label font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${
              active ? 'bg-surface-raised text-ink shadow-[0_1px_2px_rgb(0_0_0/0.4)] ring-1 ring-line-strong' : 'text-ink-subtle hover:text-ink'
            }`}
          >
            {Icon && <Icon className="size-3.5" />}
            {optionLabel}
          </button>
        )
      })}
    </div>
  )
}

// --- Loading / empty / error states ----------------------------------------------

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-ink-subtle">
      <span className="size-4 animate-spin rounded-full border-2 border-line border-t-ink-muted" aria-hidden="true" />
      {label}…
    </span>
  )
}

export function LoadingState({ label }: { label?: string }) {
  return (
    <div className="flex min-h-20 items-center justify-center py-5">
      <Spinner label={label} />
    </div>
  )
}

/** Placeholder block shown while data loads. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-white/[0.06] ${className}`} aria-hidden="true" />
}

/** Placeholder rows for lists and tables, with an accessible loading label. */
export function SkeletonRows({ rows = 4, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col divide-y divide-line">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-11 items-center gap-3">
          <Skeleton className="h-2.5 w-16" />
          <Skeleton className="h-2.5 w-1/3" />
          <Skeleton className="ml-auto h-2.5 w-16" />
        </div>
      ))}
    </div>
  )
}

/** Compact inline alert: one failing request never takes over the page. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-[var(--radius-control)] border border-danger/20 bg-danger-soft px-3 py-2 text-label text-danger">
      <AlertIcon className="size-4 shrink-0" />
      <span className="min-w-[10rem] flex-1">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold hover:bg-danger/10 focus-visible:outline-2 focus-visible:outline-danger"
        >
          <RefreshIcon className="size-3.5" />
          Try again
        </button>
      )}
    </div>
  )
}

/** Compact, quiet empty state: one line of text and, at most, one action. */
export function EmptyState({ title, description, action, size = 'md' }: {
  title: string
  description?: string
  action?: ReactNode
  size?: 'sm' | 'md'
}) {
  return (
    <div className={`flex flex-col items-center gap-1 text-center ${size === 'sm' ? 'py-5' : 'py-10'}`}>
      <p className="text-label font-medium text-ink">{title}</p>
      {description && <p className="max-w-sm text-label text-ink-subtle">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

/** Inline error banner for forms and dialogs (announced by screen readers). */
export function FormError({ message }: { message?: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="flex items-start gap-2 rounded-[var(--radius-control)] border border-danger/20 bg-danger-soft px-3 py-2 text-label text-danger">
      <AlertIcon className="mt-px size-4 shrink-0" />
      <span>{message}</span>
    </p>
  )
}

/** Short error for small figure widgets (inverse = on a solid colour card); full message for screen readers and on hover. */
export function InlineError({ error, onRetry, inverse = false }: { error: unknown; onRetry?: () => void; inverse?: boolean }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div role="alert" title={message} className="flex items-center gap-3">
      <p className={`flex items-center gap-1.5 text-label font-medium ${inverse ? 'text-white' : 'text-danger'}`}>
        <AlertIcon className="size-4 shrink-0" />
        Couldn’t load
        <span className="sr-only">: {message}</span>
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className={`inline-flex items-center gap-1 rounded text-xs font-semibold underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 ${
            inverse ? 'text-white focus-visible:outline-white' : 'text-ink focus-visible:outline-accent'
          }`}
        >
          <RefreshIcon className="size-3.5" />
          Try again
        </button>
      )}
    </div>
  )
}

// --- Figures ---------------------------------------------------------------------

/** Tiny column history (e.g. 6 months). Heights are presentation only; the last bar is emphasised. */
export function MiniBars({ values, color, label, className = 'h-8', restOpacity = 0.28, lastOpacity = 1 }: {
  values: number[]
  color: string
  label: string
  className?: string
  /** Opacity of the earlier bars and of the latest (emphasised) bar. */
  restOpacity?: number
  lastOpacity?: number
}) {
  const max = Math.max(...values, 0)
  return (
    <div className={`flex items-end gap-[3px] ${className}`} role="img" aria-label={label}>
      {values.map((v, i) => (
        <span
          key={i}
          className="w-1.5 flex-1 rounded-[2px]"
          style={{
            height: `${max > 0 ? Math.max((v / max) * 100, 8) : 8}%`,
            backgroundColor: color,
            opacity: i === values.length - 1 ? lastOpacity : restOpacity,
          }}
        />
      ))}
    </div>
  )
}

/**
 * Money in vs money out as one bar with a dot legend (widths are presentation only; the labelled
 * amounts come straight from the backend). `size="md"` is the thicker variant for hero modules.
 */
export function SplitBar({ outCents, inCents, inverse = false, size = 'sm' }: {
  outCents: number
  inCents: number
  inverse?: boolean
  size?: 'sm' | 'md'
}) {
  const empty = outCents === 0 && inCents === 0
  const track = inverse ? 'bg-black/20' : 'bg-white/[0.06]'
  const label = inverse ? 'text-white/90' : 'text-ink-subtle'
  const value = inverse ? 'text-white' : 'text-ink-muted'
  return (
    <div>
      <div className={`flex gap-[2px] overflow-hidden rounded-[2px] ${size === 'md' ? 'h-2' : 'h-1.5'} ${track}`} aria-hidden="true">
        {!empty && (
          <>
            {inCents > 0 && <span className="bg-income-chart" style={{ flexGrow: inCents }} />}
            {outCents > 0 && <span className="bg-expense-chart" style={{ flexGrow: outCents }} />}
          </>
        )}
      </div>
      <div className={`mt-2 flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs ${label}`}>
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="size-2 shrink-0 rounded-[2px] bg-income-chart" aria-hidden="true" />
          In <span className={`truncate font-medium tabular-nums ${value}`}>{formatKzt(inCents)}</span>
        </span>
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="size-2 shrink-0 rounded-[2px] bg-expense-chart" aria-hidden="true" />
          Out <span className={`truncate font-medium tabular-nums ${value}`}>{formatKzt(outCents)}</span>
        </span>
      </div>
    </div>
  )
}

/** Category as plain text with its colour swatch (the colour links it to the charts). */
export function CategoryBadge({ name, color }: { name: string; color: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-2 text-label text-ink-muted">
      <span className="size-2 shrink-0 rounded-[2px]" style={{ backgroundColor: color }} aria-hidden="true" />
      <span className="truncate">{name}</span>
    </span>
  )
}

// --- Form field wrapper ----------------------------------------------------------

/**
 * Label + control + hint/error. The control must use `id` and set
 * aria-describedby={describedBy(id, error, hint)} and aria-invalid itself.
 */
export function Field({ id, label, error, hint, children }: {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-label font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-ink-subtle">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
