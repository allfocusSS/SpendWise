import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  usePlotArea,
  useXAxisScale,
  XAxis,
  YAxis,
} from 'recharts'

import type { ReactNode } from 'react'

import type { MonthlyTrend } from '../api/client'
import { AXIS, AXIS_TEXT, CURSOR, GRID, HIGHLIGHT, INK, SERIES, SURFACE } from '../lib/chartColors'
import { formatMonth } from '../lib/dates'
import { formatKzt, formatKztCompact } from '../lib/money'

type Row = MonthlyTrend['months'][number]

const CHART_FONT = "'Inter Variable', Inter, ui-sans-serif, system-ui, sans-serif"

/** "1.2M", "400K", "0": the unit (₸) is in the card's title, so the ticks stay short. */
const tick = (v: number) => formatKztCompact(Math.round(v)).replace(/\s₸$/, '')

const yAxisProps = {
  tick: { fill: AXIS_TEXT, fontSize: 11, fontFamily: CHART_FONT },
  tickLine: false,
  axisLine: false,
  width: 44,
  tickFormatter: tick,
} as const

/** A month's point: hollow, or filled and larger for the month the page is about. */
function pointRenderer(color: string, highlight?: string) {
  return function renderPoint({ cx, cy, index, payload }: { cx?: number; cy?: number; index?: number; payload?: Row }) {
    const on = payload?.month === highlight
    return (
      <circle key={index} cx={cx} cy={cy} r={on ? 5 : 3.5} fill={on ? color : SURFACE} stroke={on ? SURFACE : color} strokeWidth={2} />
    )
  }
}

function CashFlowTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  const lines = [
    { label: 'Income', color: SERIES.income, value: row.income_cents },
    { label: 'Expenses', color: SERIES.expense, value: row.expense_cents },
  ]
  return (
    <div className="min-w-48 rounded-xl bg-[#3a2f6b] px-3.5 py-3 text-xs text-ink shadow-pop">
      <p className="mb-2 font-semibold">{formatMonth(row.month)}</p>
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 tabular-nums">
        {lines.map((line) => (
          <div key={line.label} className="contents">
            <dt className="flex items-center gap-2 text-ink-muted">
              <span className="size-2 rounded-full" style={{ backgroundColor: line.color }} aria-hidden="true" />
              {line.label}
            </dt>
            <dd className="text-right">{formatKzt(line.value)}</dd>
          </div>
        ))}
        <dt className="mt-1 border-t border-white/10 pt-2 text-ink-muted">Net</dt>
        <dd className={`mt-1 border-t border-white/10 pt-2 text-right font-semibold ${row.net_cents < 0 ? 'text-expense' : row.net_cents > 0 ? 'text-income' : ''}`}>
          {formatKzt(row.net_cents)}
        </dd>
      </dl>
    </div>
  )
}

/** Month label under the axis; months inside the highlight are set in the text colour and semibold. */
function MonthTick({ x, y, payload, isOn, short = false }: {
  x?: number | string
  y?: number | string
  payload?: { value: string }
  isOn: (month: string) => boolean
  /** First letter only ("N"), for twelve months in a narrow card. */
  short?: boolean
}) {
  const month = payload?.value ?? ''
  const on = isOn(month)
  const label = formatMonth(month, true)
  return (
    <text x={x} y={Number(y) + 6} dy="0.71em" textAnchor="middle" fill={on ? INK : AXIS_TEXT} fontSize={11} fontWeight={on ? 600 : 400} fontFamily={CHART_FONT}>
      {short ? label.charAt(0) : label}
    </text>
  )
}

/** The chart's data as a table, behind a toggle; open, it takes the full width of the footer row. */
/**
 * A shaded band behind months `first` to `last` (inclusive), reaching half-way to the neighbouring
 * months; `maxHalf` keeps a single highlighted month narrow.
 */
function MonthBand({ months, first, last, maxHalf = Infinity }: { months: string[]; first: string; last: string; maxHalf?: number }) {
  const scale = useXAxisScale()
  const plot = usePlotArea()
  const start = scale?.(first)
  const end = scale?.(last)
  if (!scale || !plot || start === undefined || end === undefined) return null
  const step = months.length > 1 ? (scale(months[1]) ?? 0) - (scale(months[0]) ?? 0) : plot.width
  const half = Math.min(step / 2, maxHalf)
  const x0 = Math.max(plot.x, start - half)
  const x1 = Math.min(plot.x + plot.width, end + half)
  return <rect x={x0} y={plot.y} width={Math.max(x1 - x0, 0)} height={plot.height} rx={10} fill={HIGHLIGHT} />
}

