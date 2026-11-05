import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ProvenancePanel } from './components/ProvenancePanel'
import { matchesDataset } from './datasetIdentity'
import type { SensorStation, DashboardData } from './types'

const stations: SensorStation[] = [
  {id:1, location:'mostar',name:'Mostar',provider:'FHMZ',measurement_count:123,source_url:'https://zrak.fhmzbih.gov.ba',attribution:'FHMZ',latitude:43,longitude:17,first_measurement_at:null,last_measurement_at:'2026-11-05T12:00:00Z',validation_counts:{unvalidated:120,provider_flagged:3}},
  {id:2, location:'sarajevo',name:'Sarajevo',provider:'OpenAQ / AirNow',measurement_count:45,source_url:'https://explore.openaq.org',attribution:'OpenAQ',latitude:43,longitude:18,first_measurement_at:null,last_measurement_at:null,validation_counts:{unvalidated:45}},
]
const dashboard={location:{slug:'mostar',name:'Mostar',latitude:43,longitude:17},source:{name:'Open-Meteo / CAMS',url:'https://open-meteo.com'},sync:{records_stored:9876}} as DashboardData
describe('provenance selection',()=>{
  it('uses station-specific counts and validation, independent of CAMS cards',()=>{
    const html=renderToStaticMarkup(<ProvenancePanel city="mostar" source="sensor" stationId={1} stations={stations} dashboard={dashboard}/> )
    expect(html).toContain('FHMZ'); expect(html).toContain('123'); expect(html).toContain('automatski, nevalidirani: 120')
    expect(html).not.toContain('Nisu stvarna mjerenja');expect(html).not.toContain('9.876')
    expect(html).toContain('meteorološki panel koriste modelirane Open-Meteo')
  })
  it('switches provider when city and station change; rejects a wrong-city station',()=>{
    const html=renderToStaticMarkup(<ProvenancePanel city="sarajevo" source="sensor" stationId={2} stations={stations} dashboard={dashboard}/> )
    expect(html).toContain('OpenAQ / AirNow');expect(html).not.toContain('FHMZ')
    const wrong=renderToStaticMarkup(<ProvenancePanel city="sarajevo" source="sensor" stationId={1} stations={stations} dashboard={dashboard}/> )
    expect(wrong).toContain('Nije odabrana');expect(wrong).not.toContain('123')
  })
  it('keeps CAMS metadata when modeled source is selected',()=>{
    const html=renderToStaticMarkup(<ProvenancePanel city="mostar" source="modeled" stationId={1} stations={stations} dashboard={dashboard}/> )
    expect(html).toContain('Nisu stvarna mjerenja');expect(html).toContain('9.876');expect(html).not.toContain('FHMZ')
  })
  it('rejects stale asynchronous results from another city, source or station',()=>{
    const data={location:'mostar',source_type:'sensor',station_id:1}
    expect(matchesDataset(data,'mostar','sensor',1)).toBe(true)
    expect(matchesDataset(data,'sarajevo','sensor',1)).toBe(false)
    expect(matchesDataset(data,'mostar','modeled')).toBe(false)
    expect(matchesDataset(data,'mostar','sensor',2)).toBe(false)
  })
  it('labels provider-returned grid coordinates separately from requested coordinates',()=>{
    const grid={...dashboard,source:{...dashboard.source,grid_latitude:'43.3',grid_longitude:'17.9'}}
    const html=renderToStaticMarkup(<ProvenancePanel city="mostar" source="modeled" stations={stations} dashboard={grid}/>)
    expect(html).toContain('CAMS mrežna ćelija');expect(html).toContain('43,300')
  })
})
