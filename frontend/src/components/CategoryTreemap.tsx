import { ResponsiveContainer, Tooltip, Treemap } from 'recharts'

import type { CategoryBreakdown } from '../api/client'
import { labelOn, SURFACE } from '../lib/chartColors'
import { formatKzt } from '../lib/money'

type Item = CategoryBreakdown['items'][number]

type TileProps = {
  x?: number
  y?: number
  width?: number
  height?: number
  depth?: number
  category_name?: string
  color?: string
  percentage?: number
}

/** One tile: the category colour, a surface-coloured gap, and a label when the tile is big enough. */
function Tile({ x = 0, y = 0, width = 0, height = 0, depth, category_name, color, percentage }: TileProps) {
  if (depth !== 1) return null
  const showName = width > 72 && height > 38
  const showShare = width > 48 && height > 24
  const label = color ? labelOn(color) : '#ffffff'
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={3} fill={color} stroke={SURFACE} strokeWidth={3} />
      {showName && (
        <text x={x + 10} y={y + 20} fill={label} fontSize={12} fontWeight={600} fontFamily="Inter Variable, Inter, sans-serif">
          {category_name && category_name.length > width / 8 ? `${category_name.slice(0, Math.floor(width / 8) - 1)}…` : category_name}
        </text>
      )}
      {showShare && (
        <text
          x={x + 10}
          y={showName ? y + 36 : y + 17}
          fill={label}
          fillOpacity={0.8}
          fontSize={11}
          fontFamily="Inter Variable, Inter, sans-serif"
        >
          {percentage}%
        </text>
      )}
    </g>
  )
}

function TileTooltip({ active, payload }: { active?: boolean; payload?: { payload: Item }[] }) {
  const item = payload?.[0]?.payload
  if (!active || !item) return null
  return (
    <div className="rounded-[var(--radius-control)] border border-line-strong bg-surface-raised px-3 py-2 text-xs text-ink shadow-pop">
      <p className="flex items-center gap-1.5 font-semibold">
        <span className="size-2 rounded-[2px]" style={{ backgroundColor: item.color }} aria-hidden="true" />
        {item.category_name}
      </p>
      <p className="mt-0.5 text-ink-muted tabular-nums">
        {formatKzt(item.total_cents)} · {item.percentage}%
      </p>
    </div>
  )
}

/**
 * Category share as a treemap: tile area ∝ the backend total, the category's own colour for
 * identity, names and percentages written on the tiles. The ranked list next to it is the precise
 * (and screen-reader) view, so the chart itself is decorative to assistive technology.
 */
export function CategoryTreemap({ breakdown, height = 'h-56' }: { breakdown: CategoryBreakdown; height?: string }) {
  return (
    <div className={`w-full ${height}`} aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <Treemap
          data={breakdown.items}
          dataKey="total_cents"
          nameKey="category_name"
          aspectRatio={1.6}
          content={<Tile />}
          isAnimationActive={false}
        >
          <Tooltip content={<TileTooltip />} />
        </Treemap>
      </ResponsiveContainer>
    </div>
  )
}
