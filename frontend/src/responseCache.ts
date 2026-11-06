type Entry = { value: unknown; saved: number }
const entries = new Map<string, Entry>()
const flights = new Map<string, Promise<unknown>>()
const prefix = 'ecomonitor:v3:'

export function peekResponse<T>(key: string): T | null {
  let entry = entries.get(key)
  if (!entry) {
    try {
      const raw = localStorage.getItem(prefix + key)
      if (raw) { entry = JSON.parse(raw); if (entry) entries.set(key, entry) }
    } catch { /* Storage may be unavailable or full; the database remains authoritative. */ }
  }
  return entry?.value as T ?? null
}

export async function cachedResponse<T>(key: string, fetcher: () => Promise<T>, ttl: number): Promise<T> {
  const value = peekResponse<T>(key)
  if (value !== null && Date.now() - entries.get(key)!.saved < ttl) return value
  const flight = flights.get(key)
  if (flight) return flight as Promise<T>
  const promise = fetcher().then(value => {
    const entry = { value, saved: Date.now() }
    entries.set(key, entry)
    if (entries.size > 100) entries.delete(entries.keys().next().value!)
    try {
      const raw = JSON.stringify(entry)
      // Keep large hourly series in memory; avoid exhausting browser storage.
      if (raw.length < 180_000) localStorage.setItem(prefix + key, raw)
    } catch { /* A quota failure must never hide successfully fetched data. */ }
    return value
  }).finally(() => flights.delete(key))
  flights.set(key, promise)
  return promise
}

export function invalidateCity(city: string) {
  for (const [key, entry] of entries) {
    if (new URLSearchParams(key.split('?')[1]).get('location') === city) {
      entry.saved = 0
      try { localStorage.setItem(prefix + key, JSON.stringify(entry)) } catch { /* optional persistence */ }
    }
  }
}

export function clearResponseCache() { entries.clear(); flights.clear() }
