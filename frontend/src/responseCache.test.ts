import { beforeEach, expect, it, vi } from 'vitest'
import { cachedResponse, clearResponseCache, invalidateCity, peekResponse } from './responseCache'
const store=new Map<string,string>()
beforeEach(()=>{
  store.clear();clearResponseCache()
  vi.stubGlobal('localStorage',{getItem:(key:string)=>store.get(key)??null,setItem:(key:string,value:string)=>store.set(key,value)})
})
it('coalesces duplicate requests and persists across a frontend restart',async()=>{
  const fetcher=vi.fn(async()=>({value:42}))
  await Promise.all([cachedResponse('/history?location=mostar',fetcher,60_000),cachedResponse('/history?location=mostar',fetcher,60_000)])
  expect(fetcher).toHaveBeenCalledTimes(1)
  clearResponseCache()
  expect(peekResponse('/history?location=mostar')).toEqual({value:42})
  await cachedResponse('/history?location=mostar',fetcher,60_000)
  expect(fetcher).toHaveBeenCalledTimes(1)
})
it('invalidates only the selected city and retains values after failure',async()=>{
  await cachedResponse('/history?location=mostar',async()=>42,60_000)
  await cachedResponse('/history?location=zenica',async()=>9,60_000)
  invalidateCity('mostar')
  const other=vi.fn(async()=>10)
  expect(await cachedResponse('/history?location=zenica',other,60_000)).toBe(9)
  expect(other).not.toHaveBeenCalled()
  await expect(cachedResponse('/history?location=mostar',async()=>{throw Error('offline')},60_000)).rejects.toThrow('offline')
  expect(peekResponse('/history?location=mostar')).toBe(42)
})
