import { createContext, useContext } from 'react'

/** Confirm a completed action ("Expense added"). Shown briefly by the Layout's Toaster. */
export type ShowToast = (message: string) => void

export const ToastContext = createContext<ShowToast>(() => {})

/** Outside the Layout (sign-in pages) toasts are a no-op. */
export function useToast(): ShowToast {
  return useContext(ToastContext)
}
