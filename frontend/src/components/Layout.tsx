import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'

import type { Transaction, TransactionType } from '../api/client'
import { useCurrentUser, useLogout } from '../api/queries'
import { CURRENT_USER_KEY } from '../lib/auth'
import { TransactionDialogContext, type OpenTransactionDialog } from '../lib/transactionDialog'
import { ErrorBoundary, PageErrorFallback } from './ErrorBoundary'
import { AnalyticsIcon, DashboardIcon, LogoutIcon, PlusIcon, TagIcon, TransactionsIcon } from './icons'
import { Toaster } from './Toaster'
import { TransactionDialog } from './TransactionDialog'
import { Button } from './ui'

const NAV = [
  { to: '/', label: 'Overview', icon: DashboardIcon, end: true },
  { to: '/transactions', label: 'Transactions', icon: TransactionsIcon },
  { to: '/categories', label: 'Categories', icon: TagIcon },
  { to: '/analytics', label: 'Analytics', icon: AnalyticsIcon },
]

/** Below lg the page title moves into the app bar (each page shows its own h1 from lg). */
const TITLES: Record<string, string> = { '/': 'Overview', '/transactions': 'Transactions', '/categories': 'Categories', '/analytics': 'Analytics' }

/** The ₸ mark and wordmark (also used on the sign-in pages). */
export function BrandMark({ wordmark = 'always' }: { wordmark?: 'always' | 'wide' }) {
  return (
    <span className="flex shrink-0 items-center gap-2.5">
      <span className="grid size-[34px] place-items-center rounded-[10px] bg-brand text-[17px] font-bold text-white" aria-hidden="true">
        ₸
      </span>
      <span className={`text-lg font-[650] tracking-[-0.02em] text-ink ${wordmark === 'wide' ? 'max-xl:sr-only' : ''}`}>
        SpendWise
      </span>
    </span>
  )
}

const railLabel = 'max-xl:sr-only'

