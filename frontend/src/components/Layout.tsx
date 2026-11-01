import { NavLink, Outlet } from 'react-router'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/transactions', label: 'Transactions' },
  { to: '/categories', label: 'Categories' },
  { to: '/analytics', label: 'Analytics' },
]

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-8">
          <NavLink to="/" className="flex items-center gap-2 text-lg font-bold tracking-tight text-slate-900">
            <span className="grid size-7 place-items-center rounded-lg bg-indigo-600 text-sm text-white" aria-hidden="true">
              ₸
            </span>
            SpendWise
          </NavLink>
          <nav aria-label="Main">
            <ul className="grid grid-cols-4 gap-1 sm:flex">
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `block whitespace-nowrap rounded-lg px-1 py-1.5 text-center text-[13px] font-medium transition-colors sm:px-3 sm:text-sm ${
                        isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-8">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-500">
        SpendWise local MVP · No authentication: do not expose this app publicly. · Amounts in KZT (₸)
      </footer>
    </div>
  )
}
