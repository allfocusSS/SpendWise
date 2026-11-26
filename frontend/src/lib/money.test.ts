import { describe, expect, it } from 'vitest'

import spec from '../../../openapi/openapi.json'
import { formatKzt, formatKztCompact, formatSignedKzt, MAX_AMOUNT_TIYN, parseKztToTiyn, tiynToInput } from './money'

// Intl uses non-breaking/narrow spaces as group separators; normalise them for readable asserts.
const plain = (s: string) => s.replace(/[\u00a0\u202f]/g, ' ')

function parsed(input: string): number | null {
  const result = parseKztToTiyn(input)
  return result.ok ? result.tiyn : null
}

describe('MAX_AMOUNT_TIYN', () => {
  it('matches the backend maximum in the OpenAPI spec', () => {
    const amount = spec.components.schemas.TransactionCreate.properties.amount_cents
    expect(amount.maximum).toBe(MAX_AMOUNT_TIYN)
    expect(amount.exclusiveMinimum).toBe(0)
  })

  it('is inside the JavaScript safe integer range', () => {
    expect(MAX_AMOUNT_TIYN).toBeLessThanOrEqual(Number.MAX_SAFE_INTEGER)
  })
})

describe('parseKztToTiyn', () => {
  it.each([
    ['2500', 250_000],
    ['2 500', 250_000],
    ['2\u00a0500,50', 250_050], // non-breaking space, comma decimal
    ['₸2\u202f500,50', 250_050],
    ['₸\u20092\u2009500.50', 250_050],
    ['2\u2007500,5\u2007₸', 250_050],
    ['10 000 000 000,00 ₸', MAX_AMOUNT_TIYN],
    ['2500.5', 250_050],
    ['19.99', 1_999], // 19.99 * 100 is 1998.9999999999998 in floating point
    ['0.29', 29], // 0.29 * 100 is 28.999999999999996 in floating point
    ['1.1', 110],
    ['0.01', 1],
    ['007', 700],
    ['  42 ₸ ', 4_200],
    ['10000000000', MAX_AMOUNT_TIYN], // exactly the maximum
  ])('parses %j as %d tiyn', (input, expected) => {
    expect(parsed(input)).toBe(expected)
  })

  it.each([
    ['', 'empty'],
    ['   ', 'whitespace'],
    ['0', 'zero'],
    ['0.00', 'zero with decimals'],
    ['-5', 'negative'],
    ['+5', 'explicit sign'],
    ['1.234', 'three decimals'],
    ['1.', 'trailing separator'],
    ['.5', 'missing whole part'],
    ['1e5', 'exponent'],
    ['abc', 'letters'],
    ['2,500.50', 'mixed separators'],
    ['12 34', 'short thousands group'],
    ['1234 567', 'oversized first group'],
    ['1 234 56', 'short final group'],
    ['1  234', 'repeated spacing'],
    ['1\t234', 'tab between digits'],
    ['1\n234', 'newline between digits'],
    ['1\n₸', 'newline before the currency symbol'],
    ['1, 23', 'space after decimal separator'],
    ['1 .23', 'space before decimal separator'],
    ['1,234', 'comma could mean thousands'],
    ['1.234.567', 'dot thousands groups'],
    ['1,234,56', 'repeated decimal separator'],
    ['₸1₸2', 'embedded currency symbol'],
    ['1₸23', 'symbol between digits'],
    ['₸123₸', 'currency symbol on both edges'],
    ['123 ₸₸', 'duplicated currency symbol'],
    ['₸  123', 'repeated space after symbol'],
    ['₸', 'missing amount'],
    ['123 KZT', 'unsupported currency suffix'],
    ['$123', 'foreign currency'],
    ['１２３', 'fullwidth digits'],
    ['1\u200b234', 'zero-width separator'],
    ['Infinity', 'Infinity'],
    ['NaN', 'NaN'],
  ])('rejects %j (%s)', (input) => {
    expect(parseKztToTiyn(input).ok).toBe(false)
  })

  describe('upper bounds', () => {
    it.each([
      ['10000000000.01', 'maximum + 1 tiyn'],
      ['10000000001', 'maximum + 1 KZT'],
      ['99999999999', '11 digits above the maximum'],
      ['90071992547409.91', 'exactly Number.MAX_SAFE_INTEGER tiyn'],
      ['90071992547409.92', 'Number.MAX_SAFE_INTEGER + 1 tiyn'],
      ['123456789012345678901', 'far beyond the safe integer range'],
    ])('rejects %j (%s)', (input) => {
      const result = parseKztToTiyn(input)
      expect(result.ok).toBe(false)
      expect(result.ok ? '' : result.error).toMatch(/cannot exceed|too large/)
    })
  })

  it('returns a helpful message for each failure kind', () => {
    expect(parseKztToTiyn('')).toEqual({ ok: false, error: 'Enter an amount.' })
    expect(parseKztToTiyn('0')).toEqual({ ok: false, error: 'Amount must be greater than zero.' })
    expect(parseKztToTiyn('abc').ok).toBe(false)
  })

  it('accepts copied positive KZT display values exactly', () => {
    for (const tiyn of [1, 99, 1_999, 250_050, 123_456_700, MAX_AMOUNT_TIYN]) {
      expect(parsed(formatKzt(tiyn))).toBe(tiyn)
    }
  })
})

