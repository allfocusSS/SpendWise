import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError, type User } from '../api/client'
import { CURRENT_USER_KEY } from './auth'

/**
 * Start a new session state: record the signed-in user (or null) and drop every other cached
 * answer, so nothing from the previous user stays in memory.
 *
 * The current-user query itself is updated, never removed: the route guards are subscribed to
 * it, and a removed query would leave them watching a query that no longer changes.
 */
export function setSession(client: QueryClient, user: User | null) {
  client.setQueryData(CURRENT_USER_KEY, user)
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== CURRENT_USER_KEY[0] })
}

/** A 401 from any request means the session has ended (logged out elsewhere, expired). */
function onUnauthorized(client: QueryClient, error: unknown) {
  if (error instanceof ApiError && error.status === 401) setSession(client, null)
}

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => onUnauthorized(client, error) }),
    mutationCache: new MutationCache({ onError: (error) => onUnauthorized(client, error) }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Retry once for network/server problems, never for 4xx answers.
        retry: (failureCount, error) =>
          failureCount < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      },
    },
  })
  return client
}
