/** Dashboard: empty state, totals after adding transactions, recent transactions, refresh. */
import { expect, test } from './support/fixtures'
import { addTransaction, entry, kzt } from './support/app'

test.describe('Dashboard', () => {
  test('a new account shows an empty dashboard', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')

    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('0'))
    await expect(page.getByRole('region', { name: /^Money in, / })).toContainText(kzt('0'))
    await expect(page.getByRole('region', { name: /^Money out, / })).toContainText(kzt('0'))
    await expect(page.getByRole('region', { name: /^Net savings, / })).toContainText('0 transactions')
    await expect(page.getByRole('region', { name: 'Cash flow' })).toContainText('No cash flow yet')
    await expect(page.getByRole('region', { name: 'Spending by category' })).toContainText('No spending in this period')
    await expect(page.getByRole('region', { name: 'Recent transactions' })).toContainText('No transactions yet')
  })

  test('balance, income, expenses, savings and recent transactions follow new transactions', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')

    await addTransaction(page, { type: 'income', amount: '450000', category: 'Salary', description: 'October salary' })
    await addTransaction(page, { type: 'expense', amount: '12 345,67', category: 'Groceries', description: 'Magnum weekly shop' })
    await addTransaction(page, { type: 'expense', amount: '50000', category: 'Transport', description: 'Monthly bus pass' })

    const expectTotals = async () => {
      // 450 000 − 12 345,67 − 50 000 = 387 654,33
      await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('387 654,33'))
      await expect(page.getByRole('region', { name: /^Money in, / })).toContainText(kzt('450 000'))
      await expect(page.getByRole('region', { name: /^Money out, / })).toContainText(kzt('62 345,67'))
      const savings = page.getByRole('region', { name: /^Net savings, / })
      await expect(savings).toContainText(kzt('387 654,33'))
      await expect(savings).toContainText('3 transactions')

      const recent = page.getByRole('region', { name: 'Recent transactions' })
      await expect(entry(recent, 'October salary')).toContainText(kzt('450 000', '+'))
      await expect(entry(recent, 'October salary')).toContainText('Salary')
      await expect(entry(recent, 'Magnum weekly shop')).toContainText(kzt('12 345,67', '−'))
      await expect(entry(recent, 'Monthly bus pass')).toContainText(kzt('50 000', '−'))
      await expect(page.getByRole('region', { name: 'Spending by category' }).getByRole('listitem')).toHaveText([
        /Transport.*80\.2%/,
        /Groceries.*19\.8%/,
      ])
    }

    await expectTotals()
    await page.reload()
    await expectTotals()
  })

  test('"All transactions" leads to the ledger', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await addTransaction(page, { type: 'expense', amount: '1500', category: 'Health', description: 'Pharmacy' })

    await page.getByRole('link', { name: /All transactions/ }).click()

    await expect(page.getByRole('heading', { level: 1, name: 'Transactions' })).toBeVisible()
    await expect(entry(page.getByRole('region', { name: 'Transaction ledger' }), 'Pharmacy')).toBeVisible()
  })
})
