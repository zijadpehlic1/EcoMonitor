export type AqiBand = {
  label: 'Nedostupno' | 'Dobar' | 'Prihvatljiv' | 'Umjeren' | 'Loš' | 'Vrlo loš' | 'Izuzetno loš'
  color: string
  text: string
}

/** Evropske AQI kategorije koje je EEA revidirala 2024. godine, a vraća ih Open-Meteo. */
export function aqiBand(value: number | null | undefined): AqiBand {
  if (value == null || !Number.isFinite(value) || value < 0) return { label: 'Nedostupno', color: '#94a3b8', text: 'Trenutna AQI vrijednost nije dostupna.' }
  if (value <= 20) return { label: 'Dobar', color: '#51a56d', text: 'Kvalitet zraka je dobar. Uobičajene aktivnosti na otvorenom su primjerene.' }
  if (value <= 40) return { label: 'Prihvatljiv', color: '#91bd54', text: 'Kvalitet zraka je uglavnom prihvatljiv.' }
  if (value <= 60) return { label: 'Umjeren', color: '#e0b444', text: 'Osjetljive osobe mogu razmotriti smanjenje dužeg fizičkog napora.' }
  if (value <= 80) return { label: 'Loš', color: '#e98943', text: 'Razmotrite ograničavanje dužih aktivnosti na otvorenom, naročito ako ste osjetljivi.' }
  if (value <= 100) return { label: 'Vrlo loš', color: '#d95854', text: 'Smanjite duže aktivnosti na otvorenom i pratite službene lokalne preporuke.' }
  return { label: 'Izuzetno loš', color: '#8b455f', text: 'Svedite naporne aktivnosti na otvorenom na minimum i pratite službene lokalne preporuke.' }
}

