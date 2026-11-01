/**
 * React Query hooks: the only place pages get server data from.
 * Mutations invalidate every query whose numbers could change, so totals never go stale.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  api,
  type BreakdownQuery,
  type CategoryCreate,
  type CategoryUpdate,
  type SummaryQuery,
  type TransactionCreate,
  type TransactionQuery,
  type TransactionType,
  type TrendQuery,
} from './client'

export const queryKeys = {
  categories: (type?: TransactionType) => ['categories', type ?? 'all'] as const,
  transactions: (query: TransactionQuery) => ['transactions', query] as const,
  summary: (query: SummaryQuery) => ['analytics', 'summary', query] as const,
  breakdown: (query: BreakdownQuery) => ['analytics', 'by-category', query] as const,
  trend: (query: TrendQuery) => ['analytics', 'monthly-trend', query] as const,
}

// --- Queries -----------------------------------------------------------------

export function useCategories(type?: TransactionType) {
  return useQuery({ queryKey: queryKeys.categories(type), queryFn: () => api.listCategories(type) })
}

export function useTransactions(query: TransactionQuery) {
  return useQuery({
    queryKey: queryKeys.transactions(query),
    queryFn: () => api.listTransactions(query),
    placeholderData: keepPreviousData, // keep the old page visible while the next one loads
  })
}

export function useSummary(query: SummaryQuery = {}) {
  return useQuery({ queryKey: queryKeys.summary(query), queryFn: () => api.getSummary(query) })
}

export function useCategoryBreakdown(query: BreakdownQuery) {
  return useQuery({
    queryKey: queryKeys.breakdown(query),
    queryFn: () => api.getCategoryBreakdown(query),
  })
}

export function useMonthlyTrend(query: TrendQuery) {
  return useQuery({ queryKey: queryKeys.trend(query), queryFn: () => api.getMonthlyTrend(query) })
}

// --- Mutations ---------------------------------------------------------------

function useInvalidate() {
  const client = useQueryClient()
  return (...prefixes: string[]) =>
    Promise.all(prefixes.map((prefix) => client.invalidateQueries({ queryKey: [prefix] })))
}

export function useSaveTransaction() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: TransactionCreate }) =>
      id === undefined ? api.createTransaction(body) : api.updateTransaction(id, body),
    onSuccess: () => invalidate('transactions', 'analytics'),
  })
}

export function useDeleteTransaction() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) => api.deleteTransaction(id),
    onSuccess: () => invalidate('transactions', 'analytics'),
  })
}

// Transactions embed their category (name, colour), so category changes refresh them too.
export function useCreateCategory() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: CategoryCreate) => api.createCategory(body),
    onSuccess: () => invalidate('categories'),
  })
}

export function useUpdateCategory() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: CategoryUpdate }) => api.updateCategory(id, body),
    onSuccess: () => invalidate('categories', 'transactions', 'analytics'),
  })
}

export function useDeleteCategory() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) => api.deleteCategory(id),
    onSuccess: () => invalidate('categories', 'transactions', 'analytics'),
  })
}
