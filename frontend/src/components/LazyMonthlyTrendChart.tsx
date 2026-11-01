import { lazy, Suspense } from 'react'

import type { MonthlyTrend } from '../api/client'
import { LoadingState } from './ui'

// Recharts is the largest dependency, so it is loaded only when a chart is on screen.
const MonthlyTrendChart = lazy(() =>
  import('./MonthlyTrendChart').then((module) => ({ default: module.MonthlyTrendChart })),
)

export function LazyMonthlyTrendChart({ trend }: { trend: MonthlyTrend }) {
  return (
    <Suspense fallback={<LoadingState label="Loading chart" />}>
      <MonthlyTrendChart trend={trend} />
    </Suspense>
  )
}
