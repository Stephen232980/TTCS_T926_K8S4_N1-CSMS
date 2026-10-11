import { afterEach, expect, it, vi } from 'vitest'
import { driverInvoiceApi } from './driverInvoiceApi'
afterEach(() => vi.unstubAllGlobals())
it('only reads invoice snapshots with the session cookie and abort signal', async () => {
  const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({status:'pending'})})
  vi.stubGlobal('fetch',fetch)
  const signal=new AbortController().signal
  await driverInvoiceApi.get(42,signal)
  expect(fetch).toHaveBeenCalledWith('/api/v1/driver/charging/sessions/42/invoice',{credentials:'include',signal})
})
it.each([403,404,401,500])('rejects HTTP %s instead of rendering amounts', async status => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status}))
  await expect(driverInvoiceApi.get(42)).rejects.toThrow()
})
