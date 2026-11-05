import { describe, expect, it } from 'vitest'
import { formatDateTime, formatNumber } from './locale'
import { aqiBand } from './aqi'

describe('audit regression checks', () => {
  it('uses Sarajevo timezone independently of the browser timezone', () => {
    expect(formatDateTime('2026-01-01T23:30:00Z')).toContain('00:30')
    expect(formatDateTime('2026-07-01T22:30:00Z')).toContain('00:30')
    expect(formatNumber(12.5)).toBe('12,5')
  })
  it.each([NaN, Infinity, -1])('does not classify invalid AQI %s as healthy', value => {
    expect(aqiBand(value).label).toBe('Nedostupno')
  })
})
