import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, buildQuery, request, toApiError } from './client'

function mockFetch(status: number, body?: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('toApiError', () => {
  it('uses the string detail of business-rule errors', () => {
    const error = toApiError(409, {
      detail: 'Category is used by 2 transaction(s); reassign or delete them first',
    })
    expect(error.status).toBe(409)
    expect(error.message).toBe('Category is used by 2 transaction(s); reassign or delete them first')
    expect(error.fieldErrors).toEqual({})
  })

  it('maps FastAPI validation errors to fields', () => {
    const error = toApiError(422, {
      detail: [
        { type: 'greater_than', loc: ['body', 'amount_cents'], msg: 'Input should be greater than 0' },
        { type: 'string_too_short', loc: ['body', 'description'], msg: 'String should have at least 1 character' },
        { type: 'int_type', loc: ['body', 'amount_cents'], msg: 'a second amount error' },
      ],
    })
    expect(error.status).toBe(422)
    expect(error.fieldErrors).toEqual({
      amount_cents: 'Input should be greater than 0',
      description: 'String should have at least 1 character',
    })
    expect(error.message).toBe('Some fields are invalid. Please check the form.')
  })

  it('uses body-level validation messages as the general message', () => {
    const error = toApiError(422, {
      detail: [{ type: 'value_error', loc: ['body'], msg: "Value error, 'name' cannot be null" }],
    })
    expect(error.message).toBe("'name' cannot be null")
    expect(error.fieldErrors).toEqual({})
  })

  it.each([
    [401, null, 'Please log in to continue.'],
    [404, null, 'Not found.'],
    [500, 'Internal Server Error', 'The server had a problem. Please try again.'],
    [418, { detail: '' }, 'Request failed (HTTP 418).'],
    [422, { detail: [] }, 'Request failed (HTTP 422).'],
  ])('falls back to a generic message for %d', (status, body, message) => {
    expect(toApiError(status, body).message).toBe(message)
  })
})

describe('buildQuery', () => {
  it('skips empty values', () => {
    expect(buildQuery({ type: 'expense', category_id: undefined, date_from: '', limit: 20 })).toBe(
      '?type=expense&limit=20',
    )
    expect(buildQuery({})).toBe('')
    expect(buildQuery()).toBe('')
  })
})

describe('request', () => {
  it('sends JSON and returns the parsed body', async () => {
    const fetchMock = mockFetch(201, { id: 1 })

    const result = await request<{ id: number }>('/categories', {
      method: 'POST',
      body: { name: 'Pets', type: 'expense' },
    })

    expect(result).toEqual({ id: 1 })
    expect(fetchMock).toHaveBeenCalledWith('/api/categories', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Pets', type: 'expense' }),
    })
  })

  it('returns undefined for 204 No Content', async () => {
    mockFetch(204)
    await expect(api.deleteTransaction(5)).resolves.toBeUndefined()
  })

  it('throws ApiError with the server message on errors', async () => {
    mockFetch(409, { detail: 'A expense category named Food already exists' })

    await expect(api.createCategory({ name: 'Food', type: 'expense' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      message: 'A expense category named Food already exists',
    })
  })

  it('reports network failures with status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    const error = await api.listCategories().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(0)
  })

  it('passes typed query parameters', async () => {
    const fetchMock = mockFetch(200, { items: [], total: 0, limit: 20, offset: 0 })

    await api.listTransactions({ type: 'income', limit: 20, offset: 0 })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/transactions?type=income&limit=20&offset=0')
  })
})

describe('auth', () => {
  const alice = { id: 1, email: 'alice@example.com', created_at: '2026-11-01T00:00:00Z' }

  it('sends the session cookie with every request and never handles a token', async () => {
    const fetchMock = mockFetch(200, [])

    await api.listCategories()

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.credentials).toBe('same-origin')
    expect(init.headers).toBeUndefined() // no Authorization header: the cookie is HttpOnly
  })

  it('returns the current user', async () => {
    const fetchMock = mockFetch(200, alice)

    await expect(api.getCurrentUser()).resolves.toEqual(alice)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/me')
  })

  it('returns null instead of throwing when signed out', async () => {
    mockFetch(401, { detail: 'Not authenticated' })
    await expect(api.getCurrentUser()).resolves.toBeNull()
  })

  it('still throws for other failures while checking the session', async () => {
    mockFetch(500)
    await expect(api.getCurrentUser()).rejects.toMatchObject({ status: 500 })
  })

  it.each([
    ['signup', () => api.signup({ email: 'a@example.com', password: 'p'.repeat(12) }), '/api/auth/signup'],
    ['login', () => api.login({ email: 'a@example.com', password: 'p'.repeat(12) }), '/api/auth/login'],
  ])('%s posts the credentials as JSON', async (_, call, url) => {
    const fetchMock = mockFetch(200, alice)

    await expect(call()).resolves.toEqual(alice)
    const [calledUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(calledUrl).toBe(url)
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ email: 'a@example.com', password: 'p'.repeat(12) })
  })

  it('logs out with a POST', async () => {
    const fetchMock = mockFetch(204)

    await expect(api.logout()).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/logout')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('shows the generic message for a failed login', async () => {
    mockFetch(401, { detail: 'Invalid email or password' })

    await expect(api.login({ email: 'a@example.com', password: 'wrong' })).rejects.toMatchObject({
      status: 401,
      message: 'Invalid email or password',
    })
  })
})
