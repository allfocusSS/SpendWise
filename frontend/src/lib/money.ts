/**
 * Money helpers. The backend stores and returns every amount as an integer number of
 * tiyn (1 KZT = 100 tiyn). The frontend never does financial math; it only converts
 * between what the user types and tiyn, and formats tiyn for display.
 */

/** Must equal the backend's MAX_AMOUNT_CENTS (checked by a test against openapi.json). */
export const MAX_AMOUNT_TIYN = 1_000_000_000_000 // 10 000 000 000 KZT

/** Longest whole-tenge part we accept, derived from the maximum (11 digits). */
const MAX_WHOLE_DIGITS = String(MAX_AMOUNT_TIYN / 100).length

// Digits, optionally followed by a decimal separator and 1–2 digits. Signs, exponents
// and other characters are rejected.
const AMOUNT_PATTERN = /^(\d+)(?:\.(\d{1,2}))?$/

export type ParseResult = { ok: true; tiyn: number } | { ok: false; error: string }

/**
 * Convert user input in tenge (e.g. "2 500,50") to integer tiyn (250050).
 *
 * Works on the digit string directly, so no floating-point multiplication is involved.
 * Accepts spaces (including non-breaking) as thousands separators, "," or "." as the
 * decimal separator, an optional "₸", and at most 2 decimal places.
 */
export function parseKztToTiyn(input: string): ParseResult {
  const cleaned = input.replace(/[\s\u00a0\u202f₸]/g, '').replace(',', '.')
  if (cleaned === '') {
    return { ok: false, error: 'Enter an amount.' }
  }

  const match = AMOUNT_PATTERN.exec(cleaned)
  if (!match) {
    return { ok: false, error: 'Enter a positive amount with up to 2 decimals, e.g. 2500 or 2 500,50.' }
  }

  const whole = match[1].replace(/^0+(?=\d)/, '') // drop leading zeros, keep a single "0"
  const fraction = (match[2] ?? '').padEnd(2, '0')

  // Check the length before calling Number(), so huge inputs can never lose precision.
  if (whole.length > MAX_WHOLE_DIGITS) {
    return { ok: false, error: `Amount cannot exceed ${formatKzt(MAX_AMOUNT_TIYN)}.` }
  }

  // Both parts are short digit strings, so this is exact integer arithmetic.
  const tiyn = Number(whole) * 100 + Number(fraction)

  if (!Number.isSafeInteger(tiyn)) {
    return { ok: false, error: 'Amount is too large.' }
  }
  if (tiyn <= 0) {
    return { ok: false, error: 'Amount must be greater than zero.' }
  }
  if (tiyn > MAX_AMOUNT_TIYN) {
    return { ok: false, error: `Amount cannot exceed ${formatKzt(MAX_AMOUNT_TIYN)}.` }
  }
  return { ok: true, tiyn }
}

const wholeFormatter = new Intl.NumberFormat('ru-KZ', {
  style: 'currency',
  currency: 'KZT',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
})
const fractionFormatter = new Intl.NumberFormat('ru-KZ', {
  style: 'currency',
  currency: 'KZT',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * Format integer tiyn as tenge for display: 250000 → "2 500 ₸", 250050 → "2 500,50 ₸".
 * Whole amounts are shown without decimals. Negative values (e.g. balances) keep the sign.
 */
export function formatKzt(tiyn: number): string {
  if (!Number.isSafeInteger(tiyn)) {
    throw new RangeError(`formatKzt expects an integer number of tiyn, got ${tiyn}`)
  }
  // Display only: the division result is passed straight to Intl, never stored or summed.
  return tiyn % 100 === 0 ? wholeFormatter.format(tiyn / 100) : fractionFormatter.format(tiyn / 100)
}

/**
 * Turn tiyn back into an editable input string: 250050 → "2500.50", 250000 → "2500".
 * Pure string manipulation, used to prefill the edit form.
 */
export function tiynToInput(tiyn: number): string {
  if (!Number.isSafeInteger(tiyn) || tiyn < 0) {
    throw new RangeError(`tiynToInput expects a non-negative integer, got ${tiyn}`)
  }
  const digits = String(tiyn).padStart(3, '0')
  const whole = digits.slice(0, -2)
  const fraction = digits.slice(-2)
  return fraction === '00' ? whole : `${whole}.${fraction}`
}

const compactFormatter = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

/** Short label for chart axes: 150000000 tiyn → "1.5M ₸". Display only. */
export function formatKztCompact(tiyn: number): string {
  if (!Number.isSafeInteger(tiyn)) {
    throw new RangeError(`formatKztCompact expects an integer number of tiyn, got ${tiyn}`)
  }
  return `${compactFormatter.format(tiyn / 100)} ₸`
}
