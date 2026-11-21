/**
 * Periods: every figure, chart and label covers the time it says it does (M7-02).
 *
 * The browser's clock is set with Playwright's clock (the app runs in Asia/Almaty, UTC+5); the
 * server keeps its real clock and its UTC calendar, which is the point: the app must ask for the
 * browser's months explicitly and never rely on the server's idea of "now".
 */
import type { Locator, Page } from '@playwright/test'

import { addTransaction, kzt } from './support/app'
import { expect, test } from './support/fixtures'

/** A moment in Almaty time, e.g. at('2026-01-15T12:00'). */
function at(localTime: string): Date {
  return new Date(`${localTime}:00+05:00`)
}

/**
 * Text as the app renders it. ICU's date ranges vary by version: thin spaces, and "1–31 Mar" or
 * "1 – 31 Mar". Spaces match any space, and the range dash may have spaces around it or not.
 */
function spaced(text: string): RegExp {
  const pattern = text
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\s*–\s*/g, '–')
    .replace(/ /g, '\\s')
    .replace(/–/g, '\\s?–\\s?')
  return new RegExp(pattern)
}

/** A full date as the Dashboard writes it ("Sunday 1 March 2026", with or without a comma). */
function day(text: string): RegExp {
  const [weekday, ...rest] = text.split(' ')
  return new RegExp(`${weekday},?\\s${rest.join('\\s')}`)
}

/** Every request for the monthly trend: its window ({ months, until }), in order. */
function watchTrend(page: Page): { months: string | null; until: string | null }[] {
  const seen: { months: string | null; until: string | null }[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname === '/api/analytics/monthly-trend') {
      seen.push({ months: url.searchParams.get('months'), until: url.searchParams.get('until') })
    }
  })
  return seen
}

const countFor = (seen: { until: string | null }[], until: string) => seen.filter((r) => r.until === until).length

function monthSelector(page: Page): Locator {
  return page.getByRole('group', { name: 'Month' })
}

function cashFlow(page: Page): Locator {
  return page.getByRole('region', { name: 'Cash flow' })
}

/** The months in the cash-flow chart's table, oldest first (opening the table if needed). */
async function chartMonths(page: Page): Promise<Locator> {
  const table = cashFlow(page).getByRole('table', { name: 'Monthly income, expenses and net' })
  if (!(await table.isVisible())) await cashFlow(page).getByText('Show as table').click()
  await expect(table).toBeVisible()
  return table.getByRole('rowheader')
}

function totals(page: Page): Locator {
  return page.getByRole('region', { name: /^Totals/ })
}

function total(page: Page, label: string): Locator {
  return totals(page).getByRole('term').filter({ hasText: new RegExp(`^${label}$`) }).locator('xpath=following-sibling::dd')
}

