import { useId } from 'react'

/**
 * Small area sparkline in plain SVG (no chart library), for the balance hero.
 * Scaling is presentation only; the values are backend figures (e.g. monthly net).
 * The end point is an HTML dot so the stretched SVG never distorts it into an ellipse.
 */
export function Sparkline({ values, color, label, className = 'h-14 w-full' }: {
  values: number[]
  color: string
  label: string
  className?: string
}) {
  // useId may contain characters that are not valid inside url(#…), so keep it to [A-Za-z0-9_-].
  const gradientId = `spark${useId().replace(/[^A-Za-z0-9_-]/g, '')}`
  if (values.length < 2) return null

  const width = 200
  const height = 56
  const pad = 6
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 0)
  const span = max - min || 1
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2)
  const points = values.map((v, i) => [(i / (values.length - 1)) * width, y(v)])
  const line = points.map(([px, py], i) => `${i === 0 ? 'M' : 'L'}${px.toFixed(1)},${py.toFixed(1)}`).join(' ')
  const zeroY = y(0)
  const area = `${line} L${width},${zeroY} L0,${zeroY} Z`
  const last = points[points.length - 1]

  return (
    <div className={`relative ${className}`} role="img" aria-label={label}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="size-full overflow-visible" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.32} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <line x1="0" x2={width} y1={zeroY} y2={zeroY} stroke="currentColor" strokeOpacity={0.35} strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
        <path d={area} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <span
        className="absolute size-2.5 -translate-1/2 rounded-full ring-[3px] ring-surface"
        style={{ left: '100%', top: `${(last[1] / height) * 100}%`, backgroundColor: color }}
        aria-hidden="true"
      />
    </div>
  )
}
