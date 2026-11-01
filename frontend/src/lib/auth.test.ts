import { describe, expect, it } from 'vitest'

import { safeRedirectPath } from './auth'

describe('safeRedirectPath', () => {
  it('returns to the page the user asked for', () => {
    expect(safeRedirectPath({ pathname: '/transactions' })).toBe('/transactions')
    expect(safeRedirectPath({ pathname: '/analytics', search: '?period=year', hash: '#trend' })).toBe(
      '/analytics?period=year#trend',
    )
  })

  it.each([
    ['nothing', undefined],
    ['null', null],
    ['a string', '/transactions'],
    ['no pathname', { search: '?x=1' }],
    ['a full URL', { pathname: 'https://evil.example/phish' }],
    ['a protocol-relative URL', { pathname: '//evil.example/phish' }],
    ['a backslash trick', { pathname: '/\\evil.example' }],
    ['a relative path', { pathname: 'transactions' }],
    ['non-string parts', { pathname: '/transactions', search: 1 }],
    ['the login page', { pathname: '/login' }],
    ['the register page', { pathname: '/register' }],
  ])('falls back to the dashboard for %s', (_, from) => {
    expect(safeRedirectPath(from)).toBe('/')
  })
})
