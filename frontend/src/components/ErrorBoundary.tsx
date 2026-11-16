import { Component, type ReactNode } from 'react'

import { errorKind, logError, reloadOnceForChunkError, type ErrorKind } from '../lib/recovery'
import { AlertIcon, RefreshIcon } from './icons'
import { Button } from './ui'

export type FallbackProps = {
  kind: ErrorKind
  /** Render the children again (after `onRetry` has run). */
  retry: () => void
  retrying: boolean
}

type Props = {
  /** Where the boundary sits, for the log line ("page", "chart", …). */
  name: string
  fallback: (props: FallbackProps) => ReactNode
  /** Runs before the children render again: fetch fresh data, load a chunk again. */
  onRetry?: () => unknown
  children: ReactNode
}

type State = { failed: boolean; kind: ErrorKind; retrying: boolean }

/**
 * Catches an error thrown while rendering its children and shows `fallback` in their place, so one
 * failing part never takes the rest of the app down. A chunk error also reloads the page once (see
 * lib/recovery.ts). Errors in event handlers and requests are not render errors: the pages show
 * those themselves.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, kind: 'render', retrying: false }

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { failed: true, kind: errorKind(error) }
  }

  componentDidCatch(error: unknown) {
    logError(`${this.props.name} boundary`, error)
    if (errorKind(error) === 'chunk') reloadOnceForChunkError()
  }

  retry = async () => {
    this.setState({ retrying: true })
    try {
      await this.props.onRetry?.()
    } finally {
      this.setState({ failed: false, retrying: false })
    }
  }

  render() {
    const { failed, kind, retrying } = this.state
    if (!failed) return this.props.children
    return this.props.fallback({ kind, retry: this.retry, retrying })
  }
}

function reloadPage() {
  window.location.reload()
}

const COPY = {
  chunk: {
    detail: 'SpendWise may have been updated since you opened it. Reloading the page gets the latest version.',
  },
  render: {
    detail: 'Something went wrong while showing it. Your saved data isn’t affected.',
  },
}

function RetryButton({ retry, retrying, variant = 'secondary' }: Pick<FallbackProps, 'retry' | 'retrying'> & { variant?: 'primary' | 'secondary' }) {
  return (
    <Button size="sm" variant={variant} onClick={retry} disabled={retrying}>
      <RefreshIcon className="size-3.5" />
      {retrying ? 'Trying again…' : 'Try again'}
    </Button>
  )
}

/** In place of one chart, at the chart's height, so the rest of the card keeps its layout. */
export function ChartErrorFallback({ kind, retry, retrying, height }: FallbackProps & { height: string }) {
  return (
    <div role="alert" className={`flex items-center justify-center ${height}`}>
      <div className="flex max-w-xs flex-col items-center gap-1 px-4 text-center">
        <AlertIcon className="mb-1 size-5 text-ink-subtle" />
        <p className="text-label font-medium text-ink">
          {kind === 'chunk' ? 'This chart couldn’t load' : 'This chart couldn’t be shown'}
        </p>
        <p className="text-label text-ink-subtle">
          {kind === 'chunk' ? COPY.chunk.detail : 'The rest of the page still works.'}
        </p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <RetryButton retry={retry} retrying={retrying} />
          {kind === 'chunk' && (
            <Button size="sm" variant="ghost" onClick={reloadPage}>
              Reload page
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/** In place of a page; the header and navigation around it keep working. */
export function PageErrorFallback({ kind, retry, retrying }: FallbackProps) {
  return (
    <div role="alert" className="mx-auto mt-10 flex max-w-md flex-col items-center gap-2 text-center">
      <AlertIcon className="mb-1 size-6 text-ink-subtle" />
      <h1 className="text-heading text-ink">{kind === 'chunk' ? 'This page couldn’t load' : 'Something went wrong on this page'}</h1>
      <p className="text-sm text-ink-muted">{COPY[kind].detail}</p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <RetryButton retry={retry} retrying={retrying} variant="primary" />
        <Button size="sm" variant="secondary" onClick={reloadPage}>
          Reload page
        </Button>
      </div>
    </div>
  )
}

/** In place of the add/edit transaction form; the dialog can still be closed. */
export function DialogErrorFallback({ kind, retry, retrying, onClose }: FallbackProps & { onClose: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 py-8 text-center">
      <AlertIcon className="mb-1 size-5 text-ink-subtle" />
      <p className="text-label font-medium text-ink">{kind === 'chunk' ? 'This form couldn’t load' : 'This form couldn’t be shown'}</p>
      <p className="max-w-xs text-label text-ink-subtle">{COPY[kind].detail}</p>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        <RetryButton retry={retry} retrying={retrying} />
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  )
}

/** Last resort, outside the router and data layer: only a reload is safe here. */
export function AppErrorFallback() {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div role="alert" className="flex max-w-sm flex-col items-center gap-2 text-center">
        <AlertIcon className="mb-1 size-6 text-ink-subtle" />
        <h1 className="text-heading text-ink">SpendWise ran into a problem</h1>
        <p className="text-sm text-ink-muted">Reload the page to continue. Your saved data isn’t affected.</p>
        <Button className="mt-4" onClick={reloadPage}>
          Reload page
        </Button>
      </div>
    </div>
  )
}
