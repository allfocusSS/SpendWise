/** Categories: defaults, create, rename, use in a transaction, deletion rules, persistence. */
import type { Page } from '@playwright/test'

import { expect, test } from './support/fixtures'
import { addTransaction, categoryList, categoryNames, kzt } from './support/app'

const EXPENSE_DEFAULTS = [
  'Education',
  'Entertainment',
  'Groceries',
  'Health',
  'Housing & utilities',
  'Other expenses',
  'Restaurants & cafes',
  'Shopping',
  'Transport',
]
const INCOME_DEFAULTS = ['Freelance', 'Gifts', 'Other income', 'Salary']

// The lists sort by activity first, so compare membership, not position.
async function sortedNames(page: Page, type: 'expense' | 'income') {
  return (await categoryNames(page, type)).sort()
}

test.describe('Categories', () => {
  test.beforeEach(async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/categories')
    await expect(page.getByRole('heading', { level: 1, name: 'Categories' })).toBeVisible()
  })

  test('a new account has the default categories', async ({ page }) => {
    await expect.poll(() => sortedNames(page, 'expense')).toEqual(EXPENSE_DEFAULTS)
    await expect.poll(() => sortedNames(page, 'income')).toEqual(INCOME_DEFAULTS)
  })

  test('create, rename, use, and the rules for deleting a category', async ({ page }) => {
    // Create.
    await page.getByRole('button', { name: 'Add category' }).first().click()
    let dialog = page.getByRole('dialog', { name: 'New category' })
    await dialog.getByLabel('Name').fill('Pets')
    await dialog.getByLabel('Type').selectOption('Expense')
    await dialog.getByRole('button', { name: 'Add category' }).click()
    await expect(dialog).toBeHidden()
    await expect.poll(() => categoryNames(page, 'expense')).toContain('Pets')

    // A duplicate name (ignoring case) is refused with a clear message.
    await page.getByRole('button', { name: 'Add category' }).first().click()
    dialog = page.getByRole('dialog', { name: 'New category' })
    await dialog.getByLabel('Name').fill('pets')
    await dialog.getByRole('button', { name: 'Add category' }).click()
    await expect(dialog).toContainText("A expense category named 'pets' already exists")
    await dialog.getByRole('button', { name: 'Cancel' }).click()

    // Rename.
    await categoryList(page, 'expense').getByRole('button', { name: 'Edit Pets' }).click()
    dialog = page.getByRole('dialog', { name: 'Edit category' })
    await dialog.getByLabel('Name').fill('Pet care')
    await dialog.getByRole('button', { name: 'Save changes' }).click()
    await expect(dialog).toBeHidden()
    await expect.poll(() => categoryNames(page, 'expense')).toContain('Pet care')
    await expect.poll(() => categoryNames(page, 'expense')).not.toContain('Pets')

    // Use it for a transaction; the category shows its activity.
    await addTransaction(page, { type: 'expense', amount: '15000', category: 'Pet care', description: 'Vet visit' })
    const petCare = categoryList(page, 'expense').locator('tr, li').filter({ hasText: 'Pet care' }).filter({ visible: true })
    await expect(petCare).toContainText(kzt('15 000'))

    // A category in use cannot be deleted; the reason is shown and nothing changes.
    await categoryList(page, 'expense').getByRole('button', { name: 'Delete Pet care' }).click()
    const confirm = page.getByRole('dialog', { name: 'Delete category?' })
    await confirm.getByRole('button', { name: 'Delete' }).click()
    await expect(confirm.getByRole('alert')).toHaveText(
      'Category is used by 1 transaction(s); reassign or delete them first',
    )
    await confirm.getByRole('button', { name: 'Cancel' }).click()
    await expect.poll(() => categoryNames(page, 'expense')).toContain('Pet care')

    // An unused category (even a default one) can be deleted.
    await categoryList(page, 'income').getByRole('button', { name: 'Delete Gifts' }).click()
    await confirm.getByRole('button', { name: 'Delete' }).click()
    await expect(confirm).toBeHidden()
    await expect.poll(() => categoryNames(page, 'income')).not.toContain('Gifts')

    // Everything above is stored, not just shown.
    await page.reload()
    await expect.poll(() => categoryNames(page, 'expense')).toContain('Pet care')
    await expect.poll(() => sortedNames(page, 'income')).toEqual(['Freelance', 'Other income', 'Salary'])
  })

  test('search filters the lists', async ({ page }) => {
    await page.getByRole('searchbox', { name: 'Search categories' }).fill('sal')

    await expect.poll(() => categoryNames(page, 'income')).toEqual(['Salary'])
    await expect(categoryList(page, 'expense')).toContainText('No categories match your search')
  })
})
