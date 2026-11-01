import { createContext, useContext } from 'react'

import type { Transaction, TransactionType } from '../api/client'

/** Open the shared add/edit transaction dialog (rendered once by the Layout). */
export type OpenTransactionDialog = (options?: { transaction?: Transaction | null; type?: TransactionType }) => void

export const TransactionDialogContext = createContext<OpenTransactionDialog | null>(null)

export function useTransactionDialog(): OpenTransactionDialog {
  const open = useContext(TransactionDialogContext)
  if (!open) throw new Error('useTransactionDialog must be used inside <Layout>')
  return open
}
