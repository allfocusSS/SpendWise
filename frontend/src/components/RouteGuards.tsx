import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { useCurrentUser } from '../api/queries'
import { safeRedirectPath } from '../lib/auth'
import { ErrorState, Spinner } from './ui'

function FullPage({ children }: { children: ReactNode }) {
  return <div className="flex min-h-dvh items-center justify-center px-4">{children}</div>
}

/** The app itself: only for signed-in users. Others go to the login page, which brings them
 * back here afterwards. The backend enforces this too; the guard only decides what to show. */
export function RequireAuth() {
  const me = useCurrentUser()
  const location = useLocation()

  if (me.isPending) {
    return <FullPage><Spinner label="Checking your session" /></FullPage>
  }
  if (me.isError) {
    return (
      <FullPage>
        <div className="w-full max-w-sm"><ErrorState error={me.error} onRetry={() => me.refetch()} /></div>
      </FullPage>
    )
  }
  if (!me.data) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <Outlet />
}

/** Login and register: signed-in users are sent on to the page they asked for (or home). */
export function GuestOnly() {
  const me = useCurrentUser()
  const location = useLocation()

  if (me.isPending) {
    return <FullPage><Spinner label="Checking your session" /></FullPage>
  }
  if (me.data) {
    const from = (location.state as { from?: unknown } | null)?.from
    return <Navigate to={safeRedirectPath(from)} replace />
  }
  return <Outlet />
}
