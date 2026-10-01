import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RoleHomePage } from './RoleHomePage'

describe('RoleHomePage', () => {
  it.each([
    ['driver', 'Khu vực tài xế', 'Chưa có phiên sạc để theo dõi'],
    ['accountant', 'Khu vực kế toán', 'Chưa có dữ liệu đối soát'],
  ])('shows the %s scope without station actions', (role, title, state) => {
    render(<RoleHomePage role={role} />)

    expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: state })).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText('Tạo trạm')).not.toBeInTheDocument()
  })

  it('denies an unknown role by default', () => {
    render(<RoleHomePage role="unknown" />)

    expect(
      screen.getByText('Vai trò hiện tại chưa được cấp quyền sử dụng chức năng nào.'),
    ).toBeInTheDocument()
  })
})
