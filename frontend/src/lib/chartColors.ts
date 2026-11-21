/**
 * Chart colours for the Plum theme: violet income and pink-magenta expenses (the reference's
 * violet/magenta, with the expense hue moved towards pink so the pair stays distinct for colour
 * blindness: palette validator CVD ΔE 17.6, normal vision 22.5, both ≥ 4.5:1 on the #1e1938 card).
 * Charts keep legends, tooltips and table views; amounts in text use the emerald and rose tokens.
 * The neutrals below mirror index.css.
 */
export const SERIES = {
  income: '#8a72ff',
  expense: '#e04f8c',
  net: '#c4b5fd',
} as const

export const GRID = 'rgba(196, 189, 220, 0.14)' // dashed, recessive
export const AXIS = '#3d3566' // baseline (line-strong token)
export const AXIS_TEXT = '#a39bc4' // ink-subtle token, 6.4:1 on the card
export const CURSOR = 'rgba(185, 165, 255, 0.06)'
export const SURFACE = '#1e1938'
export const INK = '#f5f3fb' // ink token, for an emphasised axis label
export const HIGHLIGHT = 'rgba(185, 165, 255, 0.08)' // band behind the month or period the page is showing
export const REST = '#6b6390' // categories a chart doesn't name (≥ 3:1 on the card)