describe('formatKzt', () => {
  it.each([
    [250_000, '2 500 ₸'],
    [250_050, '2 500,50 ₸'],
    [1, '0,01 ₸'],
    [0, '0 ₸'],
    [-123_455, '-1 234,55 ₸'],
    [-500_00, '-500 ₸'],
    [MAX_AMOUNT_TIYN, '10 000 000 000 ₸'],
  ])('formats %d tiyn as %j', (tiyn, expected) => {
    expect(plain(formatKzt(tiyn))).toBe(expected)
  })

  it('separates digit groups and the sign with narrow no-break spaces', () => {
    expect(formatKzt(123_456_700)).toBe('1\u202f234\u202f567\u202f₸')
    expect(formatKzt(123_456_700)).not.toMatch(/[ \u00a0]/)
  })

  it.each([1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])(
    'throws for non-integer or unsafe input %d',
    (value) => {
      expect(() => formatKzt(value)).toThrow(RangeError)
    },
  )
})

describe('formatSignedKzt', () => {
  it.each([
    [28_700_000, '+287 000 ₸'],
    [-1_250_000, '−12 500 ₸'], // a true minus sign, not a hyphen
    [-123_455, '−1 234,55 ₸'],
    [0, '0 ₸'], // zero has no sign
  ])('formats %d tiyn as %j', (tiyn, expected) => {
    expect(plain(formatSignedKzt(tiyn))).toBe(expected)
  })
})

describe('tiynToInput', () => {
  it.each([
    [250_000, '2500'],
    [250_050, '2500.50'],
    [1, '0.01'],
    [99, '0.99'],
    [100, '1'],
    [MAX_AMOUNT_TIYN, '10000000000'],
  ])('converts %d tiyn to %j', (tiyn, expected) => {
    expect(tiynToInput(tiyn)).toBe(expected)
  })

  it('round-trips through parseKztToTiyn', () => {
    for (const tiyn of [1, 99, 100, 1_999, 250_050, MAX_AMOUNT_TIYN]) {
      expect(parsed(tiynToInput(tiyn))).toBe(tiyn)
    }
  })

  it('rejects negative and non-integer values', () => {
    expect(() => tiynToInput(-1)).toThrow(RangeError)
    expect(() => tiynToInput(1.5)).toThrow(RangeError)
  })
})

describe('formatKztCompact', () => {
  it.each([
    [0, '0 ₸'],
    [50_000, '500 ₸'],
    [150_000_00, '150K ₸'],
    [1_500_000_00, '1.5M ₸'],
    [-2_000_000_00, '-2M ₸'],
  ])('formats %d tiyn as %j', (tiyn, expected) => {
    expect(formatKztCompact(tiyn)).toBe(expected)
  })
})
