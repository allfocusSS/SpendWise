/**
 * Centralised, typed access to the SpendWise API.
 *
 * All request/response types come from `schema.d.ts`, which is generated from the backend's
 * OpenAPI spec (`npm run generate:api`). Never edit those types by hand.
 */
import type { components, paths } from './schema'

type Schemas = components['schemas']

export type Category = Schemas['CategoryRead']
export type CategoryCreate = Schemas['CategoryCreate']
export type CategoryUpdate = Schemas['CategoryUpdate']
export type Transaction = Schemas['TransactionRead']
export type TransactionCreate = Schemas['TransactionCreate']
export type TransactionUpdate = Schemas['TransactionUpdate']
export type TransactionList = Schemas['TransactionList']
export type TransactionType = Schemas['TransactionType']
export type Summary = Schemas['Summary']
export type CategoryBreakdown = Schemas['CategoryBreakdown']
export type MonthlyTrend = Schemas['MonthlyTrend']

type QueryOf<P extends keyof paths> = NonNullable<
  paths[P] extends { get: { parameters: { query?: infer Q } } } ? Q : never
>
export type TransactionQuery = QueryOf<'/api/transactions'>
export type SummaryQuery = QueryOf<'/api/analytics/summary'>
export type BreakdownQuery = QueryOf<'/api/analytics/by-category'>
export type TrendQuery = QueryOf<'/api/analytics/monthly-trend'>

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * One error type for every failure the UI has to show.
 *
 * - `message`: a sentence safe to show to the user.
 * - `fieldErrors`: per-field messages from FastAPI validation errors (422 with a list).
 * - `status`: HTTP status, or 0 when the server could not be reached.
 */
export class ApiError extends Error {
  readonly status: number
  readonly fieldErrors: Record<string, string>

  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

type ValidationIssue = Schemas['ValidationError']

function isValidationIssue(value: unknown): value is ValidationIssue {
  return (
    typeof value === 'object' &&
    value !== null &&
    Array.isArray((value as ValidationIssue).loc) &&
    typeof (value as ValidationIssue).msg === 'string'
  )
}

/**
 * Turn an error response body into an ApiError.
 *
 * The backend returns two shapes:
 *   - business-rule errors (404/409/422): { "detail": "Category is used by 2 transaction(s)…" }
 *   - FastAPI validation errors (422):    { "detail": [{ "loc": ["body", "amount_cents"], "msg": "…" }] }
 */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined

  if (typeof detail === 'string' && detail.trim() !== '') {
    return new ApiError(status, detail)
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const fieldErrors: Record<string, string> = {}
    const general: string[] = []
    for (const issue of detail) {
      if (!isValidationIssue(issue)) continue
      // loc looks like ["body", "amount_cents"] or ["query", "limit"]; ["body"] means the whole body.
      const field = issue.loc.length > 1 ? String(issue.loc[issue.loc.length - 1]) : null
      const msg = issue.msg.replace(/^Value error, /, '')
      if (field && !(field in fieldErrors)) fieldErrors[field] = msg
      else if (!field) general.push(msg)
    }
    const message = general[0] ?? 'Some fields are invalid. Please check the form.'
    return new ApiError(status, message, fieldErrors)
  }

  return new ApiError(status, defaultMessage(status))
}

function defaultMessage(status: number): string {
  if (status === 404) return 'Not found.'
  if (status >= 500) return 'The server had a problem. Please try again.'
  return `Request failed (HTTP ${status}).`
}

// ---------------------------------------------------------------------------
// Low-level request helper
// ---------------------------------------------------------------------------

type QueryValue = string | number | boolean | null | undefined

export function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Record<string, QueryValue> } = {},
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}${buildQuery(options.query)}`, {
      method: options.method ?? 'GET',
      headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, "Can't reach the SpendWise server. Check that the backend is running.")
  }

  if (response.status === 204) {
    return undefined as T
  }

  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw toApiError(response.status, body)
  }
  return body as T
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export const api = {
  listCategories: (type?: TransactionType) =>
    request<Category[]>('/categories', { query: { type } }),
  createCategory: (body: CategoryCreate) =>
    request<Category>('/categories', { method: 'POST', body }),
  updateCategory: (id: number, body: CategoryUpdate) =>
    request<Category>(`/categories/${id}`, { method: 'PATCH', body }),
  deleteCategory: (id: number) => request<void>(`/categories/${id}`, { method: 'DELETE' }),

  listTransactions: (query: TransactionQuery = {}) =>
    request<TransactionList>('/transactions', { query }),
  createTransaction: (body: TransactionCreate) =>
    request<Transaction>('/transactions', { method: 'POST', body }),
  updateTransaction: (id: number, body: TransactionUpdate) =>
    request<Transaction>(`/transactions/${id}`, { method: 'PUT', body }),
  deleteTransaction: (id: number) => request<void>(`/transactions/${id}`, { method: 'DELETE' }),

  getSummary: (query: SummaryQuery = {}) =>
    request<Summary>('/analytics/summary', { query }),
  getCategoryBreakdown: (query: BreakdownQuery = {}) =>
    request<CategoryBreakdown>('/analytics/by-category', { query }),
  getMonthlyTrend: (query: TrendQuery = {}) =>
    request<MonthlyTrend>('/analytics/monthly-trend', { query }),
}
