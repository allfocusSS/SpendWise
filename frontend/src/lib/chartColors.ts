/**
 * Chart series colours (categorical slots 1–2 of the validated reference palette).
 * Checked with the palette validator on the light surface: CVD ΔE 24.7, normal-vision ΔE 33.6,
 * both ≥ 3:1 contrast. Income/expense always use these, so a series keeps its colour everywhere.
 */
export const SERIES = {
  income: '#2a78d6',
  expense: '#eb6834',
} as const

export const GRID = '#e2e8f0' // slate-200: hairline, recessive
export const AXIS_TEXT = '#64748b' // slate-500
