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
