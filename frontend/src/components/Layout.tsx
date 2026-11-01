import { useCallback, useState } from 'react'
import { NavLink, Outlet } from 'react-router'

import type { Transaction, TransactionType } from '../api/client'
import { useCurrentUser, useLogout } from '../api/queries'
import { TransactionDialogContext, type OpenTransactionDialog } from '../lib/transactionDialog'
import { AnalyticsIcon, DashboardIcon, PlusIcon, TagIcon, TransactionsIcon } from './icons'
import { TransactionDialog } from './TransactionDialog'
import { Button } from './ui'

const NAV = [
  { to: '/', label: 'Dashboard', icon: DashboardIcon, end: true },
  { to: '/transactions', label: 'Transactions', icon: TransactionsIcon },
  { to: '/categories', label: 'Categories', icon: TagIcon },
  { to: '/analytics', label: 'Analytics', icon: AnalyticsIcon },
]

/** The ₸ mark and wordmark (also used on the sign-in pages). */
export function BrandMark() {
  return (
    <span className="flex shrink-0 items-center gap-2.5">
      <span className="grid size-8 place-items-center rounded-md bg-accent text-[15px] font-semibold text-on-accent" aria-hidden="true">
        ₸
      </span>
      <span className="text-base font-semibold tracking-[-0.02em] text-ink">SpendWise</span>
    </span>
  )
}

function Brand() {
  return (
    <NavLink to="/" aria-label="SpendWise home" className="flex shrink-0 rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent">
      <BrandMark />
    </NavLink>
  )
}

/** Signed-in email (wide screens) and the log-out action. */
function Account() {
  const user = useCurrentUser().data
  const logout = useLogout()
  return (
    <div className="flex items-center gap-3">
      {user && (
        <span className="hidden max-w-56 truncate text-xs text-ink-subtle xl:inline" title={user.email}>
          {user.email}
        </span>
      )}
      <Button variant="ghost" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
        {logout.isPending ? 'Logging out…' : 'Log out'}
      </Button>
      {logout.isError && (
        <span role="alert" className="text-xs text-danger">
          Couldn’t log out. Try again.
        </span>
      )}
    </div>
  )
}

/** Desktop (≥1024px): text navigation; the current page is underlined. */
function TopNav() {
  return (
    <nav aria-label="Main" className="hidden self-stretch lg:block">
      <ul className="flex h-full items-stretch gap-7">
        {NAV.map(({ to, label, end }) => (
          <li key={to} className="flex">
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                `relative flex items-center text-label font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                  isActive ? 'text-ink' : 'text-ink-subtle hover:text-ink'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {label}
                  {isActive && <span className="absolute inset-x-0 -bottom-px h-0.5 bg-ink" aria-hidden="true" />}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** Phones and tablets (<1024px): fixed bottom tab bar (four destinations, icon + label). */
function BottomTabs() {
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-canvas/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
      <ul className="grid grid-cols-4">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${
                  isActive ? 'text-ink' : 'text-ink-subtle'
                }`
              }
            >
              <Icon className="size-5" />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export function Layout() {
  const [dialog, setDialog] = useState<{ open: boolean; transaction: Transaction | null; type: TransactionType }>({
    open: false,
    transaction: null,
    type: 'expense',
  })

  const openTransaction = useCallback<OpenTransactionDialog>((options = {}) => {
    const transaction = options.transaction ?? null
    setDialog({ open: true, transaction, type: transaction?.type ?? options.type ?? 'expense' })
  }, [])

  return (
    <TransactionDialogContext.Provider value={openTransaction}>
      <div className="min-h-dvh">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-surface-raised focus:px-4 focus:py-2 focus:text-ink focus:shadow-pop"
        >
          Skip to content
        </a>

        <header className="sticky top-0 z-30 border-b border-line bg-canvas/95 backdrop-blur">
          <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
            <div className="flex h-full items-center gap-12">
              <Brand />
              <TopNav />
            </div>
            <div className="flex items-center gap-3 sm:gap-5">
              <Account />
              <Button onClick={() => openTransaction()} className="max-sm:size-10 max-sm:p-0" aria-label="Add transaction">
                <PlusIcon strokeWidth={2.2} className="size-4" />
                <span className="max-sm:sr-only">Add transaction</span>
              </Button>
            </div>
          </div>
        </header>

        <main id="main" className="mx-auto w-full max-w-[1440px] px-4 pt-6 pb-8 sm:px-6 lg:px-8 lg:pt-8 lg:pb-10">
          <Outlet />
        </main>

        <footer className="mx-auto max-w-[1440px] px-4 pb-24 text-center text-xs text-ink-subtle lg:px-8 lg:pb-8 lg:text-left">
          Amounts are in Kazakhstani tenge (₸).
        </footer>

        <BottomTabs />

        <TransactionDialog
          open={dialog.open}
          transaction={dialog.transaction}
          defaultType={dialog.type}
          onClose={() => setDialog((current) => ({ ...current, open: false, transaction: null }))}
        />
      </div>
    </TransactionDialogContext.Provider>
  )
}
