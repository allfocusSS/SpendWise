/** Per-user isolation: two people in two separate browsers never see each other's data. */
import { expect, test } from './support/fixtures'
import { addTransaction, categoryNames, entry, goTo, kzt, ledger, logOut } from './support/app'

test.describe('Per-user isolation', () => {
  test("one user's transactions, categories and analytics are invisible to another", async ({ page, account, openUser }) => {
    // Alice (this page's user) records private data through the UI.
    expect(account.email).toBeTruthy()
    await page.goto('/categories')
    await page.getByRole('button', { name: 'Add category' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'New category' })
    await dialog.getByLabel('Name').fill('Alice private')
    await dialog.getByRole('button', { name: 'Add category' }).click()
    await expect(dialog).toBeHidden()
    await addTransaction(page, { type: 'expense', amount: '777 777', category: 'Alice private', description: 'Alice secret' })
    await addTransaction(page, { type: 'income', amount: '1 000 000', category: 'Salary', description: 'Alice salary' })
    await goTo(page, 'Transactions')
    await expect(entry(ledger(page), 'Alice secret')).toBeVisible()

    // Bob, in his own browser.
    const bob = await openUser('bob')
    await bob.page.goto('/transactions')
    await expect(ledger(bob.page)).toContainText('No transactions yet')
    await expect(bob.page.getByText('Alice secret')).toHaveCount(0)

    await goTo(bob.page, 'Categories')
    await expect.poll(() => categoryNames(bob.page, 'expense')).toContain('Groceries')
    expect(await categoryNames(bob.page, 'expense')).not.toContain('Alice private')
    await bob.page.getByRole('banner').getByRole('button', { name: 'Add transaction' }).click()
    const bobDialog = bob.page.getByRole('dialog', { name: 'New transaction' })
    await expect(bobDialog.getByRole('group', { name: 'Category' }).getByText('Groceries', { exact: true })).toBeVisible()
    await expect(bobDialog.getByText('Alice private')).toHaveCount(0)
    await bobDialog.getByRole('button', { name: 'Cancel' }).click()

    await goTo(bob.page, 'Analytics')
    await bob.page.getByRole('group', { name: 'Period' }).getByRole('button', { name: 'All time' }).click()
    const totals = bob.page.getByRole('region', { name: /^Totals/ })
    await expect(totals).toContainText(kzt('0'))
    await expect(totals).not.toContainText(kzt('777 777'))
    await expect(totals).not.toContainText(kzt('1 000 000'))

    await goTo(bob.page, 'Dashboard')
    await expect(bob.page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('0'))
    await expect(bob.page.getByRole('region', { name: 'Recent transactions' })).toContainText('No transactions yet')

    // Even a request crafted in Bob's browser for Alice's transaction gets nothing.
    const alices = await page.request.get('/api/transactions')
    const secretId = (await alices.json()).items.find((t: { description: string }) => t.description === 'Alice secret').id
    const attempt = await bob.page.request.get(`/api/transactions/${secretId}`)
    expect(attempt.status()).toBe(404)
    expect(await bob.page.request.delete(`/api/transactions/${secretId}`).then((r) => r.status())).toBe(404)
    await page.reload()
    await expect(entry(ledger(page), 'Alice secret')).toBeVisible()
  })

  test('sessions are independent: logging one user out leaves the other signed in', async ({ page, account, openUser }) => {
    await page.goto('/')
    await expect(page.getByRole('banner').getByText(account.email)).toBeVisible()
    const bob = await openUser('bob')
    await bob.page.goto('/')
    await expect(bob.page.getByRole('banner').getByText(bob.account.email)).toBeVisible()

    await logOut(page)

    await bob.page.reload()
    await expect(bob.page.getByRole('banner').getByText(bob.account.email)).toBeVisible()
    await page.goto('/transactions')
    await expect(page).toHaveURL(/\/login$/)

    // Bob's data is his own, whatever Alice's browser does.
    await addTransaction(bob.page, { type: 'income', amount: '1000', category: 'Gifts', description: 'Birthday gift' })
    await expect(bob.page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('1 000'))
  })
})
