import { useState, type ReactNode } from 'react'

import type { CategoryBreakdown } from '../api/client'
import { formatKzt } from '../lib/money'
import { CategoryDonut } from './CategoryDonut'
import { CategoryIcon } from './CategoryIcon'
import { PieIcon, WalletIcon } from './icons'
import { ChartEmpty } from './LazyCharts'

type Item = CategoryBreakdown['items'][number]

/** A rounded track with a fill; widths are presentation only (an amount over the largest amount). */
function Bar({ value, largest, color, className }: { value: number; largest: number; color: string; className: string }) {
  const width = largest > 0 ? Math.max((value / largest) * 100, 2) : 0
  return (
    <div className={`h-1.5 overflow-hidden rounded-full bg-surface-selected ${className}`} aria-hidden="true">
      <span className="block h-full rounded-full" style={{ width: `${width}%`, backgroundColor: color }} />
    </div>
  )
}

/** Amount and the backend's share, right-aligned so the columns line up row to row. */
function AmountAndShare({ item }: { item: Item }) {
  return (
    <>
      <span className="ml-auto shrink-0 font-semibold text-ink tabular-nums">{formatKzt(item.total_cents)}</span>
      <span className="w-[52px] shrink-0 text-right text-ink-subtle tabular-nums">{item.percentage}%</span>
    </>
  )
}

/**
 * Ranked rows (sorted by the backend, largest first): name, amount and share. Spending rows wear
 * the category's colour (it links them to the donut); income rows share one colour, so their bars
 * compare amounts and the icon and name carry identity.
 */
export function CategoryBreakdownList({ breakdown, active = null, onActive }: {
  breakdown: CategoryBreakdown
  /** The category being pointed at in the donut (by index), or null. */
  active?: number | null
  onActive?: (index: number | null) => void
}) {
  const largest = breakdown.items[0]?.total_cents ?? 0
  if (breakdown.type === 'income') {
    return (
      <ul className="flex flex-col gap-3.5">
        {breakdown.items.map((item) => (
          <li key={item.category_id} className="py-1">
            <p className="flex items-center gap-[9px] text-label text-ink-muted">
              <CategoryIcon name={item.category_name} color={item.color} size="sm" />
              <span className="min-w-0 truncate">{item.category_name}</span>
              <AmountAndShare item={item} />
            </p>
            <Bar value={item.total_cents} largest={largest} color="var(--color-income-chart)" className="mt-2 mr-[61px] ml-[41px]" />
          </li>
        ))}
      </ul>
    )
  }
  return (
    <ul className="flex flex-col gap-[11px]">
      {breakdown.items.map((item, i) => (
        <li
          key={item.category_id}
          onMouseEnter={onActive ? () => onActive(i) : undefined}
          onMouseLeave={onActive ? () => onActive(null) : undefined}
          className={`transition-opacity motion-reduce:transition-none ${active === null || active === i ? '' : 'opacity-45'}`}
        >
          <p className="flex items-center gap-[9px] text-label text-ink-muted">
            <span className="size-[9px] shrink-0 rounded-full" style={{ backgroundColor: item.color }} aria-hidden="true" />
            <span className="min-w-0 truncate">{item.category_name}</span>
            <AmountAndShare item={item} />
          </p>
          <Bar value={item.total_cents} largest={largest} color={item.color} className="mt-1.5 mr-[61px] ml-[18px]" />
        </li>
      ))}
    </ul>
  )
}

/** The donut's centre: the total and what it is. */
export function DonutTotal({ cents, label }: { cents: number; label: string }) {
  return (
    <>
      <span className="text-lg leading-tight font-semibold tracking-[-0.02em] text-ink tabular-nums">{formatKzt(cents)}</span>
      <span className="text-xs text-ink-subtle">{label}</span>
    </>
  )
}

/** Spending: the donut beside the ranked list (stacked in a narrow card). */
function SpendingSplit({ breakdown }: { breakdown: CategoryBreakdown }) {
  const [active, setActive] = useState<number | null>(null)
  return (
    <div className="flex flex-wrap items-center gap-[26px]">
      <CategoryDonut items={breakdown.items} total={breakdown.total_cents} active={active} onActive={setActive} size="size-[170px] max-lg:mx-auto">
        <DonutTotal cents={breakdown.total_cents} label="spent" />
      </CategoryDonut>
      <div className="min-w-[220px] flex-1">
        <CategoryBreakdownList breakdown={breakdown} active={active} onActive={setActive} />
      </div>
    </div>
  )
}

/** One breakdown for a period: spending as a donut and ranked list, income as ranked bars, or an empty state. */
export function CategorySplit({ breakdown, emptyAction }: { breakdown: CategoryBreakdown; emptyAction?: ReactNode }) {
  if (breakdown.items.length === 0) {
    const spending = breakdown.type === 'expense'
    return (
      <ChartEmpty
        icon={spending ? <PieIcon className="size-5" /> : <WalletIcon className="size-5" />}
        title={`No ${spending ? 'spending' : 'income'} in this period`}
        description={spending ? 'Pick another period or add an expense.' : 'Pick another period or add income.'}
        action={emptyAction}
        height="h-44"
      />
    )
  }
  if (breakdown.type === 'expense') return <SpendingSplit breakdown={breakdown} />
  return <CategoryBreakdownList breakdown={breakdown} />
}
