/** Authentication: register, stay signed in, log out, log in, errors, protected routes. */
import { expect, newAccount, test } from './support/fixtures'
import { logIn, logOut, register } from './support/app'

test.describe('Authentication', () => {
  test('register, stay signed in after a refresh, log out and log in again', { tag: '@mobile' }, async ({ page }) => {
    const account = newAccount('journey')

    await register(page, account)
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    await expect(page).toHaveURL(/\/$/)

    await page.reload()
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()

    await logOut(page)
    await expect(page.getByRole('heading', { level: 1, name: 'Log in' })).toBeVisible()
    await page.goto('/')
    await expect(page).toHaveURL(/\/login$/) // the session really ended

    await logIn(page, account)
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  })

  test('shows who is signed in', async ({ page, account }) => {
    await page.goto('/')
    await expect(page.getByRole('banner').getByText(account.email)).toBeVisible()
  })

  test('the session cookie is HttpOnly and never visible to page scripts', async ({ page, account }) => {
    await page.goto('/')
    await expect(page.getByRole('banner').getByText(account.email)).toBeVisible()

    expect(await page.evaluate(() => document.cookie)).not.toContain('spendwise_session')
    expect(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length)).toBe(0)
    const cookie = (await page.context().cookies()).find((c) => c.name === 'spendwise_session')
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Lax', path: '/' })
  })

  test('an invalid login shows a useful error and does not sign in', async ({ page, account }) => {
    await page.request.post('/api/auth/logout')
    await page.goto('/login')

    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page.getByText('Enter your email.')).toBeVisible()
    await expect(page.getByText('Enter your password.')).toBeVisible()

    await logIn(page, { email: account.email, password: 'definitely the wrong password' })
    await expect(page.getByRole('alert')).toHaveText('Invalid email or password')
    await expect(page).toHaveURL(/\/login$/)

    await logIn(page, { email: 'nobody-here@example.com', password: account.password })
    await expect(page.getByRole('alert')).toHaveText('Invalid email or password')

    await logIn(page, account)
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  })

  test('registration explains what is wrong', async ({ page, account }) => {
    await page.request.post('/api/auth/logout')
    await page.goto('/register')
    const create = page.getByRole('button', { name: 'Create account' })

    await page.getByLabel('Email').fill(newAccount('x').email)
    await page.getByLabel('Password', { exact: true }).fill('short')
    await create.click()
    await expect(page.getByText('Use at least 12 characters.')).toBeVisible()

    await page.getByLabel('Password', { exact: true }).fill('a long enough password')
    await page.getByLabel('Confirm password').fill('a different password!')
    await create.click()
    await expect(page.getByText('The passwords don’t match.')).toBeVisible()

    // An address that already has an account.
    await page.getByLabel('Email').fill(account.email)
    await page.getByLabel('Confirm password').fill('a long enough password')
    await create.click()
    await expect(page.getByText('An account with this email already exists')).toBeVisible()
    await expect(page).toHaveURL(/\/register$/)
  })

  for (const path of ['/', '/transactions?type=expense', '/categories', '/analytics']) {
    test(`signed-out visitors to ${path} are sent to log in, then brought back`, async ({ page, account }) => {
      await page.request.post('/api/auth/logout')

      await page.goto(path)
      await expect(page).toHaveURL(/\/login$/)
      await expect(page.getByRole('heading', { level: 1, name: 'Log in' })).toBeVisible()

      await logIn(page, account)
      await expect(page).toHaveURL(new RegExp(`${path.replace('?', '\\?')}$`))
    })
  }

  test('signed-in users are sent away from the login and register pages', async ({ page, account }) => {
    expect(account.email).toBeTruthy()
    for (const path of ['/login', '/register']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    }
  })
})
