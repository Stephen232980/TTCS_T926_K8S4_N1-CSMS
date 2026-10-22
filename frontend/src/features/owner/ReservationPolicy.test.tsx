import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ReservationPolicy } from './ReservationPolicy'

afterEach(() => vi.unstubAllGlobals())
const response = (data: unknown) => ({ok:true,status:200,json:async()=>data})

it('loads and saves an integer fee with the current optimistic version', async () => {
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => response(options?.method === 'PUT' ? {fee_vnd:10000,version:4} : {fee_vnd:0,version:3}))
  vi.stubGlobal('fetch',fetch)
  render(<ReservationPolicy stationId="station-one" />)
  const input = screen.getByLabelText('Phí không đến (đ)')
  await waitFor(() => expect(input).toBeEnabled())
  await userEvent.clear(input)
  await userEvent.type(input,'10000')
  await userEvent.click(screen.getByRole('button',{name:'Lưu phí không đến'}))
  expect(await screen.findByRole('status')).toHaveTextContent('Mức phí mới chỉ áp dụng')
  const post = fetch.mock.calls.find(([,options]) => options?.method === 'PUT')!
  expect(JSON.parse(post[1].body)).toEqual({fee_vnd:10000,expected_version:3})
})

it('blocks saving until an ambiguous failed PUT has been reloaded', async () => {
  let gets = 0
  const fetch = vi.fn().mockImplementation(async (_url: string, options?: RequestInit) => {
    if(options?.method === 'PUT') throw new TypeError('network')
    return response(++gets === 1 ? {fee_vnd:0,version:0} : {fee_vnd:10000,version:1})
  })
  vi.stubGlobal('fetch',fetch)
  render(<ReservationPolicy stationId="station-one" />)
  const input = screen.getByLabelText('Phí không đến (đ)')
  await waitFor(() => expect(input).toBeEnabled())
  await userEvent.clear(input); await userEvent.type(input,'10000')
  await userEvent.click(screen.getByRole('button',{name:'Lưu phí không đến'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Chưa xác nhận')
  expect(screen.getByRole('button',{name:'Lưu phí không đến'})).toBeDisabled()
  await userEvent.click(screen.getByRole('button',{name:'Tải lại chính sách'}))
  await waitFor(() => expect(input).toHaveValue(10000))
  expect(screen.getByRole('button',{name:'Lưu phí không đến'})).toBeEnabled()
})
