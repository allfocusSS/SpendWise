import { describe, expect, it } from 'vitest'

import { formatDate, formatMonth, fromIsoDate, periodRange, toIsoDate } from './dates'

describe('toIsoDate / fromIsoDate', () => {
  it('uses the local calendar day, not UTC', () => {
    // 00:30 local time must stay on the same calendar day.
    expect(toIsoDate(new Date(2026, 9, 31, 0, 30))).toBe('2026-10-31')
    expect(toIsoDate(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05')
  })

  it('round-trips', () => {
    expect(toIsoDate(fromIsoDate('2024-02-29'))).toBe('2024-02-29')
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
})
