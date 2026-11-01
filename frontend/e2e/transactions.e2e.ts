/** Transactions: create, list, filters, edit, delete, validation and persistence. */
import { expect, test } from './support/fixtures'
import { addTransaction, entry, fillTransaction, kzt, ledger, type NewTransaction } from './support/app'

const LEDGER: NewTransaction[] = [
  { type: 'income', amount: '450000', category: 'Salary', description: 'Salary September', date: '2026-09-05' },
  { type: 'expense', amount: '12 345,67', category: 'Groceries', description: 'Groceries Magnum', date: '2026-09-10' },
  { type: 'expense', amount: '1500', category: 'Transport', description: 'Bus ticket', date: '2026-10-02' },
  { type: 'income', amount: '80000,50', category: 'Freelance', description: 'Logo design', date: '2026-10-12' },
]

test.describe('Transactions', () => {
  test.beforeEach(async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/transactions')
    await expect(page.getByRole('heading', { level: 1, name: 'Transactions' })).toBeVisible()
  })

  test('create income and expense; they appear in the ledger and the totals', async ({ page }) => {
    await expect(ledger(page)).toContainText('No transactions yet')

    await addTransaction(page, LEDGER[0])
    await addTransaction(page, LEDGER[1])

    await expect(entry(ledger(page), 'Salary September')).toContainText(kzt('450 000', '+'))
    await expect(entry(ledger(page), 'Salary September')).toContainText('Salary')
    await expect(entry(ledger(page), 'Groceries Magnum')).toContainText(kzt('12 345,67', '−'))
    await expect(ledger(page)).toContainText('2 transactions')

    const totals = page.getByRole('region', { name: /^Totals/ })
    await expect(totals).toContainText(kzt('437 654,33')) // net change
    await expect(totals).toContainText(kzt('450 000'))
    await expect(totals).toContainText(kzt('12 345,67'))

    await page.reload()
    await expect(entry(ledger(page), 'Salary September')).toBeVisible()
    await expect(entry(ledger(page), 'Groceries Magnum')).toBeVisible()
  })

  test('newest first, and every filter narrows the list', async ({ page }) => {
    for (const tx of LEDGER) await addTransaction(page, tx)
    const rows = ledger(page).locator('tbody tr, ul > li').filter({ visible: true })
    // Retrying assertions on the rows' content (not just their count), newest first.
    const expectRows = (...descriptions: string[]) => expect(rows).toHaveText(descriptions.map((d) => new RegExp(d)))

    await expectRows('Logo design', 'Bus ticket', 'Groceries Magnum', 'Salary September')

    const type = page.getByRole('group', { name: 'Type' })
    await type.getByRole('button', { name: 'Income' }).click()
    await expectRows('Logo design', 'Salary September')
    await type.getByRole('button', { name: 'Expenses' }).click()
    await expectRows('Bus ticket', 'Groceries Magnum')
    await type.getByRole('button', { name: 'All' }).click()
    await expectRows('Logo design', 'Bus ticket', 'Groceries Magnum', 'Salary September')

    await page.getByLabel('Category', { exact: true }).selectOption({ label: 'Transport' })
    await expectRows('Bus ticket')
    await page.getByLabel('Category', { exact: true }).selectOption({ label: 'All categories' })

    await page.getByLabel('From', { exact: true }).fill('2026-10-01')
    await expectRows('Logo design', 'Bus ticket')
    await page.getByLabel('To', { exact: true }).fill('2026-10-05')
    await expectRows('Bus ticket')

    await page.getByLabel('To', { exact: true }).fill('2026-09-01') // before "From"
    await expect(page.getByRole('alert')).toHaveText('“From” must be on or before “To”.')

    await page.getByRole('button', { name: 'Clear', exact: true }).click()
    await expectRows('Logo design', 'Bus ticket', 'Groceries Magnum', 'Salary September')

    await page.getByRole('searchbox', { name: 'Search transactions on this page' }).fill('magnum')
    await expectRows('Groceries Magnum')
  })

  test('edit a transaction', async ({ page }) => {
    await addTransaction(page, LEDGER[1])

    await ledger(page).getByRole('button', { name: 'Edit Groceries Magnum' }).click()
    const dialog = page.getByRole('dialog', { name: 'Edit transaction' })
    await expect(dialog.getByLabel('Amount')).toHaveValue('12345.67')
    await expect(dialog.getByLabel('Description')).toHaveValue('Groceries Magnum')
    await fillTransaction(dialog, { amount: '9 999', category: 'Restaurants & cafes', description: 'Dinner out' })
    await dialog.getByRole('button', { name: 'Save changes' }).click()
    await expect(dialog).toBeHidden()

    await expect(entry(ledger(page), 'Dinner out')).toContainText(kzt('9 999', '−'))
    await expect(entry(ledger(page), 'Dinner out')).toContainText('Restaurants & cafes')
    await expect(entry(ledger(page), 'Groceries Magnum')).toHaveCount(0)

    await page.reload()
    await expect(entry(ledger(page), 'Dinner out')).toContainText(kzt('9 999', '−'))
  })

  test('delete a transaction (with confirmation)', async ({ page }) => {
    await addTransaction(page, LEDGER[2])
    await addTransaction(page, LEDGER[3])

    await ledger(page).getByRole('button', { name: 'Delete Bus ticket' }).click()
    const confirm = page.getByRole('dialog', { name: 'Delete transaction?' })
    await expect(confirm).toContainText('Bus ticket')
    await confirm.getByRole('button', { name: 'Cancel' }).click()
    await expect(entry(ledger(page), 'Bus ticket')).toBeVisible()

    await ledger(page).getByRole('button', { name: 'Delete Bus ticket' }).click()
    await confirm.getByRole('button', { name: 'Delete' }).click()
    await expect(confirm).toBeHidden()
    await expect(entry(ledger(page), 'Bus ticket')).toHaveCount(0)
    await expect(ledger(page)).toContainText('1 transaction')

    await page.reload()
    await expect(entry(ledger(page), 'Bus ticket')).toHaveCount(0)
    await expect(entry(ledger(page), 'Logo design')).toBeVisible()
  })

  test('the form explains invalid input and saves nothing', async ({ page }) => {
    await page.getByRole('banner').getByRole('button', { name: 'Add transaction' }).click()
    const dialog = page.getByRole('dialog', { name: 'New transaction' })

    await dialog.getByRole('button', { name: 'Add expense' }).click()
    await expect(dialog.getByText('Enter a description.')).toBeVisible()
    await expect(dialog.getByLabel('Amount')).toHaveAttribute('aria-invalid', 'true')

    await fillTransaction(dialog, { amount: '12.345.6', category: 'Groceries', description: 'Typo' })
    await dialog.getByRole('button', { name: 'Add expense' }).click()
    await expect(dialog.getByLabel('Amount')).toHaveAttribute('aria-invalid', 'true')
    await expect(dialog).toBeVisible()

    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(ledger(page)).toContainText('No transactions yet')
  })
})
