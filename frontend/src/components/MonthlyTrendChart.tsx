import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { MonthlyTrend } from '../api/client'
import { AXIS_TEXT, GRID, SERIES } from '../lib/chartColors'
import { formatMonth } from '../lib/dates'
import { formatKzt, formatKztCompact } from '../lib/money'

type Row = MonthlyTrend['months'][number]

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-slate-900">{formatMonth(row.month)}</p>
      <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 tabular-nums">
        <dt className="flex items-center gap-1.5 text-slate-600">
          <span className="size-2 rounded-sm" style={{ backgroundColor: SERIES.income }} aria-hidden="true" />
          Income
        </dt>
        <dd className="text-right text-slate-900">{formatKzt(row.income_cents)}</dd>
        <dt className="flex items-center gap-1.5 text-slate-600">
          <span className="size-2 rounded-sm" style={{ backgroundColor: SERIES.expense }} aria-hidden="true" />
          Expenses
        </dt>
        <dd className="text-right text-slate-900">{formatKzt(row.expense_cents)}</dd>
        <dt className="text-slate-600">Net</dt>
        <dd className="text-right font-medium text-slate-900">{formatKzt(row.net_cents)}</dd>
      </dl>
    </div>
  )
}

/** Income vs expenses per month (grouped columns, one shared axis), plus a table view. */
export function MonthlyTrendChart({ trend }: { trend: MonthlyTrend }) {
  const rows = trend.months
  return (
    <div>
      {/* HTML legend in series order (Recharts' legend sorts alphabetically). */}
      <ul className="mb-2 flex gap-4 text-xs text-slate-600" aria-label="Legend">
        <li className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ backgroundColor: SERIES.income }} aria-hidden="true" />
          Income
        </li>
        <li className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ backgroundColor: SERIES.expense }} aria-hidden="true" />
          Expenses
        </li>
      </ul>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} barGap={2} barCategoryGap="25%" margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis
              dataKey="month"
              tickFormatter={(m: string) => formatMonth(m, true)}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
              axisLine={{ stroke: GRID }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => formatKztCompact(Math.round(v))}
              tick={{ fill: AXIS_TEXT, fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              width={64}
            />
            <Tooltip content={<TrendTooltip />} cursor={{ fill: '#f1f5f9' }} />
            <Bar dataKey="income_cents" name="Income" fill={SERIES.income} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
            <Bar dataKey="expense_cents" name="Expenses" fill={SERIES.expense} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-slate-600 hover:text-slate-900">Show as table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left tabular-nums">
            <caption className="sr-only">Monthly income, expenses and net</caption>
            <thead className="text-xs text-slate-500">
              <tr>
                <th scope="col" className="py-1 pr-4 font-medium">Month</th>
                <th scope="col" className="py-1 pr-4 text-right font-medium">Income</th>
                <th scope="col" className="py-1 pr-4 text-right font-medium">Expenses</th>
                <th scope="col" className="py-1 text-right font-medium">Net</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-800">
              {rows.map((row) => (
                <tr key={row.month}>
                  <th scope="row" className="py-1.5 pr-4 font-normal">{formatMonth(row.month)}</th>
                  <td className="py-1.5 pr-4 text-right">{formatKzt(row.income_cents)}</td>
                  <td className="py-1.5 pr-4 text-right">{formatKzt(row.expense_cents)}</td>
                  <td className="py-1.5 text-right font-medium">{formatKzt(row.net_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
