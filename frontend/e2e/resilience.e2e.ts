/**
 * Error boundaries (components/ErrorBoundary.tsx): one failing part never takes the app down.
 *
 * Failures are made with Playwright's request routing, so the production build needs no test
 * hooks: a chart's JavaScript file is unreachable (a tab opened before a deploy), or the API answers
 * with data that makes a component throw while rendering (an amount that isn't whole tiyn).
 */
import type { Page } from '@playwright/test'

import { addTransaction, entry, goTo, isoDate, kzt, ledger, mainNav } from './support/app'
import { expect, test } from './support/fixtures'

const CHART_CHUNK = '**/assets/MonthlyTrendChart-*.js'
const MONTHLY_TREND = /\/api\/analytics\/monthly-trend(\?|$)/
const TRANSACTION_LIST = /\/api\/transactions(\?|$)/
const CATEGORY_LIST = /\/api\/categories(\?|$)/

function cashFlow(page: Page) {
  return page.getByRole('region', { name: 'Cash flow' })
}

/** Six months whose amounts are not whole tiyn: drawing them throws (formatKzt's RangeError). */
function brokenTrend() {
  const months = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06']
  return { months: months.map((month) => ({ month, income_cents: 1050.5, expense_cents: 0, net_cents: 1050.5 })) }
}

function brokenTransactions() {
  const now = new Date().toISOString()
  const category = { id: 1, name: 'Groceries', type: 'expense', color: '#22c55e', is_default: true }
  return {
    items: [
      {
        id: 1,
        amount_cents: 1.5,
        type: 'expense',
        category_id: 1,
        category,
        description: 'Broken row',
        occurred_on: isoDate(),
        source: 'manual',
        created_at: now,
        updated_at: now,
      },
    ],
    total: 1,
    limit: 20,
    offset: 0,
  }
}

test.describe('Error boundaries', () => {
  test('a chart whose code fails to load is contained, reloads the page at most once, and loads when it can', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await addTransaction(page, { type: 'income', amount: '150 000', category: 'Salary', description: 'Pay' })
    await expect(cashFlow(page).getByText('Show as table')).toBeVisible() // the chart works

    // From now on the chart's file can't be fetched, as for a tab opened before a deploy.
    await page.route(CHART_CHUNK, (route) => route.abort())
    let loads = 0
    page.on('load', () => {
      loads += 1
    })
    await page.reload()

    // One automatic reload (a new build would be picked up), then the fallback: never a loop.
    await expect.poll(() => loads).toBe(2)
    const fallback = cashFlow(page).getByRole('alert')
    await expect(fallback).toContainText('This chart couldn’t load')
    await expect(fallback.getByRole('button', { name: 'Reload page' })).toBeVisible()
    await page.waitForTimeout(2_000)
    expect(loads).toBe(2)

    // Everything else on the dashboard still works.
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('150 000'))
    await expect(entry(page.getByRole('region', { name: 'Recent transactions' }), 'Pay')).toBeVisible()

    // So does the navigation, and coming back doesn't reload again.
    await goTo(page, 'Transactions')
    await expect(entry(ledger(page), 'Pay')).toBeVisible()
    await goTo(page, 'Dashboard')
    await expect(cashFlow(page).getByRole('alert')).toContainText('This chart couldn’t load')
    expect(loads).toBe(2)

    // The file is reachable again: "Try again" loads the chart in place, without a reload.
    await page.unroute(CHART_CHUNK)
    await cashFlow(page).getByRole('button', { name: 'Try again' }).click()
    await expect(cashFlow(page).getByText('Show as table')).toBeVisible()
    await expect(cashFlow(page).getByRole('alert')).toHaveCount(0)
    expect(loads).toBe(2)
  })

  test('a chart that throws while drawing is replaced by a message; the rest of the dashboard works', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.route(MONTHLY_TREND, (route) => route.fulfill({ json: brokenTrend() }))
    await page.goto('/')

    const fallback = cashFlow(page).getByRole('alert')
    await expect(fallback).toContainText('This chart couldn’t be shown')
    await expect(fallback.getByRole('button', { name: 'Reload page' })).toHaveCount(0) // not a loading problem
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('0'))
    await expect(page.getByRole('region', { name: 'Recent transactions' })).toContainText('No transactions yet')

    await goTo(page, 'Categories')
    await goTo(page, 'Dashboard')
    await expect(cashFlow(page).getByRole('alert')).toContainText('This chart couldn’t be shown')

    // Good data again: "Try again" fetches it and the chart area recovers.
    await page.unroute(MONTHLY_TREND)
    await cashFlow(page).getByRole('button', { name: 'Try again' }).click()
    await expect(cashFlow(page).getByText('No cash flow yet')).toBeVisible()
    await expect(cashFlow(page).getByRole('alert')).toHaveCount(0)
  })

  test('a page that throws shows a message in its place; navigation keeps working and the page recovers', { tag: '@mobile' }, async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.route(TRANSACTION_LIST, (route) =>
      route.request().method() === 'GET' ? route.fulfill({ json: brokenTransactions() }) : route.fallback(),
    )
    await page.goto('/transactions')

    const problem = page.getByRole('main').getByRole('alert')
    await expect(page.getByRole('heading', { level: 1, name: 'Something went wrong on this page' })).toBeVisible()
    await expect(problem).toContainText('Your saved data isn’t affected')
    await expect(problem).not.toContainText('1.5') // no technical detail on screen

    // The header and navigation are outside the failing page.
    await expect(page.getByRole('banner').getByRole('button', { name: 'Add transaction' })).toBeVisible()
    await goTo(page, 'Categories')
    await mainNav(page).getByRole('link', { name: 'Transactions' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Something went wrong on this page' })).toBeVisible()

    // The API answers properly again: "Try again" shows the real (empty) ledger.
    await page.unroute(TRANSACTION_LIST)
    await problem.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Transactions' })).toBeVisible()
    await expect(ledger(page)).toContainText('No transactions yet')
  })

  test('a transaction form that throws is contained in its dialog, which still closes', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    // A category without a name: the form's category picker throws while rendering.
    await page.route(CATEGORY_LIST, (route) =>
      route.fulfill({ json: [{ id: 1, name: null, type: 'expense', color: '#22c55e', is_default: true }] }),
    )

    await page.getByRole('banner').getByRole('button', { name: 'Add transaction' }).click()
    const dialog = page.getByRole('dialog', { name: 'New transaction' })
    await expect(dialog.getByRole('alert')).toContainText('This form couldn’t be shown')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toBeHidden()
    await goTo(page, 'Analytics') // the app around the dialog is unaffected

    // With proper categories, "Try again" brings the form back.
    await page.getByRole('banner').getByRole('button', { name: 'Add transaction' }).click()
    await expect(dialog.getByRole('alert')).toContainText('This form couldn’t be shown')
    await page.unroute(CATEGORY_LIST)
    await dialog.getByRole('button', { name: 'Try again' }).click()
    await expect(dialog.getByLabel('Amount')).toBeVisible()
    await expect(dialog.getByRole('alert')).toHaveCount(0)
  })
})
