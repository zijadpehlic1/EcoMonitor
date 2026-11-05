export function matchesDataset(data: {location: string; source_type: string; station_id: number | null} | null,
  city: string, source: string, station?: number): boolean {
  return !!data && data.location === city && data.source_type === source &&
    (source === 'modeled' ? data.station_id == null : data.station_id === station)
}
