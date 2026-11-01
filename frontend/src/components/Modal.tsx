import { useEffect, useId, useRef, type ReactNode } from 'react'

import { CloseIcon } from './icons'
import { Button, FormError } from './ui'

/**
 * Accessible modal built on the native <dialog> element: the browser handles focus
 * trapping, Escape to close and making the rest of the page inert.
 * Children are only rendered while open, so forms start fresh every time.
 */
export function Modal({ open, title, onClose, children }: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
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
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl bg-white p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      {open && (
        <div className="p-5 sm:p-6">
          <div className="mb-4 flex items-start justify-between gap-4">
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              {title}
            </h2>
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close dialog">
              <CloseIcon />
            </Button>
          </div>
          {children}
        </div>
      )}
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
        <div className="text-sm text-slate-700">{message}</div>
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
