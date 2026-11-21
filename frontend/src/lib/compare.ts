/**
 * Change against the previous period as a whole percentage, for labels like "↗ 12% vs Oct".
 * Display only: both amounts are backend totals, and nothing is stored or added up. Null when
 * there is nothing meaningful to compare with: a previous total of zero, or a negative amount
 * (a net can change sign, and a percentage of a negative base reads backwards).
 */
export function percentChange(current: number, previous: number): number | null {
  if (previous <= 0 || current < 0) return null
  return Math.round(((current - previous) / previous) * 100)
}
