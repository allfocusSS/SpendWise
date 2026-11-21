import {
  useId,
  useState,
  type ButtonHTMLAttributes,
  type ComponentType,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type SVGProps,
} from 'react'

import { formatKzt, formatSignedKzt } from '../lib/money'
import { cardClass, fieldFrame, inputClass } from '../lib/styles'
import { AlertIcon, ChevronDownIcon, RefreshIcon, SearchIcon } from './icons'

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>

// --- Buttons ---------------------------------------------------------------------

const buttonVariants = {
  primary: 'bg-brand text-on-accent hover:bg-brand-hover focus-visible:outline-focus',
  secondary: 'bg-surface-raised text-ink ring-1 ring-line-strong ring-inset hover:bg-surface-selected focus-visible:outline-focus',
  danger: 'bg-danger-strong text-white hover:brightness-110 focus-visible:outline-danger',
  ghost: 'text-ink-muted hover:bg-white/5 hover:text-ink focus-visible:outline-focus',
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof buttonVariants
  size?: 'sm' | 'md' | 'lg'
}

const buttonSizes = { sm: 'h-8 px-3 text-label', md: 'h-10 px-4 text-sm', lg: 'h-12 px-5 text-[15px]' }

export function Button({ variant = 'primary', size = 'md', className = '', type = 'button', ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-[var(--radius-control)] font-semibold whitespace-nowrap transition-[color,background-color,filter] focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${buttonSizes[size]} ${buttonVariants[variant]} ${className}`}
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
      ? 'text-danger hover:bg-danger-soft focus-visible:outline-danger'
      : 'text-ink-subtle hover:bg-white/5 hover:text-ink focus-visible:outline-focus'
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`grid size-8 shrink-0 place-items-center rounded-lg bg-surface-raised transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 ${colors} ${className}`}
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
        <div className={`flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5 px-5 pt-[18px] ${flush ? 'pb-3' : 'pb-1'}`}>
          <div className="min-w-0">
            {title && (
              <h2 id={headingId} className="text-heading text-ink">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-ink-subtle">{subtitle}</p>}
          </div>
          {action && <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-subtle">{action}</div>}
        </div>
      )}
      <div className={`flex-1 ${flush ? '' : 'px-5 pt-3 pb-[18px]'}`}>{children}</div>
    </section>
  )
}

/**
 * Page heading: title and one line of context, controls on the right. Below lg the title lives in
 * the app bar (the Layout's h1), so only the controls show here.
 */
export function PageHeader({ title, eyebrow, description, action }: {
  title: string
  /** A short line above the title, e.g. today's date. */
  eyebrow?: ReactNode
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={`mb-3.5 flex flex-col gap-3 lg:mb-[18px] lg:min-h-[52px] lg:flex-row lg:items-center lg:justify-between ${action ? '' : 'max-lg:hidden'}`}>
      <div className="hidden min-w-0 flex-1 lg:block">
        {eyebrow && <p className="text-label text-ink-subtle">{eyebrow}</p>}
        <h1 className="text-title text-ink">{title}</h1>
        {description && <p className="mt-0.5 text-label text-ink-subtle">{description}</p>}
      </div>
      {action && <div className="flex flex-wrap items-center gap-2.5 lg:shrink-0 lg:justify-end">{action}</div>}
    </div>
  )
}

/** "View all →" style link placed in a section header. */
export const linkClass =
  'inline-flex items-center gap-1 rounded-sm text-label font-semibold text-accent underline-offset-4 hover:text-accent-strong hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus'

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
        className="h-[42px] w-full rounded-[var(--radius-control)] border border-field bg-surface-raised pr-3 pl-9 text-base text-ink sm:text-sm placeholder:text-ink-subtle focus:border-focus focus:ring-3 focus:ring-focus/25 focus:outline-none pointer-coarse:h-11"
      />
    </div>
  )
}

/** A native select styled like the text inputs, with a chevron. `className` sizes the wrapper. */
export function Select({ className = '', hasError = false, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { hasError?: boolean }) {
  return (
    <div className={`relative ${className}`}>
      <select className={`${inputClass(hasError)} appearance-none pr-9`} {...props} />
      <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-subtle" />
    </div>
  )
}

/**
 * A password input with a Show / Hide button inside its border (the button says what it will do).
 * Takes the input's own props; the box carries the focus ring.
 */
export function PasswordInput({ hasError = false, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { hasError?: boolean }) {
  const [visible, setVisible] = useState(false)
  return (
    <div className={`flex h-12 items-center gap-1 rounded-[var(--radius-control)] border bg-surface-raised pr-1 focus-within:ring-3 ${fieldFrame(hasError)}`}>
      <input
        {...props}
        type={visible ? 'text' : 'password'}
        className="h-full min-w-0 flex-1 rounded-[var(--radius-control)] bg-transparent px-3 text-base text-ink focus:outline-none sm:text-sm"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="h-10 shrink-0 rounded-lg px-3 text-label font-semibold text-accent transition-colors hover:bg-white/5 hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-focus"
      >
        {visible ? 'Hide' : 'Show'}
        <span className="sr-only"> password</span>
      </button>
    </div>
  )
}

/** Segmented toggle: hairline container with a raised active segment. */
export function Segmented<T extends string>({ label, options, value, onChange, className = '' }: {
  label: string
  options: { value: T; label: string; icon?: IconComponent }[]
  value: T
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div role="group" aria-label={label} className={`inline-flex max-w-full flex-wrap gap-0.5 rounded-[11px] border border-line bg-surface p-[3px] ${className}`}>
      {options.map(({ value: optionValue, label: optionLabel, icon: Icon }) => {
        const active = value === optionValue
        return (
          <button
            key={optionValue}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(optionValue)}
            className={`inline-flex h-[34px] items-center justify-center gap-1.5 rounded-lg px-3.5 text-label whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus pointer-coarse:h-10 ${
              active ? 'bg-brand font-semibold text-on-accent' : 'font-medium text-ink-muted hover:text-ink'
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
  return <div className={`animate-pulse rounded-md bg-white/[0.07] ${className}`} aria-hidden="true" />
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

/** Decorative icon in a soft ring, above an empty state's title. */
export function EmptyIcon({ children }: { children: ReactNode }) {
  return (
    <span className="mb-2 grid size-10 place-items-center rounded-full bg-white/[0.04] text-ink-subtle ring-1 ring-line" aria-hidden="true">
      {children}
    </span>
  )
}

/** Compact, quiet empty state: one line of text and, at most, one action. */
export function EmptyState({ title, description, action, icon, size = 'md' }: {
  title: string
  description?: string
  action?: ReactNode
  /** Optional decorative icon above the title. */
  icon?: ReactNode
  size?: 'sm' | 'md'
}) {
  return (
    <div className={`flex flex-col items-center gap-1 text-center ${size === 'sm' ? 'py-5' : 'py-10'}`}>
      {icon ? <EmptyIcon>{icon}</EmptyIcon> : null}
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

/** A large amount with a quieter currency sign ("620 000 ₸"). Formatting only; true minus sign. */
export function Figure({ cents, signed = false }: { cents: number; signed?: boolean }) {
  const amount = (signed ? formatSignedKzt(cents) : formatKzt(cents).replace(/^-/, '−')).replace(/\s₸$/, '')
  return (
    <span className="tabular-nums">
      {amount}
      <span className="ml-1 text-[0.6em] font-medium tracking-normal text-ink-subtle">₸</span>
    </span>
  )
}

/** Category as plain text with its colour swatch (the colour links it to the charts). */
export function CategoryBadge({ name, color }: { name: string; color: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-2 text-label text-ink-muted">
      <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
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
      <label htmlFor={id} className="text-label font-medium text-ink-muted">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-ink-subtle">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="flex items-start gap-1.5 text-xs font-medium text-danger">
          <AlertIcon className="mt-px size-3.5 shrink-0" />
          {error}
        </p>
      )}
    </div>
  )
}
