/**
 * Responsive smoke flows. Tagged @mobile, so they run on the desktop project (1440×900) and on
 * the phone project (Pixel 7, 412×915, touch).
 */
import { expect, test } from './support/fixtures'
import { addTransaction, entry, expectNoHorizontalOverflow, goTo, kzt, mainNav } from './support/app'

const PAGES = ['Dashboard', 'Transactions', 'Categories', 'Analytics'] as const

test.describe('Responsive layout', { tag: '@mobile' }, () => {
  test('every page fits the screen and the navigation reaches it', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await expect(mainNav(page)).toBeVisible()

    for (const name of PAGES) {
      await goTo(page, name)
      await expect(mainNav(page).getByRole('link', { name })).toHaveAttribute('aria-current', 'page')
      await expectNoHorizontalOverflow(page)
    }
  })

  test('primary actions stay reachable', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    const banner = page.getByRole('banner')

    for (const button of ['Add transaction', 'Log out']) {
      const control = banner.getByRole('button', { name: button })
      await expect(control).toBeVisible()
      await expect(control).toBeInViewport()
    }
    for (const link of PAGES) await expect(mainNav(page).getByRole('link', { name: link })).toBeInViewport()
  })

  test('the transaction dialog fits and works', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await page.getByRole('banner').getByRole('button', { name: 'Add transaction' }).click()
    const dialog = page.getByRole('dialog', { name: 'New transaction' })
    await expect(dialog).toBeVisible()

    const box = (await dialog.boundingBox())!
    const viewport = page.viewportSize()!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    await expect(dialog.getByRole('button', { name: 'Add expense' })).toBeInViewport()
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()

    await addTransaction(page, { type: 'expense', amount: '4 200', category: 'Restaurants & cafes', description: 'Lunch' })
    await expect(entry(page.getByRole('region', { name: 'Recent transactions' }), 'Lunch')).toContainText(kzt('4 200', '−'))
    await expectNoHorizontalOverflow(page)
  })

  test('the sign-in pages fit the screen', async ({ page }) => {
    for (const path of ['/login', '/register']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expectNoHorizontalOverflow(page)
    }
  })
})
