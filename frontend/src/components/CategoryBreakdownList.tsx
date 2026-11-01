import type { ReactNode } from 'react'

import type { CategoryBreakdown } from '../api/client'
import { formatKzt } from '../lib/money'
import { labelClass } from '../lib/styles'
import { ChartEmpty, LazyCategoryTreemap } from './LazyCharts'

type Item = CategoryBreakdown['items'][number]

/**
 * Part-to-whole as one 100% stacked bar (categories in their own colours, hairline gaps).
 * A donut is avoided on purpose: with more than five categories slices become unreadable.
 * The text summary makes the same information available to screen readers.
 */
export function ProportionBar({ items, className = 'h-2.5' }: { items: Item[]; className?: string }) {
  const summary = items.map((item) => `${item.category_name} ${item.percentage}%`).join(', ')
  return (
    <div className={`flex gap-[2px] overflow-hidden rounded-[2px] bg-surface-sunken ${className}`} role="img" aria-label={`Share by category: ${summary}`}>
      {items.map((item) => (
        <span
          key={item.category_id}
          className="min-w-1"
          style={{ flexGrow: item.total_cents, backgroundColor: item.color }}
          title={`${item.category_name}: ${formatKzt(item.total_cents)} (${item.percentage}%)`}
        />
      ))}
    </div>
  )
}

/**
 * Total, treemap (or a proportion bar in tight spots) and ranked list for one breakdown, or a
 * compact empty state. "wide" puts the treemap and the list side by side.
 */
export function CategorySplit({ breakdown, limit, layout = 'stacked', chart = 'treemap', treemapHeight = 'h-48', emptyAction }: {
  breakdown: CategoryBreakdown
  limit?: number
  layout?: 'stacked' | 'wide'
  chart?: 'treemap' | 'bar'
  treemapHeight?: string
  emptyAction?: ReactNode
}) {
  if (breakdown.items.length === 0) {
    const what = breakdown.type === 'expense' ? 'spending' : 'income'
    return (
      <ChartEmpty
        title={`No ${what} in this period`}
        description={`Categories appear here once ${breakdown.type === 'expense' ? 'expenses are' : 'income is'} recorded.`}
        action={emptyAction}
      />
    )
  }
  const header = (
    <div className="flex items-end justify-between gap-3">
      <div>
        <p className={labelClass}>{breakdown.type === 'expense' ? 'Total spent' : 'Total earned'}</p>
        <p className="mt-1.5 text-figure tabular-nums text-ink">{formatKzt(breakdown.total_cents)}</p>
      </div>
      <p className="text-xs text-ink-subtle tabular-nums">
        {breakdown.items.length} {breakdown.items.length === 1 ? 'category' : 'categories'}
      </p>
    </div>
  )
  const visual = chart === 'treemap' ? <LazyCategoryTreemap breakdown={breakdown} height={treemapHeight} /> : <ProportionBar items={breakdown.items} />
  const list = (
    <>
      <CategoryBreakdownList breakdown={breakdown} limit={limit} />
      {limit !== undefined && breakdown.items.length > limit && (
        <p className="mt-3 text-xs text-ink-subtle">and {breakdown.items.length - limit} more</p>
      )}
    </>
  )
  if (layout === 'wide') {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 lg:items-start">
          {visual}
          <div>{list}</div>
        </div>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-4">
      {header}
      {visual}
      <div>{list}</div>
    </div>
  )
}

/**
 * Ranked rows (sorted by the backend, largest first) with amount, share and a hairline bar in the
 * category's colour. Bar widths are presentation only; amounts and percentages come from the backend.
 */
export function CategoryBreakdownList({ breakdown, limit }: { breakdown: CategoryBreakdown; limit?: number }) {
  const items = limit ? breakdown.items.slice(0, limit) : breakdown.items
  const largest = breakdown.items[0]?.total_cents ?? 0

  return (
    <ul className="grid gap-y-3">
      {items.map((item) => {
        const width = largest > 0 ? Math.max((item.total_cents / largest) * 100, 2) : 0
        return (
          <li key={item.category_id}>
            <div className="flex items-baseline justify-between gap-3 text-label">
              <span className="flex min-w-0 items-center gap-2">
                <span className="size-2 shrink-0 rounded-[2px]" style={{ backgroundColor: item.color }} aria-hidden="true" />
                <span className="truncate text-ink">{item.category_name}</span>
              </span>
              <span className="shrink-0 tabular-nums">
                <span className="font-medium text-ink">{formatKzt(item.total_cents)}</span>
                <span className="ml-2 inline-block w-12 text-right text-xs text-ink-subtle">{item.percentage}%</span>
              </span>
            </div>
            <div className="mt-1.5 h-[3px] w-full bg-surface-sunken" aria-hidden="true">
              <div className="h-[3px]" style={{ width: `${width}%`, backgroundColor: item.color }} />
            </div>
          </li>
        )
      })}
    </ul>
  )
}
