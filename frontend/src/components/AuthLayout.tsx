import type { ReactNode } from 'react'

import { cardClass } from '../lib/styles'
import { BrandMark } from './Layout'

/** Shell for the login and register pages: brand bar, then one narrow form card. */
export function AuthLayout({ title, description, children, footer }: {
  title: string
  description: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-line">
        <div className="mx-auto flex h-16 max-w-[1440px] items-center px-4 sm:px-6 lg:px-8">
          <BrandMark />
        </div>
      </header>
      <main id="main" className="flex flex-1 justify-center px-4 pt-12 pb-16 sm:pt-20">
        <div className="w-full max-w-sm">
          <h1 className="text-title text-ink">{title}</h1>
          <p className="mt-1 text-sm text-ink-muted">{description}</p>
          <div className={`${cardClass} mt-6 p-5 sm:p-6`}>{children}</div>
          <p className="mt-5 text-center text-label text-ink-subtle">{footer}</p>
        </div>
      </main>
    </div>
  )
}
