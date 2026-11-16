/**
 * The browser's calendar against a UTC server, in Almaty (UTC+5): for the first five hours of a
 * month, UTC is still in the previous month. The date helpers must follow the local calendar.
 *
 * The time zone is set before the module is loaded: Intl formatters keep the zone they were
 * created in.
 */
import { describe, expect, it } from 'vitest'

// Node's process.env; the app's TypeScript settings have no Node types.
(globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.TZ = 'Asia/Almaty'
const { monthKey, msUntilNextDay, periodRange, shownMonth, toIsoDate, trendWindow } = await import('./dates')

// 02:30 on 1 March in Almaty is 21:30 on 28 February in UTC.
const earlyFirstOfMarch = new Date(Date.UTC(2026, 1, 28, 21, 30))
// Midnight on New Year's Day in Almaty is 19:00 on 31 December in UTC.
const newYearMidnight = new Date(Date.UTC(2025, 11, 31, 19, 0))

describe('in UTC+5', () => {
  it('really runs in Almaty time', () => {
    expect(new Date(Date.UTC(2026, 0, 1, 0, 0)).getHours()).toBe(5)
  })

  it('uses the local month while UTC is still in the previous one', () => {
    expect(earlyFirstOfMarch.toISOString().slice(0, 10)).toBe('2026-02-28') // what a UTC server sees
    expect(toIsoDate(earlyFirstOfMarch)).toBe('2026-03-01')
    expect(monthKey(earlyFirstOfMarch)).toBe('2026-03')
    expect(toIsoDate(shownMonth(null, earlyFirstOfMarch))).toBe('2026-03-01')
    expect(periodRange('this-month', earlyFirstOfMarch)).toEqual({ date_from: '2026-03-01', date_to: '2026-03-31' })
  })

  it('sends the local month as `until`, so the server never picks its UTC month', () => {
    expect(trendWindow(earlyFirstOfMarch, 6)).toEqual({ months: 6, until: '2026-03-01' })
    expect(trendWindow(newYearMidnight, 12)).toEqual({ months: 12, until: '2026-01-01' })
  })

  it('crosses into the new year by the local clock', () => {
    expect(newYearMidnight.toISOString().slice(0, 10)).toBe('2025-12-31')
    expect(toIsoDate(newYearMidnight)).toBe('2026-01-01')
    expect(periodRange('last-month', newYearMidnight)).toEqual({ date_from: '2025-12-01', date_to: '2025-12-31' })
  })

  it('times local midnight, not UTC midnight', () => {
    const almostMidnight = new Date(Date.UTC(2026, 0, 31, 18, 59, 30)) // 23:59:30 in Almaty
    expect(msUntilNextDay(almostMidnight)).toBe(30_000)
  })
})
