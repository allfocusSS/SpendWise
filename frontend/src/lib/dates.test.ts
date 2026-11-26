import { describe, expect, it } from 'vitest'

import {
  addMonths,
  endOfMonth,
  formatDate,
  formatDateRange,
  formatMonth,
  formatMonthSpan,
  formatRecentDate,
  fromIsoDate,
  fromMonthKey,
  monthKey,
  msUntilNextDay,
  periodRange,
  shownMonth,
  startOfDay,
  stepMonth,
  toIsoDate,
  trendWindow,
} from './dates'

/**
 * ICU's range formatting varies by version (thin spaces; "1–30 Nov" or "1 – 30 Nov"): compare with
 * plain spaces and " – " around the range dash.
 */
const plain = (text: string) => text.replace(/\s/g, ' ').replace(/ *– */g, ' – ')

describe('toIsoDate / fromIsoDate', () => {
  it('uses the local calendar day, not UTC', () => {
    // 00:30 local time must stay on the same calendar day.
    expect(toIsoDate(new Date(2026, 9, 31, 0, 30))).toBe('2026-10-31')
    expect(toIsoDate(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05')
  })

  it('round-trips', () => {
    expect(toIsoDate(fromIsoDate('2024-02-29'))).toBe('2024-02-29')
  })

  it.each(['0001-01-01', '0099-12-31', '9999-12-31'])('preserves the calendar year of %s', (iso) => {
    expect(toIsoDate(fromIsoDate(iso))).toBe(iso)
    const key = iso.slice(0, 7)
    expect(monthKey(fromMonthKey(key))).toBe(key)
  })
})

describe('periodRange', () => {
  const now = new Date(2026, 0, 15) // 15 Jan 2026

  it.each([
    ['this-month', { date_from: '2026-01-01', date_to: '2026-01-31' }],
    ['last-month', { date_from: '2025-12-01', date_to: '2025-12-31' }],
    ['last-3-months', { date_from: '2025-11-01', date_to: '2026-01-31' }],
    ['this-year', { date_from: '2026-01-01', date_to: '2026-12-31' }],
    ['all-time', {}],
  ] as const)('%s', (key, expected) => {
    expect(periodRange(key, now)).toEqual(expected)
  })

  it('handles February in a leap year', () => {
    expect(periodRange('this-month', new Date(2028, 1, 10))).toEqual({
      date_from: '2028-02-01',
      date_to: '2028-02-29',
    })
  })
})

describe('formatting', () => {
  it('formats dates and months', () => {
    expect(formatDate('2026-10-20')).toBe('20 Oct 2026')
    expect(formatMonth('2026-10')).toBe('Oct 2026')
    expect(formatMonth('2026-10', true)).toBe('Oct')
  })

  it('formats recent dates relative to today, in the local calendar', () => {
    const today = new Date(2026, 10, 17, 0, 30) // just after midnight
    expect(formatRecentDate('2026-11-17', today)).toBe('Today')
    expect(formatRecentDate('2026-11-16', today)).toBe('Yesterday')
    expect(formatRecentDate('2026-11-15', today)).toBe('Sun 15 Nov')
    expect(formatRecentDate('2026-01-01', today)).toBe('Thu 1 Jan')
    expect(formatRecentDate('2025-12-31', today)).toBe('31 Dec 2025')
    // Across a daylight-saving change the day count still rounds to whole days.
    expect(formatRecentDate('2026-03-28', new Date(2026, 2, 29, 23, 0))).toBe('Yesterday')
  })
})

describe('month arithmetic', () => {
  it('crosses year boundaries both ways', () => {
    expect(toIsoDate(addMonths(new Date(2026, 0, 15), -1))).toBe('2025-12-01')
    expect(toIsoDate(addMonths(new Date(2025, 11, 31), 1))).toBe('2026-01-01')
    expect(toIsoDate(addMonths(new Date(2026, 2, 31), -13))).toBe('2025-02-01')
  })

  it('knows the length of February in leap and common years', () => {
    expect(toIsoDate(endOfMonth(new Date(2024, 1, 10)))).toBe('2024-02-29')
    expect(toIsoDate(endOfMonth(new Date(2025, 1, 10)))).toBe('2025-02-28')
    expect(toIsoDate(endOfMonth(new Date(2000, 1, 10)))).toBe('2000-02-29') // divisible by 400
    expect(toIsoDate(endOfMonth(new Date(2100, 1, 10)))).toBe('2100-02-28') // divisible by 100
  })

  it('normalizes early and final-year dates without shifting the year', () => {
    const leapDay = fromIsoDate('0004-02-29')
    const endOfCalendar = fromIsoDate('9999-12-31')
    expect(toIsoDate(endOfMonth(fromIsoDate('0001-01-20')))).toBe('0001-01-31')
    expect(toIsoDate(endOfMonth(leapDay))).toBe('0004-02-29')
    expect(toIsoDate(endOfMonth(endOfCalendar))).toBe('9999-12-31')
    expect(toIsoDate(addMonths(fromIsoDate('0099-12-31'), 1))).toBe('0100-01-01')
    expect(toIsoDate(addMonths(fromIsoDate('0100-01-01'), -1))).toBe('0099-12-01')
    expect(trendWindow(leapDay, 6)).toEqual({ months: 6, until: '0004-02-01' })
    expect(trendWindow(endOfCalendar, 6)).toEqual({ months: 6, until: '9999-12-01' })
    expect(periodRange('this-year', leapDay)).toEqual({ date_from: '0004-01-01', date_to: '0004-12-31' })
    expect(periodRange('last-month', fromIsoDate('0099-02-10'))).toEqual({
      date_from: '0099-01-01',
      date_to: '0099-01-31',
    })
    expect(toIsoDate(startOfDay(leapDay))).toBe('0004-02-29')
    expect(msUntilNextDay(leapDay)).toBe(24 * 60 * 60 * 1000)
  })

  it('names months as the API does, and back', () => {
    expect(monthKey(new Date(2025, 11, 31, 23, 59))).toBe('2025-12')
    expect(toIsoDate(fromMonthKey('2025-12'))).toBe('2025-12-01')
  })

  it('periods cross the year and handle leap years', () => {
    expect(periodRange('last-month', new Date(2026, 0, 1))).toEqual({ date_from: '2025-12-01', date_to: '2025-12-31' })
    expect(periodRange('last-3-months', new Date(2028, 1, 29))).toEqual({ date_from: '2027-12-01', date_to: '2028-02-29' })
  })
})

describe('midnight', () => {
  it('counts the time to the next local midnight', () => {
    expect(msUntilNextDay(new Date(2026, 0, 31, 23, 59, 30))).toBe(30_000)
    expect(msUntilNextDay(new Date(2025, 11, 31, 0, 0, 0))).toBe(24 * 60 * 60 * 1000)
    expect(msUntilNextDay(new Date(2024, 1, 28, 12, 0, 0))).toBe(12 * 60 * 60 * 1000) // to 29 Feb
  })

  it('reduces a moment to its day', () => {
    expect(startOfDay(new Date(2026, 4, 20, 17, 45)).getTime()).toBe(new Date(2026, 4, 20).getTime())
  })
})

describe('the Dashboard month (shownMonth / stepMonth)', () => {
  const jan15 = new Date(2026, 0, 15)

  it('shows the current month until the user goes back', () => {
    expect(toIsoDate(shownMonth(null, jan15))).toBe('2026-01-01')
    expect(toIsoDate(shownMonth('2025-11', jan15))).toBe('2025-11-01')
  })

  it('steps back across the year and forward again to "current"', () => {
    const december = stepMonth(null, jan15, -1)
    expect(december).toBe('2025-12')
    expect(stepMonth(december, jan15, -1)).toBe('2025-11')
    expect(stepMonth(december, jan15, 1)).toBeNull() // back to the current month: follow the calendar
  })

  it('never goes past the current month', () => {
    expect(stepMonth(null, jan15, 1)).toBeNull()
    expect(toIsoDate(shownMonth('2026-02', jan15))).toBe('2026-01-01') // a stale future choice
  })

  it('at a month rollover, "current" moves on and a chosen month stays', () => {
    const lastEvening = new Date(2026, 0, 31)
    const nextMorning = new Date(2026, 1, 1)
    expect(toIsoDate(shownMonth(null, lastEvening))).toBe('2026-01-01')
    expect(toIsoDate(shownMonth(null, nextMorning))).toBe('2026-02-01')
    expect(toIsoDate(shownMonth('2025-12', nextMorning))).toBe('2025-12-01')
    // The month that was current is now a past month the user can step forward from.
    expect(stepMonth('2025-12', nextMorning, 1)).toBe('2026-01')
    expect(stepMonth('2026-01', nextMorning, 1)).toBeNull()
  })

  it('asks the API for the history ending with the shown month, always with a local `until`', () => {
    expect(trendWindow(jan15, 6)).toEqual({ months: 6, until: '2026-01-01' })
    expect(trendWindow(shownMonth('2025-12', jan15), 6)).toEqual({ months: 6, until: '2025-12-01' })
    // Any day of a month gives the same window (and the same cache key).
    expect(trendWindow(new Date(2026, 0, 31, 23, 59), 6)).toEqual(trendWindow(jan15, 6))
  })
})

describe('period labels', () => {
  it('describes a date range the way the API applies it', () => {
    expect(plain(formatDateRange({ date_from: '2026-11-01', date_to: '2026-11-30' }))).toBe('1 – 30 Nov 2026')
    expect(plain(formatDateRange({ date_from: '2025-12-01', date_to: '2026-01-31' }))).toBe('1 Dec 2025 – 31 Jan 2026')
    expect(plain(formatDateRange({ date_from: '2028-02-01', date_to: '2028-02-29' }))).toBe('1 – 29 Feb 2028')
    expect(formatDateRange({ date_from: '2026-03-01' })).toBe('From 1 Mar 2026')
    expect(formatDateRange({ date_to: '2026-03-31' })).toBe('Until 31 Mar 2026')
    expect(formatDateRange({})).toBe('All time') // no bounds: the API uses every date
  })

  it('describes the months a trend covers', () => {
    expect(plain(formatMonthSpan('2025-12', '2026-11'))).toBe('Dec 2025 – Nov 2026')
    expect(plain(formatMonthSpan('2026-06', '2026-11'))).toBe('Jun – Nov 2026')
    expect(formatMonthSpan('2026-11', '2026-11')).toBe('Nov 2026')
  })
})
