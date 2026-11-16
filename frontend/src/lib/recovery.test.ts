import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CHUNK_RELOAD_KEY,
  chunkLoaded,
  errorKind,
  errorSummary,
  isChunkLoadError,
  logError,
  reloadOnceForChunkError,
  retryableLoader,
  tabStorage,
  type ReloadEnvironment,
} from './recovery'

/** sessionStorage stand-in. */
function memoryStore() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    values,
  }
}

function environment(overrides: Partial<ReloadEnvironment> = {}) {
  const reload = vi.fn()
  const env: ReloadEnvironment = { store: memoryStore(), hasOpenDialog: () => false, reload, ...overrides }
  return { env, reload }
}

// A message with private figures, as a render error can have (formatKzt's RangeError does).
const PRIVATE = 'formatKzt expects an integer number of tiyn, got 1234.5 for Salary'

describe('isChunkLoadError', () => {
  it.each([
    ['Chromium', new TypeError('Failed to fetch dynamically imported module: https://x.test/assets/MonthlyTrendChart-1a2b.js')],
    ['Firefox', new TypeError('error loading dynamically imported module: https://x.test/assets/MonthlyTrendChart-1a2b.js')],
    ['Safari', new TypeError('Importing a module script failed.')],
    ['Vite preloader', new Error('Unable to preload CSS for /assets/index-1a2b.css')],
  ])('recognises a failed chunk (%s)', (_browser, error) => {
    expect(isChunkLoadError(error)).toBe(true)
    expect(errorKind(error)).toBe('chunk')
  })

  it('recognises an error named ChunkLoadError', () => {
    const error = new Error('Loading chunk 3 failed')
    error.name = 'ChunkLoadError'
    expect(isChunkLoadError(error)).toBe(true)
  })

  it.each([
    ['a render error', new TypeError("Cannot read properties of undefined (reading 'name')")],
    ['a money error', new RangeError(PRIVATE)],
    ['a string', 'Failed to fetch dynamically imported module'],
    ['null', null],
    ['a plain object', { message: 'Failed to fetch dynamically imported module' }],
  ])('treats %s as a render error', (_what, error) => {
    expect(isChunkLoadError(error)).toBe(false)
    expect(errorKind(error)).toBe('render')
  })
})

describe('errorSummary and logError', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
  })

  it('keeps the kind and class name only, never the message', () => {
    expect(errorSummary(new RangeError(PRIVATE))).toEqual({ kind: 'render', name: 'RangeError' })
    expect(JSON.stringify(errorSummary(new RangeError(PRIVATE)))).not.toContain('1234')
  })

  it('does not trust unusual error names or values that are not errors', () => {
    const odd = new Error('x')
    odd.name = 'Salary 1234.5 for alice@example.com'
    expect(errorSummary(odd).name).toBe('Error')
    expect(errorSummary('a thrown string')).toEqual({ kind: 'render', name: 'Error' })
    expect(errorSummary(undefined)).toEqual({ kind: 'render', name: 'Error' })
  })

  it('logs one safe line in production builds', () => {
    vi.stubEnv('DEV', false)
    const console = vi.spyOn(globalThis.console, 'error').mockImplementation(() => {})
    logError('chart boundary', new RangeError(PRIVATE))
    expect(console).toHaveBeenCalledTimes(1)
    expect(console).toHaveBeenCalledWith('[SpendWise] chart boundary: render error (RangeError)')
    expect(JSON.stringify(console.mock.calls)).not.toContain('1234')
  })

  it('adds the full error in development builds only', () => {
    vi.stubEnv('DEV', true)
    const console = vi.spyOn(globalThis.console, 'error').mockImplementation(() => {})
    const error = new TypeError('Failed to fetch dynamically imported module: /assets/x.js')
    logError('page boundary', error)
    expect(console.mock.calls).toEqual([['[SpendWise] page boundary: chunk error (TypeError)'], [error]])
  })
})

describe('reloadOnceForChunkError', () => {
  it('reloads once, then not again while the first reload has not helped', () => {
    const { env, reload } = environment()
    expect(reloadOnceForChunkError(env)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(env.store?.getItem(CHUNK_RELOAD_KEY)).not.toBeNull()

    // After the reload the chunk fails again: no second reload, so no loop.
    expect(reloadOnceForChunkError(env)).toBe(false)
    expect(reloadOnceForChunkError(env)).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('may reload again once a chunk has loaded in between', () => {
    const { env, reload } = environment()
    reloadOnceForChunkError(env)
    chunkLoaded(env.store)
    expect(reloadOnceForChunkError(env)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('never reloads while a dialog is open (it would lose what is being typed)', () => {
    const { env, reload } = environment({ hasOpenDialog: () => true })
    expect(reloadOnceForChunkError(env)).toBe(false)
    expect(reload).not.toHaveBeenCalled()
    expect(env.store?.getItem(CHUNK_RELOAD_KEY)).toBeNull() // still free for later
  })

  it('never reloads without storage to remember it by', () => {
    const { env, reload } = environment({ store: null })
    expect(reloadOnceForChunkError(env)).toBe(false)
    const failing = {
      getItem: () => {
        throw new Error('SecurityError')
      },
      setItem: () => {
        throw new Error('SecurityError')
      },
      removeItem: () => {
        throw new Error('SecurityError')
      },
    }
    const blocked = environment({ store: failing })
    expect(reloadOnceForChunkError(blocked.env)).toBe(false)
    expect(() => chunkLoaded(failing)).not.toThrow()
    expect(reload).not.toHaveBeenCalled()
    expect(blocked.reload).not.toHaveBeenCalled()
  })

  it('finds no storage outside a browser', () => {
    expect(tabStorage()).toBeNull()
  })
})

describe('retryableLoader', () => {
  it('passes a successful load through and reports it', async () => {
    const onLoaded = vi.fn()
    const loader = retryableLoader(() => Promise.resolve('chart'), onLoaded)
    await expect(loader.load()).resolves.toBe('chart')
    expect(onLoaded).toHaveBeenCalledTimes(1)
    expect(loader.retry()).toBe(false) // nothing failed: keep the loaded component
  })

  it('after a failure, allows exactly one new attempt, which can succeed', async () => {
    const onLoaded = vi.fn()
    const chunkError = new TypeError('Failed to fetch dynamically imported module: /assets/x.js')
    const load = vi.fn<() => Promise<string>>().mockRejectedValueOnce(chunkError).mockResolvedValueOnce('chart')
    const loader = retryableLoader(load, onLoaded)

    await expect(loader.load()).rejects.toBe(chunkError)
    expect(onLoaded).not.toHaveBeenCalled()
    expect(loader.retry()).toBe(true)
    expect(loader.retry()).toBe(false) // one new attempt per failure

    await expect(loader.load()).resolves.toBe('chart')
    expect(load).toHaveBeenCalledTimes(2)
    expect(onLoaded).toHaveBeenCalledTimes(1)
  })
})
