import { describe, expect, it } from 'vitest'

import { percentChange } from './compare'

describe('percentChange', () => {
  it('rounds the change to a whole percentage', () => {
    expect(percentChange(65_000_000, 58_000_000)).toBe(12) // +12.07%
    expect(percentChange(40_080_000, 106_050_000)).toBe(-62) // −62.21%
    expect(percentChange(150, 100)).toBe(50)
  })

  it('is zero when nothing changed, and −100 when the amount fell to zero', () => {
    expect(percentChange(5_000, 5_000)).toBe(0)
    expect(percentChange(0, 5_000)).toBe(-100)
  })

  it('has no answer without a previous amount to compare with', () => {
    expect(percentChange(5_000, 0)).toBeNull()
    expect(percentChange(0, 0)).toBeNull()
  })

  it('has no answer for negative amounts (a net that changed sign)', () => {
    expect(percentChange(5_000, -2_000)).toBeNull()
    expect(percentChange(-5_000, 2_000)).toBeNull()
  })
})
