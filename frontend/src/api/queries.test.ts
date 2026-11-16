import { describe, expect, it } from 'vitest'

import { trendWindow } from '../lib/dates'
import { createQueryClient } from '../lib/queryClient'
import { queryKeys } from './queries'

describe('analytics query keys', () => {
  it('give each history window its own cache entry', () => {
    const december = queryKeys.trend(trendWindow(new Date(2025, 11, 1), 6))
    const january = queryKeys.trend(trendWindow(new Date(2026, 0, 1), 6))
    expect(december).toEqual(['analytics', 'monthly-trend', { months: 6, until: '2025-12-01' }])
    expect(january).not.toEqual(december)
    // Same window, same entry: the two Analytics charts share one request.
    expect(queryKeys.trend(trendWindow(new Date(2026, 0, 31), 12))).toEqual(queryKeys.trend(trendWindow(new Date(2026, 0, 1), 12)))
  })

  it('all sit under "analytics", which every transaction or category change invalidates', async () => {
    const client = createQueryClient()
    const keys = [
      queryKeys.trend(trendWindow(new Date(2025, 11, 1), 6)),
      queryKeys.trend(trendWindow(new Date(2026, 0, 1), 12)),
      queryKeys.summary({ date_from: '2025-12-01', date_to: '2025-12-31' }),
      queryKeys.breakdown({ type: 'expense', date_from: '2025-12-01', date_to: '2025-12-31' }),
    ]
    for (const key of keys) client.setQueryData(key, {})
    await client.invalidateQueries({ queryKey: ['analytics'] })
    for (const key of keys) expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true)
  })
})
