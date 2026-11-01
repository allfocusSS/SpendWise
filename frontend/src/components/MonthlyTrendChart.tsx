import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { MonthlyTrend } from '../api/client'
import { AXIS, AXIS_TEXT, CURSOR, GRID, SERIES, SURFACE } from '../lib/chartColors'
import { formatMonth } from '../lib/dates'
import { formatKzt, formatKztCompact } from '../lib/money'

type Row = MonthlyTrend['months'][number]

const CHART_FONT = "'Inter Variable', Inter, ui-sans-serif, system-ui, sans-serif"

const axisProps = {
  tick: { fill: AXIS_TEXT, fontSize: 11, fontFamily: CHART_FONT },
  tickLine: false,
} as const

function CashFlowTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  const lines = [
    { label: 'Income', color: SERIES.income, value: row.income_cents },
    { label: 'Expenses', color: SERIES.expense, value: row.expense_cents },
  ]
  return (
    <div className="min-w-48 rounded-[var(--radius-control)] border border-line-strong bg-surface-raised px-3.5 py-3 text-xs text-ink shadow-pop">
      <p className="mb-2 font-medium text-ink-muted">{formatMonth(row.month)}</p>
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 tabular-nums">
        {lines.map((line) => (
          <div key={line.label} className="contents">
            <dt className="flex items-center gap-2 text-ink-muted">
              <span className="size-2 rounded-[2px]" style={{ backgroundColor: line.color }} aria-hidden="true" />
              {line.label}
            </dt>
            <dd className="text-right">{formatKzt(line.value)}</dd>
          </div>
        ))}
        <dt className="mt-1 flex items-center gap-2 border-t border-line pt-2 text-ink-muted">
          <span className="h-0.5 w-2.5" style={{ backgroundColor: SERIES.net }} aria-hidden="true" />
          Net
        </dt>
        <dd className="mt-1 border-t border-line pt-2 text-right font-semibold">{formatKzt(row.net_cents)}</dd>
      </dl>
    </div>
  )
}

function LatestNetLabel({ x, y, index, value, lastIndex }: {
  x?: number | string
  y?: number | string
  index?: number
  value?: number | string
  lastIndex: number
}) {
  if (index !== lastIndex || typeof value !== 'number') return null
  const text = `Net ${formatKztCompact(value)}`
  const width = text.length * 6.4 + 10
  const px = Number(x) - width - 8
  const py = Number(y) - 10
  // A surface-coloured backing keeps the label readable where it crosses a bar.
  return (
    <g>
      <rect x={px} y={py} width={width} height={20} rx={3} fill={SURFACE} fillOpacity={0.9} />
      <text x={px + width / 2} y={py + 14} textAnchor="middle" fill={SERIES.net} fontSize={11} fontWeight={600} fontFamily={CHART_FONT}>
        {text}
      </text>
    </g>
  )
}

function TrendTable({ rows }: { rows: Row[] }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-xs text-ink-subtle hover:text-ink">Show as table</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left">
          <caption className="sr-only">Monthly income, expenses and net</caption>
          <thead className="text-xs text-ink-subtle">
            <tr>
              <th scope="col" className="py-1.5 pr-4 font-medium">Month</th>
              <th scope="col" className="py-1.5 pr-4 text-right font-medium">Income</th>
              <th scope="col" className="py-1.5 pr-4 text-right font-medium">Expenses</th>
              <th scope="col" className="py-1.5 text-right font-medium">Net</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line text-xs text-ink tabular-nums">
            {rows.map((row) => (
              <tr key={row.month}>
                <th scope="row" className="py-1.5 pr-4 font-normal">{formatMonth(row.month)}</th>
                <td className="py-1.5 pr-4 text-right">{formatKzt(row.income_cents)}</td>
                <td className="py-1.5 pr-4 text-right">{formatKzt(row.expense_cents)}</td>
                <td className="py-1.5 text-right font-semibold">{formatKzt(row.net_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

/**
 * Combo chart: income and expense columns per month with the backend's net as a line, all on ONE
 * axis (same unit, ₸). Values come straight from the backend. Includes a table view.
 */
export function CashFlowChart({ trend, height = 'h-72', showNet = true }: {
  trend: MonthlyTrend
  height?: string
  showNet?: boolean
}) {
  const rows = trend.months
  return (
    <div>
      <p className="sr-only">
        Income and expenses per month from {formatMonth(rows[0].month)} to {formatMonth(rows[rows.length - 1].month)}. Exact
        values are in the table below the chart.
      </p>
      <div className={`w-full ${height}`} aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} barGap={4} barCategoryGap="28%" margin={{ top: 16, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="month" tickFormatter={(m: string) => formatMonth(m, true)} axisLine={{ stroke: AXIS }} dy={8} {...axisProps} />
            <YAxis tickFormatter={(v: number) => formatKztCompact(Math.round(v))} axisLine={false} width={64} {...axisProps} />
            <ReferenceLine y={0} stroke={AXIS} />
            <Tooltip content={<CashFlowTooltip />} cursor={{ fill: CURSOR }} />
            <Bar dataKey="income_cents" name="Income" fill={SERIES.income} radius={[2, 2, 0, 0]} maxBarSize={24} isAnimationActive={false} />
            <Bar dataKey="expense_cents" name="Expenses" fill={SERIES.expense} radius={[2, 2, 0, 0]} maxBarSize={24} isAnimationActive={false} />
            {showNet && (
              <Line
                dataKey="net_cents"
                name="Net"
                type="monotone"
                stroke={SERIES.net}
                strokeWidth={2}
                dot={{ r: 3, fill: SURFACE, stroke: SERIES.net, strokeWidth: 2 }}
                activeDot={{ r: 5, fill: SERIES.net, stroke: SURFACE, strokeWidth: 2 }}
                isAnimationActive={false}
              >
                {/* Direct label: the latest net value sits next to its point, so no legend lookup is needed. */}
                <LabelList dataKey="net_cents" content={<LatestNetLabel lastIndex={rows.length - 1} />} />
              </Line>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <TrendTable rows={rows} />
    </div>
  )
}

function NetTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return (
    <div className="rounded-[var(--radius-control)] border border-line-strong bg-surface-raised px-3 py-2 text-xs text-ink shadow-pop">
      <p className="font-medium text-ink-muted">{formatMonth(row.month)}</p>
      <p className="mt-1 font-semibold tabular-nums">Net {formatKzt(row.net_cents)}</p>
    </div>
  )
}

/** Net per month (backend value): emerald above zero, coral below. */
export function NetBarsChart({ trend, height = 'h-52' }: { trend: MonthlyTrend; height?: string }) {
  return (
    <div className={`w-full ${height}`} aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={trend.months} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="month" tickFormatter={(m: string) => formatMonth(m, true)} axisLine={false} dy={8} {...axisProps} />
          <YAxis tickFormatter={(v: number) => formatKztCompact(Math.round(v))} axisLine={false} width={64} {...axisProps} />
          <ReferenceLine y={0} stroke={AXIS} />
          <Tooltip content={<NetTooltip />} cursor={{ fill: CURSOR }} />
          <Bar dataKey="net_cents" name="Net" radius={[2, 2, 2, 2]} maxBarSize={32} isAnimationActive={false}>
            {trend.months.map((row) => (
              <Cell key={row.month} fill={row.net_cents < 0 ? SERIES.expense : SERIES.income} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
