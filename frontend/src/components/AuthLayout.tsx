import type { ReactNode } from 'react'

import { BrandMark } from './Layout'

/**
 * Shell for the login and register pages: a brand panel (headline and one line about the product)
 * beside the form from lg; above it, as a compact header with the headline only, on smaller screens.
 */
export function AuthLayout({ title, description, headline, lead, children, footer }: {
  title: string
  description: string
  headline: string
  lead: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-4 lg:p-4">
      <section
        aria-label="About SpendWise"
        className="flex flex-col bg-surface gap-[22px] rounded-b-3xl px-[22px] pt-[26px] pb-[30px] lg:justify-between lg:gap-10 lg:rounded-[22px] lg:px-[52px] lg:py-11"
      >
        <BrandMark />
        <div>
          <p className="max-w-[520px] text-[30px] leading-[1.06] font-[650] tracking-[-0.035em] text-ink lg:text-[46px]">{headline}</p>
          <p className="mt-4 hidden max-w-[460px] text-base text-ink-muted lg:block">{lead}</p>
        </div>
        <span className="hidden lg:block" aria-hidden="true" />
      </section>
      <main id="main" className="flex items-start justify-center px-[22px] pt-7 pb-10 lg:items-center lg:p-6">
        <div className="w-full max-w-[420px]">
          <h1 className="text-[26px] leading-tight font-[650] tracking-[-0.03em] text-ink lg:text-[30px]">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-muted">{description}</p>
          <div className="mt-7">{children}</div>
          <p className="mt-6 border-t border-line pt-[22px] text-center text-sm text-ink-muted">{footer}</p>
        </div>
      </main>
    </div>
  )
}
