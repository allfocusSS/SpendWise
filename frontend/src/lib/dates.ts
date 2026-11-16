/**
 * Date helpers working in the user's local calendar. Dates are exchanged with the API as
 * "YYYY-MM-DD" strings; we never use toISOString() for them because it converts to UTC and
 * can shift the day (e.g. just after midnight in Almaty, UTC+5).
 */

const pad = (n: number) => String(n).padStart(2, '0')

export function toIsoDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Parse "YYYY-MM-DD" as a local calendar date. */
export function fromIsoDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

export function todayIso(now: Date = new Date()): string {
  return toIsoDate(now)
}

export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

export function endOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0)
}

/** First day of the month `months` months before `date`'s month. */
export function monthsAgo(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() - months, 1)
}

/** First day of the month `months` months after `date`'s month (negative: before). */
export function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, 1)
}

export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

/** Milliseconds from `now` to the next local midnight. */
export function msUntilNextDay(now: Date): number {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime() - now.getTime()
}

/** "2026-11": the month of `date`, as the API names months (MonthlyTrend's `month`). */
export function monthKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`
}

/** "2026-11" → 1 Nov 2026 (local). */
export function fromMonthKey(key: string): Date {
  return fromIsoDate(`${key}-01`)
}

// --- The Dashboard's month -----------------------------------------------------------------------

/**
 * The month the Dashboard shows: `selected` ("YYYY-MM") is a month the user went back to, null
 * means "the current month" and follows the calendar (a tab left open over midnight on the last
 * day moves on to the new month). A chosen month stays chosen.
 */
export function shownMonth(selected: string | null, today: Date): Date {
  return selected !== null && selected < monthKey(today) ? fromMonthKey(selected) : startOfMonth(today)
}

/**
 * The selection after stepping `delta` months from the shown month. Never past the current month;
 * reaching it returns null, so the Dashboard follows the calendar again.
 */
export function stepMonth(selected: string | null, today: Date, delta: number): string | null {
  const next = monthKey(addMonths(shownMonth(selected, today), delta))
  return next < monthKey(today) ? next : null
}

/**
 * The monthly-trend query for `months` months ending with `month`'s month. `until` is always sent,
 * as a date in the browser's calendar: left out, the server uses its own date, and in UTC that is
 * still the previous month for the first hours of a month in Almaty (UTC+5).
 */
export function trendWindow(month: Date, months: number): { months: number; until: string } {
  return { months, until: toIsoDate(startOfMonth(month)) }
}

export type DateRange = { date_from?: string; date_to?: string }

export type PeriodKey = 'this-month' | 'last-month' | 'last-3-months' | 'this-year' | 'all-time'

export const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: 'this-month', label: 'This month' },
  { key: 'last-month', label: 'Last month' },
  { key: 'last-3-months', label: 'Last 3 months' },
  { key: 'this-year', label: 'This year' },
  { key: 'all-time', label: 'All time' },
]

export function periodRange(key: PeriodKey, now: Date = new Date()): DateRange {
  switch (key) {
    case 'this-month':
      return { date_from: toIsoDate(startOfMonth(now)), date_to: toIsoDate(endOfMonth(now)) }
    case 'last-month': {
      const start = monthsAgo(now, 1)
      return { date_from: toIsoDate(start), date_to: toIsoDate(endOfMonth(start)) }
    }
    case 'last-3-months':
      return { date_from: toIsoDate(monthsAgo(now, 2)), date_to: toIsoDate(endOfMonth(now)) }
    case 'this-year':
      return {
        date_from: toIsoDate(new Date(now.getFullYear(), 0, 1)),
        date_to: toIsoDate(new Date(now.getFullYear(), 11, 31)),
      }
    case 'all-time':
      return {}
  }
}

const dayFormatter = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
const monthFormatter = new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric' })
const shortMonthFormatter = new Intl.DateTimeFormat('en-GB', { month: 'short' })

/** "2026-10-20" → "20 Oct 2026" */
export function formatDate(iso: string): string {
  return dayFormatter.format(fromIsoDate(iso))
}

/** "2026-10" → "Oct 2026" (or "Oct" with short=true) */
export function formatMonth(yearMonth: string, short = false): string {
  const date = fromIsoDate(`${yearMonth}-01`)
  return (short ? shortMonthFormatter : monthFormatter).format(date)
}

/**
 * A date range as a period label: "1–30 Nov 2026", "1 Dec 2025 – 31 Jan 2026", "From 1 Mar 2026",
 * "Until 31 Mar 2026", or "All time" when there is no bound (the API then uses every date).
 */
export function formatDateRange({ date_from, date_to }: DateRange): string {
  if (date_from && date_to) return dayFormatter.formatRange(fromIsoDate(date_from), fromIsoDate(date_to))
  if (date_from) return `From ${formatDate(date_from)}`
  if (date_to) return `Until ${formatDate(date_to)}`
  return 'All time'
}

/** "2025-12", "2026-11" → "Dec 2025 – Nov 2026" (the months a trend response covers). */
export function formatMonthSpan(first: string, last: string): string {
  return first === last ? formatMonth(first) : monthFormatter.formatRange(fromMonthKey(first), fromMonthKey(last))
}
