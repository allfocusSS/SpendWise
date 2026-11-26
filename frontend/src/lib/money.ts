/**
 * Money helpers. The backend stores and returns every amount as an integer number of
 * tiyn (1 KZT = 100 tiyn). The frontend never does financial math; it only converts
 * between what the user types and tiyn, and formats tiyn for display.
 */

/** Must equal the backend's MAX_AMOUNT_CENTS (checked by a test against openapi.json). */
export const MAX_AMOUNT_TIYN = 1_000_000_000_000 // 10 000 000 000 KZT

/** Longest whole-tenge part we accept, derived from the maximum (11 digits). */
const MAX_WHOLE_DIGITS = String(MAX_AMOUNT_TIYN / 100).length

// Match formatting before removing separators. These spaces also match the backend's draft grammar.
const GROUP_SPACE = '[ \u00a0\u202f\u2009\u2007]'
const CURRENCY_EDGE = new RegExp(`^₸${GROUP_SPACE}?|${GROUP_SPACE}?₸$`)
const AMOUNT_PATTERN = new RegExp(`^([0-9]+|[0-9]{1,3}(?:${GROUP_SPACE}[0-9]{3})+)(?:[.,]([0-9]{1,2}))?$`)
const GROUP_SPACES = new RegExp(GROUP_SPACE, 'g')

export type ParseResult = { ok: true; tiyn: number } | { ok: false; error: string }

/**
 * Convert user input in tenge (e.g. "2 500,50") to integer tiyn (250050).
 *
 * Works on the digit string directly, so no floating-point multiplication is involved.
 * Accepts single spaces between exact thousands groups, one "," or "." with 1–2 decimal
 * digits, and at most one "₸" before or after the amount.
 */
export function parseKztToTiyn(input: string): ParseResult {
  const text = input.trim()
  if (text === '') {
    return { ok: false, error: 'Enter an amount.' }
  }

  const match = AMOUNT_PATTERN.exec(text.replace(CURRENCY_EDGE, ''))
  if (!match) {
    return { ok: false, error: 'Use up to two decimals, single spaces between thousands, and one optional ₸ before or after the amount. For example, 2 500,50 ₸.' }
  }

  const whole = match[1].replace(GROUP_SPACES, '').replace(/^0+(?=\d)/, '')
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
 * Digit groups and the currency sign are set off by narrow no-break spaces (U+202F), which keep
 * large figures compact and never break across lines.
 */
export function formatKzt(tiyn: number): string {
  if (!Number.isSafeInteger(tiyn)) {
    throw new RangeError(`formatKzt expects an integer number of tiyn, got ${tiyn}`)
  }
  // Display only: the division result is passed straight to Intl, never stored or summed.
  const text = tiyn % 100 === 0 ? wholeFormatter.format(tiyn / 100) : fractionFormatter.format(tiyn / 100)
  return text.replace(/\u00a0/g, '\u202f')
}

/**
 * Format with an explicit sign and a true minus: "+287 000 ₸", "−12 500 ₸", "0 ₸". For nets and
 * comparisons, where the sign is the point. Display only.
 */
export function formatSignedKzt(tiyn: number): string {
  return `${tiyn > 0 ? '+' : ''}${formatKzt(tiyn).replace(/^-/, '−')}`
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
