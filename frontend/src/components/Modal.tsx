import { useEffect, useId, useRef, type ReactNode } from 'react'

import { CloseIcon } from './icons'
import { Button, FormError, IconButton } from './ui'

/**
 * Accessible modal built on the native <dialog> element: the browser handles focus
 * trapping, Escape to close and making the rest of the page inert.
 * Children are only rendered while open, so forms start fresh every time.
 */
export function Modal({ open, title, onClose, children, size = 'md' }: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  /** "sheet": right-side panel on desktop, bottom sheet on phones. */
  size?: 'md' | 'lg' | 'sheet'
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault() // let React state decide when to close
        onClose()
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose() // click on the backdrop
      }}
      className={
        size === 'sheet'
          ? 'mx-0 mt-auto mb-0 max-h-[92dvh] w-full max-w-none rounded-t-[var(--radius-card)] border-t border-line-strong bg-surface p-0 text-ink shadow-pop backdrop:bg-black/60 sm:my-0 sm:mr-0 sm:ml-auto sm:h-dvh sm:max-h-none sm:w-[480px] sm:rounded-none sm:border-t-0 sm:border-l'
          : `m-auto w-[calc(100%-2rem)] rounded-[var(--radius-card)] border border-line-strong bg-surface p-0 text-ink shadow-pop backdrop:bg-black/60 ${size === 'lg' ? 'max-w-xl' : 'max-w-md'}`
      }
    >
      {open &&
        (size === 'sheet' ? (
          <div className="flex h-full max-h-[92dvh] flex-col sm:max-h-none">
            <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
              <h2 id={titleId} className="text-xl font-semibold tracking-tight text-ink">
                {title}
              </h2>
              <IconButton label="Close dialog" onClick={onClose} className="-mr-1.5 size-8">
                <CloseIcon />
              </IconButton>
            </div>
            <div className="flex flex-1 flex-col overflow-y-auto px-5 pt-5 sm:px-6 sm:pt-6">{children}</div>
          </div>
        ) : (
          <div className="p-5 sm:p-6">
            <div className="mb-5 flex items-start justify-between gap-4">
              <h2 id={titleId} className="text-xl font-semibold tracking-tight text-ink">
                {title}
              </h2>
              <IconButton label="Close dialog" onClick={onClose} className="-mt-0.5 -mr-1.5 size-8">
                <CloseIcon />
              </IconButton>
            </div>
            {children}
          </div>
        ))}
    </dialog>
  )
}

export function ConfirmDialog({ open, title, message, confirmLabel, pending, error, onConfirm, onClose }: {
  open: boolean
  title: string
  message: ReactNode
  confirmLabel: string
  pending: boolean
  error?: string | null
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="text-sm leading-relaxed text-ink-muted">{message}</div>
        <FormError message={error} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={pending}>
            {pending ? 'Deleting…' : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