test.describe('Dashboard periods', () => {
  test('the history follows the selected month, across the turn of the year', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: at('2026-01-15T12:00') })
    const trend = watchTrend(page)
    await page.goto('/')
    await expect(monthSelector(page)).toContainText('January 2026')

    await addTransaction(page, { type: 'expense', amount: '5 000', category: 'Transport', description: 'July taxi', date: '2025-07-10' })
    await addTransaction(page, { type: 'income', amount: '100 000', category: 'Salary', description: 'December pay', date: '2025-12-10' })
    await addTransaction(page, { type: 'expense', amount: '30 000', category: 'Groceries', description: 'December food', date: '2025-12-20' })
    await addTransaction(page, { type: 'income', amount: '50 000', category: 'Salary', description: 'January pay', date: '2026-01-05' })

    // January: six months to January 2026 (July is outside the window).
    await expect(cashFlow(page)).toContainText('6 months to Jan 2026')
    await expect(await chartMonths(page)).toHaveText(['Aug 2025', 'Sept 2025', 'Oct 2025', 'Nov 2025', 'Dec 2025', 'Jan 2026'])
    expect(trend.at(-1)).toEqual({ months: '6', until: '2026-01-01' })

    // Back one month, into the previous year: everything that is monthly moves with it.
    await monthSelector(page).getByRole('button', { name: 'Previous month' }).click()
    await expect(monthSelector(page)).toContainText('December 2025')
    await expect(page.getByRole('region', { name: 'Money in, December 2025' })).toContainText(kzt('100 000'))
    await expect(page.getByRole('region', { name: 'Money out, December 2025' })).toContainText(kzt('30 000'))
    await expect(page.getByRole('region', { name: 'Money in, December 2025' })).toContainText(/vs Nov ·/) // compared with the month before
    await expect(cashFlow(page)).toContainText('6 months to Dec 2025')
    const months = await chartMonths(page)
    await expect(months).toHaveText(['Jul 2025', 'Aug 2025', 'Sept 2025', 'Oct 2025', 'Nov 2025', 'Dec 2025'])
    const december = cashFlow(page).getByRole('row', { name: /^Dec 2025/ })
    await expect(december.getByRole('cell')).toHaveText([kzt('100 000'), kzt('30 000'), kzt('70 000')])
    await expect(cashFlow(page).getByRole('row', { name: /^Jul 2025/ }).getByRole('cell').nth(1)).toHaveText(kzt('5 000'))
    expect(trend.at(-1)).toEqual({ months: '6', until: '2025-12-01' })
    // The net bars and the cash-flow chart's text alternative name the same window.
    await expect(page.getByRole('img', { name: 'Monthly net, 6 months to Dec 2025' })).toBeVisible()
    await expect(cashFlow(page)).toContainText('Income and expenses per month from Jul 2025 to Dec 2025')
    // The balance stays all-time and says so: 100 000 − 30 000 + 50 000 − 5 000.
    const balance = page.getByRole('region', { name: 'Total balance' })
    await expect(balance).toContainText('All time')
    await expect(balance).toContainText(kzt('115 000'))

    // Forward again: the current month, and no further.
    await monthSelector(page).getByRole('button', { name: 'Next month' }).click()
    await expect(monthSelector(page)).toContainText('January 2026')
    await expect(monthSelector(page).getByRole('button', { name: 'Next month' })).toBeDisabled()
  })

  test('just after midnight on the 1st in UTC+5 (still the previous month in UTC), everything is the new month', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    // 02:30 on 1 March in Almaty; the server's UTC calendar would say 28 February.
    await page.clock.install({ time: at('2026-03-01T02:30') })
    const trend = watchTrend(page)
    await page.goto('/')
    await expect(monthSelector(page)).toContainText('March 2026')
    await expect(page.getByText(day('Sunday 1 March 2026'))).toBeVisible()

    // The form's default date is the local day too.
    await addTransaction(page, { type: 'income', amount: '20 000', category: 'Salary', description: 'Early pay' })
    await expect(page.getByRole('region', { name: 'Money in, March 2026' })).toContainText(kzt('20 000'))
    await expect(cashFlow(page)).toContainText('6 months to Mar 2026')
    const months = await chartMonths(page)
    await expect(months.last()).toHaveText('Mar 2026')
    await expect(cashFlow(page).getByRole('row', { name: /^Mar 2026/ }).getByRole('cell').first()).toHaveText(kzt('20 000'))
    expect(trend.every((request) => request.until === '2026-03-01')).toBe(true)

    // Analytics agrees: "this month" is March, and the 12-month window ends with March.
    await page.goto('/analytics')
    await expect(totals(page)).toHaveAccessibleName(spaced('Totals, This month · 1–31 Mar 2026'))
    await expect(total(page, 'Money in')).toHaveText(kzt('20 000'))
    await expect(cashFlow(page)).toContainText(spaced('Last 12 months · Apr 2025 – Mar 2026'))
  })

  test('a tab left open over midnight moves on to the new day and month, but keeps a month the user chose', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: at('2026-01-31T23:59') })
    const trend = watchTrend(page)
    await page.goto('/')
    await expect(page.getByText(day('Saturday 31 January 2026'))).toBeVisible()
    await expect(monthSelector(page)).toContainText('January 2026')

    // Two minutes later it is February: the Dashboard follows the calendar on its own.
    await page.clock.fastForward('02:00')
    await expect(page.getByText(day('Sunday 1 February 2026'))).toBeVisible()
    await expect(monthSelector(page)).toContainText('February 2026')
    await expect(cashFlow(page)).toContainText('6 months to Feb 2026')
    await expect.poll(() => trend.at(-1)).toEqual({ months: '6', until: '2026-02-01' })

    // A month the user went back to stays chosen when the day changes again.
    await monthSelector(page).getByRole('button', { name: 'Previous month' }).click()
    await expect(monthSelector(page)).toContainText('January 2026')
    await page.clock.fastForward('24:00:00')
    await expect(page.getByText(day('Monday 2 February 2026'))).toBeVisible()
    await expect(monthSelector(page)).toContainText('January 2026')
    await monthSelector(page).getByRole('button', { name: 'Next month' }).click()
    await expect(monthSelector(page)).toContainText('February 2026')
    await expect(monthSelector(page).getByRole('button', { name: 'Next month' })).toBeDisabled()
  })

  test('each month keeps its own cached history, and a new transaction refreshes it', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: at('2026-01-15T12:00') })
    const trend = watchTrend(page)
    await page.goto('/')
    await expect(monthSelector(page)).toContainText('January 2026')
    await expect.poll(() => countFor(trend, '2026-01-01')).toBe(1)

    const previous = monthSelector(page).getByRole('button', { name: 'Previous month' })
    const next = monthSelector(page).getByRole('button', { name: 'Next month' })
    // The account is new, so the month shows in the cash-flow window (its tiles come with data).
    await previous.click()
    await expect(cashFlow(page)).toContainText('6 months to Dec 2025')
    await expect.poll(() => countFor(trend, '2025-12-01')).toBe(1)

    // Back and forth within the cache's lifetime: no new requests, the right data each time.
    await next.click()
    await expect(cashFlow(page)).toContainText('6 months to Jan 2026')
    await previous.click()
    await expect(cashFlow(page)).toContainText('6 months to Dec 2025')
    expect(countFor(trend, '2026-01-01')).toBe(1)
    expect(countFor(trend, '2025-12-01')).toBe(1)

    // A December transaction refreshes December's history, and January's on the way back.
    await addTransaction(page, { type: 'income', amount: '42 000', category: 'Freelance', description: 'December gig', date: '2025-12-12' })
    await expect(page.getByRole('region', { name: 'Money in, December 2025' })).toContainText(kzt('42 000'))
    await expect.poll(() => countFor(trend, '2025-12-01')).toBe(2)
    await expect((await chartMonths(page)).last()).toHaveText('Dec 2025')
    await expect(cashFlow(page).getByRole('row', { name: /^Dec 2025/ }).getByRole('cell').first()).toHaveText(kzt('42 000'))
    await next.click()
    await expect.poll(() => countFor(trend, '2026-01-01')).toBe(2)
  })
})