function TrendTable({ rows }: { rows: Row[] }) {
  return (
    <details className="ml-auto text-sm open:ml-0 open:basis-full">
      <summary className="w-fit cursor-pointer list-none rounded-sm py-1 text-label font-semibold text-accent hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus pointer-coarse:py-3 [&::-webkit-details-marker]:hidden">
        Show as table
      </summary>
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
 * Smooth areas for income and expenses per month, on ONE axis (same unit, ₸); the net is in the
 * tooltip and the table. Monotone curves never overshoot below zero or between months. Values come
 * straight from the backend. `highlight` marks one month (the Overview's), `band` a run of months
 * (the Analytics period). Includes a table view.
 */
export function CashFlowChart({ trend, height = 'h-72', highlight, band, summary }: {
  trend: MonthlyTrend
  height?: string
  /** A month ("YYYY-MM") to emphasise. */
  highlight?: string
  /** First and last month ("YYYY-MM") of a period to shade. */
  band?: [string, string]
  /** Shown under the chart, beside the table toggle (e.g. the window's totals). */
  summary?: ReactNode
}) {
  const rows = trend.months
  const months = rows.map((row) => row.month)
  const isOn = (month: string) => month === highlight || (band !== undefined && month >= band[0] && month <= band[1])
  return (
    <div>
      <p className="sr-only">
        Income and expenses per month from {formatMonth(rows[0].month)} to {formatMonth(rows[rows.length - 1].month)}. Exact
        values are in the table below the chart.
      </p>
      <div className={`w-full ${height}`} aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          {/* The chart is hidden from assistive technology (the table below is its text version), so
              Recharts' keyboard layer would only add a tab stop that announces nothing. */}
          <AreaChart data={rows} margin={{ top: 10, right: 10, bottom: 0, left: 0 }} accessibilityLayer={false}>
            <defs>
              {(['expense', 'income'] as const).map((key) => (
                <linearGradient key={key} id={`cf-${key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={SERIES[key]} stopOpacity={0.42} />
                  <stop offset="1" stopColor={SERIES[key]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} />
            {band ? <MonthBand months={months} first={band[0]} last={band[1]} /> : null}
            {highlight ? <MonthBand months={months} first={highlight} last={highlight} maxHalf={22} /> : null}
            <XAxis dataKey="month" axisLine={false} tickLine={false} interval={0} tick={<MonthTick isOn={isOn} />} />
            <YAxis {...yAxisProps} tickCount={4} />
            <Tooltip content={<CashFlowTooltip />} cursor={{ stroke: AXIS, strokeDasharray: '3 3' }} />
            <Area
              dataKey="expense_cents"
              name="Expenses"
              type="monotone"
              stroke={SERIES.expense}
              strokeWidth={2.5}
              fill="url(#cf-expense)"
              dot={pointRenderer(SERIES.expense, highlight)}
              activeDot={{ r: 5, fill: SERIES.expense, stroke: SURFACE, strokeWidth: 2 }}
              isAnimationActive={false}
            />
            <Area
              dataKey="income_cents"
              name="Income"
              type="monotone"
              stroke={SERIES.income}
              strokeWidth={2.5}
              fill="url(#cf-income)"
              dot={pointRenderer(SERIES.income, highlight)}
              activeDot={{ r: 5, fill: SERIES.income, stroke: SURFACE, strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {summary}
        <TrendTable rows={rows} />
      </div>
    </div>
  )
}

function NetTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return (
    <div className="rounded-xl bg-[#3a2f6b] px-3 py-2 text-xs text-ink shadow-pop">
      <p className="font-semibold">{formatMonth(row.month)}</p>
      <p className={`mt-1 font-semibold tabular-nums ${row.net_cents < 0 ? 'text-expense' : 'text-income'}`}>Net {formatKzt(row.net_cents)}</p>
    </div>
  )
}

/**
 * A symmetric axis for the net bars: zero in the middle and one round gridline above and below it
 * (the largest 1, 2 or 5 × 10ⁿ under the biggest month), so saving and overspending read on the
 * same scale.
 */
function netScale(rows: Row[]) {
  const peak = Math.max(...rows.map((row) => Math.abs(row.net_cents)), 1)
  const power = 10 ** Math.floor(Math.log10(peak))
  const step = [5, 2, 1].map((n) => n * power).find((n) => n <= peak) ?? power
  const max = Math.ceil((peak * 1.05) / (step / 5)) * (step / 5)
  return { domain: [-max, max], ticks: [-step, 0, step] }
}

const signedTick = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${tick(Math.abs(v))}`

/** Net per month (backend value): violet above zero for months that saved, pink below for months that overspent. */
export function NetBarsChart({ trend, label, height = 'h-40', highlight, shortLabels = false }: {
  trend: MonthlyTrend
  /** What the bars show, for screen readers ("Monthly net, 6 months to Nov 2026"). */
  label: string
  height?: string
  /** A month ("YYYY-MM") to emphasise. */
  highlight?: string
  /** One-letter month labels, for twelve months in a narrow card. */
  shortLabels?: boolean
}) {
  const scale = netScale(trend.months)
  return (
    <div className={`w-full ${height}`} role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={trend.months} margin={{ top: 8, right: 6, bottom: 0, left: 0 }} accessibilityLayer={false}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} />
          <XAxis
            dataKey="month"
            axisLine={false}
            tickLine={false}
            interval={0}
            tick={<MonthTick isOn={(month) => month === highlight} short={shortLabels} />}
          />
          <YAxis {...yAxisProps} width={48} domain={scale.domain} ticks={scale.ticks} tickFormatter={signedTick} />
          <ReferenceLine y={0} stroke={AXIS_TEXT} strokeOpacity={0.45} />
          <Tooltip content={<NetTooltip />} cursor={{ fill: CURSOR }} />
          <Bar dataKey="net_cents" name="Net" radius={4} maxBarSize={16} isAnimationActive={false}>
            {trend.months.map((row) => (
              <Cell key={row.month} fill={row.net_cents < 0 ? SERIES.expense : SERIES.income} fillOpacity={!highlight || row.month === highlight ? 1 : 0.8} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
