/**
 * Recovering from errors the error boundaries catch (components/ErrorBoundary.tsx).
 *
 * Two kinds of failure:
 * - "chunk": a lazily loaded bundle (the charts) could not be fetched. Usually a tab opened before
 *   a deploy asking for a file the new build no longer has, sometimes a dropped connection.
 * - "render": a component threw while rendering.
 *
 * Kept free of React so the rules can be unit-tested.
 */

export type ErrorKind = 'chunk' | 'render'

// What each browser (and Vite's preloader) says when a dynamic import's file can't be loaded.
const CHUNK_ERROR_MESSAGES = [
  'Failed to fetch dynamically imported module', // Chromium
  'error loading dynamically imported module', // Firefox
  'Importing a module script failed', // Safari
  'Unable to preload CSS', // Vite's preloader
]

export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return error.name === 'ChunkLoadError' || CHUNK_ERROR_MESSAGES.some((text) => error.message.includes(text))
}

export function errorKind(error: unknown): ErrorKind {
  return isChunkLoadError(error) ? 'chunk' : 'render'
}

/**
 * What may be logged about an error: its kind and its class name ("TypeError"). Never the message
 * or the stack, which can carry amounts, descriptions or other data from the page.
 */
export function errorSummary(error: unknown): { kind: ErrorKind; name: string } {
  const name = error instanceof Error && /^[A-Za-z][A-Za-z0-9]{0,39}$/.test(error.name) ? error.name : 'Error'
  return { kind: errorKind(error), name }
}

export function logError(where: string, error: unknown): void {
  const { kind, name } = errorSummary(error)
  console.error(`[SpendWise] ${where}: ${kind} error (${name})`)
  // Only in development builds: the full error, to debug it.
  if (import.meta.env.DEV) console.error(error)
}

// --- Reloading once after a chunk error ---------------------------------------------------------

type FlagStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

/** Set while an automatic reload is under way; cleared once a chunk loads again. */
export const CHUNK_RELOAD_KEY = 'spendwise:chunk-reload'

/** This tab's sessionStorage, or null where the browser blocks it. */
export function tabStorage(): FlagStore | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export type ReloadEnvironment = {
  store: FlagStore | null
  /** True while a dialog is open: reloading would throw away what is being typed in it. */
  hasOpenDialog: () => boolean
  reload: () => void
}

function browserEnvironment(): ReloadEnvironment {
  return {
    store: tabStorage(),
    hasOpenDialog: () => document.querySelector('dialog[open]') !== null,
    reload: () => window.location.reload(),
  }
}

/**
 * After a chunk error, reload the page once: a tab left open across a deploy then gets the new
 * build. Never twice in a row: the flag stays until a chunk loads again, so a chunk that keeps
 * failing shows its fallback instead of reloading forever. Without storage there is no way to
 * know, so no automatic reload at all. Returns whether it reloaded.
 */
export function reloadOnceForChunkError(environment: ReloadEnvironment = browserEnvironment()): boolean {
  const { store } = environment
  if (!store || environment.hasOpenDialog()) return false
  try {
    if (store.getItem(CHUNK_RELOAD_KEY) !== null) return false
    store.setItem(CHUNK_RELOAD_KEY, '1')
  } catch {
    return false
  }
  environment.reload()
  return true
}

/** A chunk loaded: the next chunk error may reload again. */
export function chunkLoaded(store: FlagStore | null = tabStorage()): void {
  try {
    store?.removeItem(CHUNK_RELOAD_KEY)
  } catch {
    // Nothing to clear without storage.
  }
}

// --- Loading a chunk again ----------------------------------------------------------------------

/**
 * A dynamic import that can be tried again. React.lazy keeps a failed import's error for good, so
 * a retry needs a new lazy component: `retry()` says whether one is needed (only after a failure).
 */
export function retryableLoader<T>(load: () => Promise<T>, onLoaded: () => void = chunkLoaded) {
  let failed = false
  return {
    load: (): Promise<T> =>
      load().then(
        (value) => {
          failed = false
          onLoaded()
          return value
        },
        (error: unknown) => {
          failed = true
          throw error
        },
      ),
    retry: (): boolean => {
      if (!failed) return false
      failed = false
      return true
    },
  }
}
