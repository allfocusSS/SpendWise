/**
 * Shared fixtures.
 *
 * - Diagnostics (automatic): every page's console messages, uncaught errors and HTTP errors are
 *   recorded and attached to failed tests as browser-log.txt. A test also fails if the page threw
 *   an uncaught error or the server answered 5xx, even when its own assertions passed.
 * - `account`: a new user signed up through the real POST /api/auth/signup, in this page's
 *   browser context (so the page is signed in with the real HttpOnly cookie).
 * - `openUser`: another signed-in user in a separate browser context (another browser), for
 *   isolation tests.
 */
import { randomUUID } from 'node:crypto'
import { writeFileSync } from 'node:fs'

import { test as base, expect, type Browser, type Page, type TestInfo } from '@playwright/test'

export { expect }

export type Account = { email: string; password: string }

/** Fresh credentials: unique per call, so tests never share users. */
export function newAccount(label: string): Account {
  const id = randomUUID().slice(0, 8)
  return { email: `e2e-${label}-${id}@example.com`, password: `e2e-pass-${randomUUID()}` }
}

type Watch = { log: string[]; problems: string[] }

function watch(page: Page, name: string, into: Watch) {
  page.on('console', (m) => into.log.push(`[${name}] console.${m.type()}: ${m.text()}`))
  page.on('pageerror', (e) => {
    into.log.push(`[${name}] pageerror: ${e.message}`)
    into.problems.push(`[${name}] uncaught error in the page: ${e.message}`)
  })
  page.on('requestfailed', (r) => into.log.push(`[${name}] request failed: ${r.method()} ${r.url()} (${r.failure()?.errorText})`))
  page.on('response', (r) => {
    if (r.status() < 400) return
    const line = `${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`
    into.log.push(`[${name}] http ${line}`)
    if (r.status() >= 500) into.problems.push(`[${name}] server error: ${line}`)
  })
}

async function signUp(page: Page, account: Account) {
  const response = await page.request.post('/api/auth/signup', { data: account })
  expect(response.status(), await response.text()).toBe(201)
}

async function report(testInfo: TestInfo, watched: Watch) {
  if (testInfo.status !== testInfo.expectedStatus || watched.problems.length > 0) {
    // A file next to the screenshot and trace (so CI can upload test-results/ as it is), also
    // linked from the HTML report.
    const file = testInfo.outputPath('browser-log.txt')
    writeFileSync(file, watched.log.join('\n') || '(no console output or HTTP errors)')
    await testInfo.attach('browser-log.txt', { path: file, contentType: 'text/plain' })
  }
  expect(watched.problems, 'the page must not throw or get 5xx responses').toEqual([])
}

type OpenUser = (label: string) => Promise<{ page: Page; account: Account }>

// Fixture callbacks name their second argument `provide` (Playwright's docs call it `use`) so
// the React hooks lint rule does not mistake it for React's use().
export const test = base.extend<{ diagnostics: Watch; account: Account; openUser: OpenUser }>({
  diagnostics: [
    async ({ page }, provide, testInfo) => {
      const watched: Watch = { log: [], problems: [] }
      watch(page, 'user', watched)
      await provide(watched)
      await report(testInfo, watched)
    },
    { auto: true },
  ],

  account: async ({ page }, provide) => {
    const account = newAccount('user')
    await signUp(page, account)
    await provide(account)
  },

  openUser: async ({ browser, diagnostics }, provide) => {
    const contexts: Awaited<ReturnType<Browser['newContext']>>[] = []
    await provide(async (label) => {
      const context = await browser.newContext()
      contexts.push(context)
      const page = await context.newPage()
      watch(page, label, diagnostics)
      const account = newAccount(label)
      await signUp(page, account)
      return { page, account }
    })
    await Promise.all(contexts.map((context) => context.close()))
  },
})