/** Desktop (lg+): the floating sidebar; an icon rail from lg, labels from xl. */
function Sidebar({ onAdd }: { onAdd: () => void }) {
  const user = useCurrentUser().data
  const logout = useLogout()
  return (
    <div className="fixed inset-y-4 left-4 z-30 hidden w-[76px] flex-col items-center gap-[22px] rounded-[18px] bg-surface px-3 py-[22px] lg:flex xl:w-[220px] xl:items-stretch xl:px-3.5">
      <NavLink to="/" aria-label="SpendWise home" className="rounded-lg px-0 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus xl:px-2">
        <BrandMark wordmark="wide" />
      </NavLink>
      <nav aria-label="Main" className="w-full">
        <ul className="flex flex-col items-center gap-1 xl:items-stretch">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                title={label}
                className={({ isActive }) =>
                  `flex size-12 items-center justify-center gap-3 rounded-[11px] border text-[14px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus xl:h-[42px] xl:w-full xl:justify-start xl:px-3 ${
                    isActive ? 'border-line-strong bg-surface-raised text-accent' : 'border-transparent text-ink-muted hover:bg-white/[0.03] hover:text-ink'
                  }`
                }
              >
                <Icon className="size-[19px] shrink-0" />
                <span className={railLabel}>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <Button onClick={onAdd} className="size-12 rounded-[14px] p-0 xl:h-11 xl:w-full xl:rounded-[var(--radius-control)]">
        <PlusIcon strokeWidth={2.2} className="size-[17px]" />
        <span className={railLabel}>Add transaction</span>
      </Button>
      <div className="mt-auto flex w-full flex-col items-center gap-2 xl:items-stretch">
        {user ? (
          <div className="flex items-center gap-2.5 xl:px-2" title={user.email}>
            <span className="grid size-[38px] shrink-0 place-items-center rounded-full bg-[linear-gradient(135deg,#3b2f73,#5b2a6e)] text-sm font-semibold text-white ring-1 ring-white/10" aria-hidden="true">
              {user.email.charAt(0).toUpperCase()}
            </span>
            <span className="min-w-0 truncate text-xs text-ink-muted max-xl:sr-only">{user.email}</span>
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
          className="flex size-12 items-center justify-center gap-3 rounded-[11px] text-[14px] font-medium text-ink-muted transition-colors hover:bg-white/[0.03] hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus xl:h-[42px] xl:w-full xl:justify-start xl:px-3"
        >
          <LogoutIcon className="size-[19px] shrink-0" />
          <span className={railLabel}>{logout.isPending ? 'Logging out…' : 'Log out'}</span>
        </button>
        {logout.isError ? (
          <span role="alert" className="text-center text-xs text-danger">Couldn’t log out. Try again.</span>
        ) : null}
      </div>
    </div>
  )
}

/** Phones and tablets (below lg): an app bar with the page title and log out. */
function AppBar({ title }: { title: string }) {
  const logout = useLogout()
  return (
    <div className="flex h-[58px] items-center justify-between gap-3 border-b border-line bg-surface px-3.5 lg:hidden">
      <div className="flex min-w-0 items-center gap-2.5">
        <NavLink to="/" aria-label="SpendWise home" className="shrink-0 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
          <span className="grid size-[30px] place-items-center rounded-[9px] bg-brand text-[15px] font-bold text-white" aria-hidden="true">₸</span>
        </NavLink>
        {title ? <h1 className="truncate text-[17px] font-semibold text-ink">{title}</h1> : null}
      </div>
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        className="grid size-11 place-items-center rounded-xl text-ink-muted hover:bg-white/5 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <LogoutIcon className="size-5" />
        <span className="sr-only">{logout.isPending ? 'Logging out…' : 'Log out'}</span>
      </button>
    </div>
  )
}

/** Phones and tablets: fixed bottom tab bar, four destinations around the add button. */
function TabBar({ onAdd }: { onAdd: () => void }) {
  const tab = ({ to, label, icon: Icon, end }: (typeof NAV)[number]) => (
    <li key={to}>
      <NavLink
        to={to}
        end={end}
        className={({ isActive }) =>
          `flex min-h-[52px] flex-col items-center justify-center gap-[3px] rounded-xl text-[10.5px] font-medium focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus ${
            isActive ? 'text-accent' : 'text-ink-subtle'
          }`
        }
      >
        <Icon className="size-[21px]" />
        {label}
      </NavLink>
    </li>
  )
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface px-1.5 pt-1.5 pb-[max(12px,env(safe-area-inset-bottom))] lg:hidden">
      <ul className="grid grid-cols-5 items-center">
        {NAV.slice(0, 2).map(tab)}
        <li className="flex justify-center">
          <button
            type="button"
            onClick={onAdd}
            className="grid size-[54px] place-items-center rounded-[18px] bg-brand text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
          >
            <PlusIcon strokeWidth={2.2} className="size-6" />
            <span className="sr-only">Add transaction</span>
          </button>
        </li>
        {NAV.slice(2).map(tab)}
      </ul>
    </nav>
  )
}

export function Layout() {
  const location = useLocation()
  const client = useQueryClient()
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
      <Toaster>
        <div className="min-h-dvh">
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-surface-raised focus:px-4 focus:py-2 focus:text-ink focus:shadow-pop"
          >
            Skip to content
          </a>

          {/* All app chrome in one banner: the sidebar (lg+), or the app bar and tab bar (below lg). */}
          <header className="sticky top-0 z-30 lg:static">
            <Sidebar onAdd={() => openTransaction()} />
            <AppBar title={TITLES[location.pathname] ?? ''} />
            <TabBar onAdd={() => openTransaction()} />
          </header>

          <main id="main" className="mx-auto w-full max-w-[1680px] px-3.5 pt-3.5 pb-6 lg:pt-4 lg:pr-4 lg:pl-[112px] xl:pl-[256px]">
            {/* A page that throws is replaced by a fallback; the header and navigation keep working.
                Each page gets a fresh boundary, and "Try again" refetches its data (not the session). */}
            <ErrorBoundary
              key={location.pathname}
              name="page"
              onRetry={() => client.resetQueries({ predicate: (query) => query.queryKey[0] !== CURRENT_USER_KEY[0] })}
              fallback={(props) => <PageErrorFallback {...props} />}
            >
              <Outlet />
            </ErrorBoundary>
          </main>

          <footer className="mx-auto max-w-[1680px] px-3.5 pb-28 text-xs text-ink-subtle lg:pr-4 lg:pb-6 lg:pl-[112px] xl:pl-[256px]">
            Amounts are in Kazakhstani tenge (₸).
          </footer>

          <TransactionDialog
            open={dialog.open}
            transaction={dialog.transaction}
            defaultType={dialog.type}
            onClose={() => setDialog((current) => ({ ...current, open: false, transaction: null }))}
          />
        </div>
      </Toaster>
    </TransactionDialogContext.Provider>
  )
}
