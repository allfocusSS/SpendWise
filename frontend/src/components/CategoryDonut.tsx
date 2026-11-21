import type { ReactNode } from 'react'

import type { CategoryBreakdown } from '../api/client'
import { REST, SERIES } from '../lib/chartColors'

type Item = CategoryBreakdown['items'][number]

// Geometry in CSS pixels at the default 150px size (the SVG scales with its box).
const SIZE = 150
const WIDTH = 16
const RADIUS = (SIZE - WIDTH) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const GAP = 2.5

/**
 * Ring of spending by category, largest first from 12 o'clock, with the total in the middle. Arc
 * lengths are presentation only (each category's backend amount over the backend total).
 * Categories past `named` are drawn in a neutral grey: the list beside the ring names the largest
 * ones. Hidden from screen readers: the list carries the figures.
 */
export function CategoryDonut({ items, total, named = items.length, active = null, onActive, size = 'size-[150px]', children }: {
  items: Item[]
  total: number
  /** How many categories (largest first) keep their own colour. */
  named?: number
  /** The category being pointed at (by index), or null. */
  active?: number | null
  onActive?: (index: number | null) => void
  /** Tailwind size of the ring. */
  size?: string
  /** The centre: the total. */
  children: ReactNode
}) {
  const arcs: { id: number; index: number; color: string; start: number; length: number }[] = []
  let start = 0
  for (const [index, item] of items.entries()) {
    const length = total > 0 ? (item.total_cents / total) * CIRCUMFERENCE : 0
    arcs.push({ id: item.category_id, index, color: index < named ? item.color : REST, start, length })
    start += length
  }
  const gap = arcs.length > 1 ? GAP : 0
  return (
    <div className={`relative shrink-0 ${size}`}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="size-full -rotate-90" aria-hidden="true">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" strokeWidth={WIDTH} className="stroke-white/5" />
        {arcs.map((arc) => (
          <circle
            key={arc.id}
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={arc.color}
            strokeWidth={WIDTH}
            strokeDasharray={`${Math.max(arc.length - gap, 0.5)} ${CIRCUMFERENCE}`}
            strokeDashoffset={-arc.start}
            opacity={active === null || active === arc.index ? 1 : 0.3}
            className="transition-opacity motion-reduce:transition-none"
            onMouseEnter={onActive ? () => onActive(arc.index) : undefined}
            onMouseLeave={onActive ? () => onActive(null) : undefined}
          />
        ))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  )
}

/**
 * One category's share as a progress ring in one violet for every category (magnitude; the name
 * under the ring says which). Hidden from screen readers: the percentage and name are text.
 */
export function ShareRing({ percentage, children, size = 'size-[92px]' }: {
  /** The backend's percentage of the total (0–100). */
  percentage: number
  children: ReactNode
  size?: string
}) {
  const ring = 92
  const width = 9
  const r = (ring - width) / 2
  const c = 2 * Math.PI * r
  return (
    <div className={`relative shrink-0 ${size}`}>
      <svg viewBox={`0 0 ${ring} ${ring}`} className="size-full -rotate-90" aria-hidden="true">
        <circle cx={ring / 2} cy={ring / 2} r={r} fill="none" strokeWidth={width} className="stroke-white/[0.07]" />
        <circle
          cx={ring / 2}
          cy={ring / 2}
          r={r}
          fill="none"
          stroke={SERIES.income}
          strokeWidth={width}
          strokeLinecap="round"
          strokeDasharray={`${Math.max((Math.min(percentage, 100) / 100) * c, 2)} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">{children}</div>
    </div>
  )
}
