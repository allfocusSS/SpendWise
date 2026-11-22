/** Dashboard: empty state, totals after adding transactions, recent transactions, refresh. */
import type { Page } from '@playwright/test'

import { expect, test } from './support/fixtures'
import { addTransaction, entry, fillTransaction, kzt } from './support/app'

/** Back to the current month with the navigator's "This month" button. */
async function backToThisMonth(page: Page) {
  await page.getByRole('button', { name: 'This month' }).click()
  await expect(page.getByRole('button', { name: 'This month' })).toHaveCount(0)
}

test.describe('Dashboard', () => {
  test('a new account is welcomed with first steps instead of empty figures', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')

    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('0'))
    await expect(page.getByRole('heading', { level: 2, name: 'Welcome to SpendWise' })).toBeVisible()
    await expect(page.getByRole('region', { name: /^Money in, / })).toHaveCount(0) // no tiles of zeros
    await expect(page.getByRole('region', { name: 'Cash flow' })).toContainText('No cash flow yet')
    await expect(page.getByRole('region', { name: 'Spending by category' })).toContainText('No spending in this period')
    await expect(page.getByRole('region', { name: 'Recent transactions' })).toContainText('No transactions yet')

    // The first step opens the form ready for income.
    await page.getByRole('main').getByRole('button', { name: 'Add income' }).click()
    const dialog = page.getByRole('dialog', { name: 'New transaction' })
    await expect(dialog.getByRole('radio', { name: /Income/ })).toBeChecked()
    await fillTransaction(dialog, { amount: '200000', category: 'Salary', description: 'First pay' })
    await dialog.getByRole('button', { name: 'Add income' }).click()
    await expect(dialog).toBeHidden()

    // With a transaction, the month's figures take the steps' place.
    await expect(page.getByRole('heading', { name: 'Welcome to SpendWise' })).toHaveCount(0)
    await expect(page.getByRole('region', { name: /^Money in, / })).toContainText(kzt('200 000'))
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('200 000'))
  })

  test('the month compares with the one before, and the cash-flow totals cover the chart\'s months', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: new Date('2026-06-15T12:00:00+05:00') })
    await page.goto('/')
    await addTransaction(page, { type: 'income', amount: '999 000', category: 'Gifts', description: 'Old gift', date: '2025-12-10' })
    await addTransaction(page, { type: 'income', amount: '100 000', category: 'Salary', description: 'May pay', date: '2026-05-05' })
    await addTransaction(page, { type: 'expense', amount: '80 000', category: 'Groceries', description: 'May food', date: '2026-05-10' })
    await addTransaction(page, { type: 'income', amount: '150 000', category: 'Salary', description: 'June pay', date: '2026-06-05' })
    await addTransaction(page, { type: 'expense', amount: '40 000', category: 'Groceries', description: 'June food', date: '2026-06-10' })

    // June against May: the change and May's figure, with the direction in words, not only colour.
    const moneyIn = page.getByRole('region', { name: 'Money in, June 2026' })
    await expect(moneyIn).toContainText(kzt('150 000'))
    await expect(moneyIn).toContainText(/Up\s*50%/)
    await expect(moneyIn).toContainText(new RegExp(`vs May\\s*·\\s*${kzt('100 000').source}`))
    const moneyOut = page.getByRole('region', { name: 'Money out, June 2026' })
    await expect(moneyOut).toContainText(/Down\s*50%/)
    await expect(moneyOut).toContainText(new RegExp(`vs May\\s*·\\s*${kzt('80 000').source}`))
    // The month's net, and how much of what came in went out (both amounts the server's).
    const net = page.getByRole('region', { name: 'Net savings, June 2026' })
    await expect(net).toContainText(kzt('110 000', '+'))
    await expect(net).toContainText(new RegExp(`${kzt('40 000').source}\\s*out`))
    await expect(net).toContainText(new RegExp(`of\\s*${kzt('150 000').source}\\s*in`))
    await expect(net).toContainText('2 transactions')
    // The balance card says the shown month's net with its sign.
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(new RegExp(`${kzt('110 000', '+').source}\\s*this month`))

    // The totals are the server's for January–June, the chart's window: December's gift is outside it.
    const totals = page.getByRole('region', { name: 'Cash flow' }).getByRole('definition')
    await expect(totals).toHaveText([kzt('250 000'), kzt('120 000'), kzt('130 000', '+')])
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('1 129 000')) // all time does include it
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
      await expect(savings).toContainText(kzt('387 654,33', '+')) // the sign says it, not only the colour
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

  test('a month that spent more than it earned shows a minus sign, not just a colour', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await addTransaction(page, { type: 'income', amount: '100000', category: 'Salary', description: 'Small salary' })
    await addTransaction(page, { type: 'expense', amount: '150000', category: 'Housing & utilities', description: 'Rent' })

    await expect(page.getByRole('region', { name: /^Net savings, / })).toContainText(kzt('50 000', '−'))
    await expect(page.getByRole('region', { name: 'Total balance' })).toContainText(kzt('50 000', '−'))
  })

  test('"This month" returns from a past month in one step, also by keyboard', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.clock.install({ time: new Date('2026-06-15T12:00:00+05:00') })
    await page.goto('/')
    const month = page.getByRole('group', { name: 'Month' })
    const thisMonth = page.getByRole('button', { name: 'This month' })
    await expect(month).toContainText('June 2026')
    await expect(thisMonth).toHaveCount(0) // only offered away from the current month

    await month.getByRole('button', { name: 'Previous month' }).click()
    await month.getByRole('button', { name: 'Previous month' }).click()
    await expect(month).toContainText('April 2026')
    await expect(page.getByRole('region', { name: 'Cash flow' })).toContainText('6 months to Apr 2026')

    await thisMonth.focus()
    await page.keyboard.press('Enter')
    await expect(month).toContainText('June 2026')
    await expect(page.getByRole('region', { name: 'Cash flow' })).toContainText('6 months to Jun 2026')
    await expect(thisMonth).toHaveCount(0)
    await expect(month.getByRole('button', { name: 'Next month' })).toBeDisabled()
  })

  test('nothing focusable hides from screen readers, and the chart is not an empty tab stop', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await addTransaction(page, { type: 'income', amount: '200000', category: 'Salary', description: 'Pay' })
    await expect(page.getByRole('region', { name: 'Cash flow' }).getByText('Show as table')).toBeVisible()

    const hiddenFocusable = await page.evaluate(() =>
      Array.from(document.querySelectorAll('main [aria-hidden="true"]')).flatMap((hidden) =>
        Array.from(hidden.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex]'))
          .filter((el) => (el as HTMLElement).tabIndex >= 0)
          .map((el) => el.outerHTML.slice(0, 80)),
      ),
    )
    expect(hiddenFocusable).toEqual([])

    // From the month controls the next stop is the chart's table toggle (the chart itself is skipped).
    await page.getByRole('button', { name: 'Previous month' }).focus()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('region', { name: 'Cash flow' }).getByText('Show as table')).toBeFocused()
  })

  test('touch targets are at least 44px on a phone', { tag: '@mobile' }, async ({ page, account, isMobile }) => {
    test.skip(!isMobile, 'touch-screen target sizes; with a mouse the controls are 40px by design')
    expect(account.email).toBeTruthy()
    await page.goto('/')
    await addTransaction(page, { type: 'expense', amount: '4 200', category: 'Restaurants & cafes', description: 'Lunch' })
    await page.getByRole('button', { name: 'Previous month' }).click() // so "This month" is offered too

    const main = page.getByRole('main')
    const boxes = [
      main.getByRole('button', { name: 'Previous month' }),
      main.getByRole('button', { name: 'Next month' }),
      main.getByRole('button', { name: 'This month' }),
      main.getByRole('link', { name: /Analytics/ }),
      main.getByRole('link', { name: /All transactions/ }),
    ]
    for (const control of boxes) {
      const box = (await control.boundingBox())!
      expect(Math.min(box.width, box.height), await control.textContent() ?? '').toBeGreaterThanOrEqual(44)
    }

    // The edit button looks smaller but answers taps across a 44px square around its centre.
    await backToThisMonth(page)
    const edit = main.getByRole('button', { name: 'Edit Lunch' })
    await edit.scrollIntoViewIfNeeded()
    const reach = await edit.evaluate((button) => {
      const r = button.getBoundingClientRect()
      const [cx, cy] = [r.left + r.width / 2, r.top + r.height / 2]
      const hits = (x: number, y: number) => {
        const hit = document.elementFromPoint(x, y)
        return hit === button || button.contains(hit)
      }
      return [hits(cx - 21, cy), hits(cx + 21, cy), hits(cx, cy - 21), hits(cx, cy + 21)]
    })
    expect(reach).toEqual([true, true, true, true])
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
