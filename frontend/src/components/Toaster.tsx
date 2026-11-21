import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { ToastContext } from '../lib/toast'
import { CheckIcon } from './icons'

/** How long a confirmation stays on screen. */
const TOAST_MS = 4500

/**
 * Success confirmations for saves and deletes. One polite live region (announced without moving
 * focus); a newer message replaces the older one. The toast never takes clicks, so it can't cover
 * a control the user is reaching for; it disappears on its own.
 */
export function Toaster({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ id: number; message: string } | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const show = useCallback((message: string) => {
    window.clearTimeout(timer.current)
    setToast((current) => ({ id: (current?.id ?? 0) + 1, message }))
    timer.current = window.setTimeout(() => setToast(null), TOAST_MS)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-4 bottom-[92px] z-50 flex justify-center lg:inset-x-auto lg:right-6 lg:bottom-6"
      >
        {toast ? (
          <p key={toast.id} className="flex items-center gap-3 rounded-xl bg-surface-selected py-2.5 pr-4 pl-2.5 text-sm font-medium text-ink shadow-pop">
            <span className="grid size-7 place-items-center rounded-full bg-income-soft text-income" aria-hidden="true">
              <CheckIcon className="size-4" strokeWidth={2.4} />
            </span>
            {toast.message}
          </p>
        ) : null}
      </div>
    </ToastContext.Provider>
  )
}