test.describe('Analytics periods', () => {
  test('every period says exactly what it covers; the 12-month charts say they are independent of it', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: at('2026-05-20T12:00') })
    await page.goto('/')
    await addTransaction(page, { type: 'income', amount: '300 000', category: 'Salary', description: 'May pay', date: '2026-05-05' })
    await addTransaction(page, { type: 'expense', amount: '40 000', category: 'Housing & utilities', description: 'May rent', date: '2026-05-06' })
    await addTransaction(page, { type: 'income', amount: '250 000', category: 'Salary', description: 'April pay', date: '2026-04-05' })
    await addTransaction(page, { type: 'expense', amount: '10 000', category: 'Shopping', description: 'Old purchase', date: '2025-03-10' })

    const trend = watchTrend(page)
    const summaries: string[] = []
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.pathname === '/api/analytics/summary') summaries.push(url.search)
    })
    await page.goto('/analytics')
    const period = page.getByRole('group', { name: 'Period' })

    // This month, with its dates; the figures are May's.
    await expect(totals(page)).toHaveAccessibleName(spaced('Totals, This month · 1–31 May 2026'))
    await expect(total(page, 'Money in')).toHaveText(kzt('300 000'))
    await expect(total(page, 'Transactions')).toHaveText('2')
    expect(summaries).toContain('?date_from=2026-05-01&date_to=2026-05-31')

    // The rolling charts: the months they really cover, and a note that the period doesn't apply.
    for (const title of ['Cash flow', 'Net by month']) {
      const card = page.getByRole('region', { name: title })
      await expect(card).toContainText(spaced('Last 12 months · Jun 2025 – May 2026'))
      await expect(card).toContainText('The period above doesn’t change this chart.')
    }
    await expect(await chartMonths(page)).toHaveCount(12)
    await expect((await chartMonths(page)).first()).toHaveText('Jun 2025')
    await expect((await chartMonths(page)).last()).toHaveText('May 2026')
    expect(trend).toEqual([{ months: '12', until: '2026-05-01' }]) // one request, shared by both charts

    // Last month: April's figures and dates; the 12-month window doesn't move.
    await period.getByRole('button', { name: 'Last month' }).click()
    await expect(totals(page)).toHaveAccessibleName(spaced('Totals, Last month · 1–30 Apr 2026'))
    await expect(total(page, 'Money in')).toHaveText(kzt('250 000'))
    await expect(total(page, 'Transactions')).toHaveText('1')
    expect(summaries).toContain('?date_from=2026-04-01&date_to=2026-04-30')
    await expect(cashFlow(page)).toContainText(spaced('Last 12 months · Jun 2025 – May 2026'))
    expect(trend).toHaveLength(1)

    // All time.
    await period.getByRole('button', { name: 'All time' }).click()
    await expect(totals(page)).toHaveAccessibleName('Totals, All time')
    await expect(total(page, 'Money in')).toHaveText(kzt('550 000'))
    await expect(total(page, 'Money out')).toHaveText(kzt('50 000'))
  })

  test('a custom range is labelled with the dates it applies, and an empty one says "All time"', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: at('2026-05-20T12:00') })
    await page.goto('/')
    await addTransaction(page, { type: 'income', amount: '300 000', category: 'Salary', description: 'May pay', date: '2026-05-05' })
    await addTransaction(page, { type: 'income', amount: '250 000', category: 'Salary', description: 'April pay', date: '2026-04-05' })
    await page.goto('/analytics')

    await page.getByRole('group', { name: 'Period' }).getByRole('button', { name: 'Custom' }).click()
    // No dates yet: the API returns all time, and the label says so (not "Custom").
    await expect(totals(page)).toHaveAccessibleName('Totals, All time')
    await expect(total(page, 'Money in')).toHaveText(kzt('550 000'))

    await page.getByLabel('From', { exact: true }).fill('2026-05-01')
    await expect(totals(page)).toHaveAccessibleName('Totals, From 1 May 2026')
    await expect(total(page, 'Money in')).toHaveText(kzt('300 000'))

    await page.getByLabel('From', { exact: true }).fill('')
    await page.getByLabel('To', { exact: true }).fill('2026-04-30')
    await expect(totals(page)).toHaveAccessibleName('Totals, Until 30 Apr 2026')
    await expect(total(page, 'Money in')).toHaveText(kzt('250 000'))

    await page.getByLabel('From', { exact: true }).fill('2026-04-01')
    await expect(totals(page)).toHaveAccessibleName(spaced('Totals, 1–30 Apr 2026'))
    await expect(total(page, 'Money in')).toHaveText(kzt('250 000'))

    // An impossible range shows no totals at all, only the error and the independent charts.
    await page.getByLabel('From', { exact: true }).fill('2026-05-01')
    await expect(page.getByRole('alert')).toContainText('“From” must be on or before “To”.')
    await expect(totals(page)).toHaveCount(0)
    await expect(cashFlow(page)).toContainText(spaced('Last 12 months · Jun 2025 – May 2026'))
  })
})
