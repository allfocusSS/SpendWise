/**
 * Analytics, checked against known transactions entered through the UI.
 *
 * Expected figures are written out by hand (amounts in ₸, shares rounded half-up to 2 decimals
 * as the backend does); chart pixels are never asserted, only labels, totals and the
 * accessible table behind the cash-flow chart.
 */
import { expect, test } from './support/fixtures'
import {
  addTransaction,
  entry,
  firstOfThisMonth,
  goTo,
  isoDate,
  kzt,
  ledger,
  thisMonthLabel,
  type NewTransaction,
} from './support/app'
import type { Locator, Page } from '@playwright/test'

const THIS_MONTH: NewTransaction[] = [
  { type: 'income', amount: '500000', category: 'Salary', description: 'Salary', date: firstOfThisMonth() },
  { type: 'income', amount: '80000,50', category: 'Freelance', description: 'Freelance job', date: isoDate() },
  { type: 'expense', amount: '200000', category: 'Housing & utilities', description: 'Rent', date: firstOfThisMonth() },
  { type: 'expense', amount: '35 500,25', category: 'Groceries', description: 'Groceries', date: isoDate() },
  { type: 'expense', amount: '12000', category: 'Transport', description: 'Taxi', date: isoDate() },
]

/** The value shown next to a label in the totals row ("Money in" → "580 000,50 ₸"). */
function total(page: Page, label: string): Locator {
  return page
    .getByRole('region', { name: /^Totals/ })
    .getByRole('term')
    .filter({ hasText: new RegExp(`^${label}$`) })
    .locator('xpath=following-sibling::dd')
}

function breakdown(page: Page, title: 'Spending by category' | 'Income by category'): Locator {
  return page.getByRole('region', { name: title }).getByRole('listitem')
}

test.describe('Analytics', () => {
  test.beforeEach(async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/transactions')
    for (const tx of THIS_MONTH) await addTransaction(page, tx)
    await goTo(page, 'Analytics')
  })

  test('summary, category breakdowns and cash flow match the transactions', async ({ page }) => {
    await expect(page.getByRole('group', { name: 'Period' }).getByRole('button', { name: 'This month' })).toHaveAttribute('aria-pressed', 'true')

    // Income 580 000,50; expenses 247 500,25; net 332 500,25.
    await expect(total(page, 'Net change')).toHaveText(kzt('332 500,25'))
    await expect(total(page, 'Money in')).toHaveText(kzt('580 000,50'))
    await expect(total(page, 'Money out')).toHaveText(kzt('247 500,25'))
    await expect(total(page, 'Transactions')).toHaveText('5')

    await expect(breakdown(page, 'Spending by category')).toHaveText([
      new RegExp(`Housing & utilities.*${kzt('200 000').source}.*80\\.81%`),
      new RegExp(`Groceries.*${kzt('35 500,25').source}.*14\\.34%`),
      new RegExp(`Transport.*${kzt('12 000').source}.*4\\.85%`),
    ])
    await expect(breakdown(page, 'Income by category')).toHaveText([
      new RegExp(`Salary.*${kzt('500 000').source}.*86\\.21%`),
      new RegExp(`Freelance.*${kzt('80 000,50').source}.*13\\.79%`),
    ])

    const comparison = page.getByRole('region', { name: 'Income vs expenses' })
    await expect(comparison).toContainText('5 transactions')

    // The cash-flow chart's data, through its accessible table rather than its pixels.
    const cashFlow = page.getByRole('region', { name: 'Cash flow' })
    await cashFlow.getByText('Show as table').click()
    const table = cashFlow.getByRole('table', { name: 'Monthly income, expenses and net' })
    await expect(table.getByRole('row')).toHaveCount(13) // header + 12 months
    const month = table.getByRole('row', { name: new RegExp(`^${thisMonthLabel()}`) })
    await expect(month.getByRole('cell').nth(0)).toHaveText(kzt('580 000,50'))
    await expect(month.getByRole('cell').nth(1)).toHaveText(kzt('247 500,25'))
    await expect(month.getByRole('cell').nth(2)).toHaveText(kzt('332 500,25'))
  })

  test('analytics follow changes to transactions', async ({ page }) => {
    await expect(total(page, 'Money out')).toHaveText(kzt('247 500,25'))

    await goTo(page, 'Transactions')
    await ledger(page).getByRole('button', { name: 'Delete Taxi' }).click()
    await page.getByRole('dialog', { name: 'Delete transaction?' }).getByRole('button', { name: 'Delete' }).click()
    await expect(entry(ledger(page), 'Taxi')).toHaveCount(0)
    await goTo(page, 'Analytics')

    // Without the 12 000 taxi: expenses 235 500,25, net 344 500,25, four transactions.
    await expect(total(page, 'Money out')).toHaveText(kzt('235 500,25'))
    await expect(total(page, 'Net change')).toHaveText(kzt('344 500,25'))
    await expect(total(page, 'Transactions')).toHaveText('4')
    await expect(breakdown(page, 'Spending by category')).toHaveText([
      /Housing & utilities.*84\.93%/,
      /Groceries.*15\.07%/,
    ])
  })

  test('a period with no transactions shows empty states, not zeros dressed up as data', async ({ page }) => {
    await page.getByRole('group', { name: 'Period' }).getByRole('button', { name: 'Custom' }).click()
    await page.getByLabel('From', { exact: true }).fill('2020-01-01')
    await page.getByLabel('To', { exact: true }).fill('2020-01-31')

    await expect(total(page, 'Transactions')).toHaveText('0')
    await expect(page.getByRole('region', { name: 'Income vs expenses' })).toContainText('Nothing to compare yet')
    await expect(page.getByRole('region', { name: 'Spending by category' })).toContainText('No spending in this period')
  })
})
