/**
 * Chart series colours for the Graphite (dark) theme: emerald income, coral expenses, blue net.
 * Checked with the palette validator on the #12151c surface, all pairs: lightness band, chroma,
 * CVD ΔE ≥ 9.0, normal-vision ΔE ≥ 23.5, all ≥ 3:1 contrast. Charts still keep legends,
 * tooltips and table views. Text amounts use the lighter --color-income / --color-expense tokens.
 */
export const SERIES = {
  income: '#12a07a',
  expense: '#ec5f53',
  net: '#6a7ff0',
} as const

export const GRID = '#1f2430' // hairline, recessive
export const AXIS = '#323949' // baseline (line-strong token)
export const AXIS_TEXT = '#8892a4' // ink-subtle token, 5.8:1 on the surface
export const CURSOR = 'rgba(255, 255, 255, 0.03)'
export const SURFACE = '#12151c'

/** Label colours for text drawn on a category-coloured tile. */
export const ON_LIGHT = '#0a0c10'
export const ON_DARK = '#ffffff'

/** Pick the label colour with more contrast against a "#rrggbb" fill (WCAG relative luminance). */
export function labelOn(fill: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(fill.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
  // Contrast with black is (L + 0.05) / 0.05, with white 1.05 / (L + 0.05); pick the larger.
  return (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) ? ON_LIGHT : ON_DARK
}
