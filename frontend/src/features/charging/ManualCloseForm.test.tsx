import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ManualCloseForm } from './ManualCloseForm'

const props = { sessionId: 42, latestMeter: '3500', startMeter: '1000', meterAt: '2026-10-02T01:10:00Z', onSubmit: vi.fn(), onCancel: vi.fn() }

describe('ManualCloseForm', () => {
  it('requires a reason and explicit confirmation, derives energy from saved meters', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<ManualCloseForm {...props} onSubmit={onSubmit} />)
    expect(screen.getByText('2,5 kWh')).toBeInTheDocument()
    expect(screen.getByText(/Trụ sẽ không nhận lệnh dừng sạc/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Xác nhận đóng phiên' })
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText('Lý do đóng tay'), '  Đã kiểm tra tại trụ  ')
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('checkbox'))
    await user.click(submit)
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Đã kiểm tra tại trụ')
  })

  it('keeps user input after conflict and allows cancel without changing the session', async () => {
    const onCancel = vi.fn()
    const user = userEvent.setup()
    render(<ManualCloseForm {...props} onCancel={onCancel} onSubmit={vi.fn().mockRejectedValue(new Error('Phiên đã kết thúc.'))} />)
    await user.type(screen.getByLabelText('Lý do đóng tay'), 'Kiểm tra')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Xác nhận đóng phiên' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Phiên đã kết thúc.')
    expect(screen.getByLabelText('Lý do đóng tay')).toHaveValue('Kiểm tra')
    await user.click(screen.getByRole('button', { name: 'Hủy' }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it.each([null, '500'])('blocks closure when latest energy is invalid: %s', async latestMeter => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ManualCloseForm {...props} latestMeter={latestMeter} onSubmit={onSubmit} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Hãy kiểm tra số đo')
    await user.type(screen.getByLabelText('Lý do đóng tay'), 'Kiểm tra')
    await user.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: 'Xác nhận đóng phiên' })).toBeDisabled()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
