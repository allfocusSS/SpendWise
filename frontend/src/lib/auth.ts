/** Session helpers shared by the route guards, the auth pages and the query client. */

/** React Query key of the signed-in user (null when signed out). */
export const CURRENT_USER_KEY = ['auth', 'me'] as const

const AUTH_PAGES = new Set(['/login', '/register'])

/**
 * Where to go after signing in: the page the user originally asked for, if it is a page of this
 * app. Anything else (other sites, protocol-relative "//host", the auth pages themselves) falls
 * back to the dashboard, so the value can never be used as an open redirect.
 */
export function safeRedirectPath(from: unknown): string {
  if (typeof from !== 'object' || from === null) return '/'
  const { pathname, search = '', hash = '' } = from as { pathname?: unknown; search?: unknown; hash?: unknown }
  if (typeof pathname !== 'string' || typeof search !== 'string' || typeof hash !== 'string') return '/'
  if (!pathname.startsWith('/') || pathname.startsWith('//') || pathname.includes('\\')) return '/'
  if (AUTH_PAGES.has(pathname)) return '/'
  return `${pathname}${search}${hash}`
}
