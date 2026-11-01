import { QueryObserver } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { ApiError, type User } from '../api/client'
import { CURRENT_USER_KEY } from './auth'
import { createQueryClient, setSession } from './queryClient'

const alice: User = { id: 1, email: 'alice@example.com', created_at: '2026-11-01T00:00:00Z' }

function signedInClient() {
  const client = createQueryClient()
  client.setQueryData(CURRENT_USER_KEY, alice)
  client.setQueryData(['transactions', {}], { items: ['private'], total: 1, limit: 50, offset: 0 })
  return client
}

describe('createQueryClient', () => {
  it('signs the user out and drops cached data when a query gets a 401', async () => {
    const client = signedInClient()

    await client
      .fetchQuery({ queryKey: ['analytics', 'summary', {}], queryFn: () => Promise.reject(new ApiError(401, 'x')) })
      .catch(() => {})

    expect(client.getQueryData(CURRENT_USER_KEY)).toBeNull()
    expect(client.getQueryData(['transactions', {}])).toBeUndefined()
  })

  it('does the same when a mutation gets a 401', async () => {
    const client = signedInClient()

    await client
      .getMutationCache()
      .build(client, { mutationFn: () => Promise.reject(new ApiError(401, 'x')) })
      .execute(undefined)
      .catch(() => {})

    expect(client.getQueryData(CURRENT_USER_KEY)).toBeNull()
  })

  it.each([403, 404, 409, 422, 500, 0])('keeps the session for a %d error', async (status) => {
    const client = signedInClient()

    await client
      .fetchQuery({ queryKey: ['categories'], queryFn: () => Promise.reject(new ApiError(status, 'x')), retry: false })
      .catch(() => {})

    expect(client.getQueryData(CURRENT_USER_KEY)).toEqual(alice)
    expect(client.getQueryData(['transactions', {}])).toBeDefined()
  })
})

describe('setSession', () => {
  it('updates the current-user query in place, so the route guards see the change', () => {
    const client = createQueryClient()
    client.setQueryData(CURRENT_USER_KEY, null)
    const seen: unknown[] = []
    const guard = new QueryObserver(client, { queryKey: CURRENT_USER_KEY, enabled: false })
    const unsubscribe = guard.subscribe((result) => seen.push(result.data))

    setSession(client, alice) // log in
    setSession(client, null) // log out

    expect(seen).toEqual([alice, null])
    unsubscribe()
  })

  it("drops the previous user's cached data", () => {
    const client = signedInClient()

    setSession(client, { ...alice, id: 2, email: 'bob@example.com' })

    expect(client.getQueryData(['transactions', {}])).toBeUndefined()
    expect(client.getQueryData(CURRENT_USER_KEY)).toMatchObject({ email: 'bob@example.com' })
  })
})
