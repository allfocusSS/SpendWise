/**
 * Helpers that drive SpendWise the way a person does: through visible labels, roles and
 * accessible names, never through CSS classes or the API.
 */
import { expect, type Locator, type Page } from '@playwright/test'

import type { Account } from './fixtures'

export const TIME_ZONE = 'Asia/Almaty' // must match playwright.config.ts

// --- Money and dates ---------------------------------------------------------------------------

const SPACE = '[\\s\\u00a0\\u202f]'

function escape(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * An amount exactly as the app shows it, in any whitespace style ("1 234,50 ₸" uses narrow or
 * no-break spaces). kzt('1 234,50') or kzt('1 234,50', '−') for a signed ledger amount.
 */
export function kzt(amount: string, sign?: '+' | '−'): RegExp {
  const digits = escape(amount).replace(/ /g, SPACE)
  const prefix = sign === '+' ? '\\+' : sign === '−' ? '[−-]' : ''
  return new RegExp(`${prefix}${digits}${SPACE}*₸`)
}

/** YYYY-MM-DD in the app's time zone, `daysAgo` days before today. */
export function isoDate(daysAgo = 0): string {
  const date = new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000)
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(date)
}

/** The first day of the current month, YYYY-MM-DD. */
export function firstOfThisMonth(): string {
  return `${isoDate().slice(0, 8)}01`
}

/** The current month as the charts' tables label it, e.g. "Nov 2026". */
export function thisMonthLabel(): string {
  return new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: TIME_ZONE }).format(new Date())
}

// --- Navigation and layout ---------------------------------------------------------------------

/** The main navigation: top links on desktop, bottom tab bar on phones (whichever is shown). */
export function mainNav(page: Page): Locator {
  return page.getByRole('navigation', { name: 'Main' })
}

export async function goTo(page: Page, link: 'Dashboard' | 'Transactions' | 'Categories' | 'Analytics') {
  await mainNav(page).getByRole('link', { name: link }).click()
  const heading = link === 'Dashboard' ? 'Overview' : link
  await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
}

export async function expectNoHorizontalOverflow(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth, `page is ${scrollWidth}px wide in a ${clientWidth}px viewport`).toBeLessThanOrEqual(clientWidth)
}

// --- Authentication ----------------------------------------------------------------------------

export async function register(page: Page, account: Account) {
  await page.goto('/register')
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByLabel('Confirm password').fill(account.password)
  await page.getByRole('button', { name: 'Create account' }).click()
}

export async function logIn(page: Page, account: Account) {
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password').fill(account.password)
  await page.getByRole('button', { name: 'Log in' }).click()
}

export async function logOut(page: Page) {
  await page.getByRole('banner').getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
}

// --- Transactions ------------------------------------------------------------------------------

export type NewTransaction = {
  type: 'income' | 'expense'
  amount: string // as typed, e.g. "12 345,67"
  category: string
  description: string
  date?: string // YYYY-MM-DD; the form defaults to today
}

/** Fill the transaction form in an open dialog. */
export async function fillTransaction(dialog: Locator, tx: Partial<NewTransaction>) {
  if (tx.type) await dialog.getByText(tx.type === 'income' ? 'Money coming in' : 'Money going out').click()
  if (tx.amount !== undefined) await dialog.getByLabel('Amount').fill(tx.amount)
  if (tx.category) await dialog.getByRole('group', { name: 'Category' }).getByText(tx.category, { exact: true }).click()
  if (tx.date) await dialog.getByLabel('Date').fill(tx.date)
  if (tx.description !== undefined) await dialog.getByLabel('Description').fill(tx.description)
}

/** Add a transaction with the header's "Add transaction" button, as a person would. */
export async function addTransaction(page: Page, tx: NewTransaction) {
  await page.getByRole('banner').getByRole('button', { name: 'Add transaction' }).click()
  const dialog = page.getByRole('dialog', { name: 'New transaction' })
  await expect(dialog).toBeVisible()
  await fillTransaction(dialog, tx)
  await dialog.getByRole('button', { name: tx.type === 'income' ? 'Add income' : 'Add expense' }).click()
  await expect(dialog).toBeHidden()
}

/** The ledger on the Transactions page. */
export function ledger(page: Page): Locator {
  return page.getByRole('region', { name: 'Transaction ledger' })
}

/** The row (table on wide screens, list item on phones) showing a transaction. */
export function entry(scope: Locator, description: string): Locator {
  return scope.locator('tr, li').filter({ hasText: description }).filter({ visible: true })
}

// --- Categories --------------------------------------------------------------------------------

export function categoryList(page: Page, type: 'expense' | 'income'): Locator {
  return page.getByRole('region', { name: type === 'income' ? 'Income categories' : 'Expense categories' })
}

/** Visible category names in one list, in display order. */
export async function categoryNames(page: Page, type: 'expense' | 'income'): Promise<string[]> {
  const rows = categoryList(page, type).locator('tbody tr, ul > li').filter({ visible: true })
  await expect(rows.first()).toBeVisible()
  const names: string[] = []
  for (const row of await rows.all()) {
    const label = await row.getByRole('button', { name: /^Edit / }).getAttribute('aria-label')
    names.push(label!.replace(/^Edit /, ''))
  }
  return names
}
