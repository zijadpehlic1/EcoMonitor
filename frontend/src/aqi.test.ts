import { describe, expect, it } from 'vitest'
import { aqiBand } from './aqi'

describe('European AQI bands', () => {
  it.each([
    [0, 'Dobar'],
    [20, 'Dobar'],
    [20.1, 'Prihvatljiv'],
    [40, 'Prihvatljiv'],
    [40.1, 'Umjeren'],
    [60, 'Umjeren'],
    [60.1, 'Loš'],
    [80, 'Loš'],
    [80.1, 'Vrlo loš'],
    [100, 'Vrlo loš'],
    [100.1, 'Izuzetno loš'],
  ])('classifies %s as %s', (value, expected) => {
    expect(aqiBand(value).label).toBe(expected)
  })

  it('handles missing values explicitly', () => {
    expect(aqiBand(null).label).toBe('Nedostupno')
  })
})

