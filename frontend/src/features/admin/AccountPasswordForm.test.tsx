import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,expect,it,vi} from 'vitest'
import {AccountPasswordForm} from './AccountPasswordForm'
import type {Account} from './adminApi'
const account:Account={id:'target',email:'target@example.com',roles:['driver'],status:'active',created_at:'2026-10-12T00:00:00Z',updated_at:'2026-10-12T01:00:00Z'}
afterEach(()=>vi.restoreAllMocks())
it('explains password requirements and toggles both inputs without submitting',async()=>{
 const fetcher=vi.spyOn(globalThis,'fetch');const user=userEvent.setup();render(<AccountPasswordForm account={account} self={false} onSaved={vi.fn()} onCancel={vi.fn()} onConflict={vi.fn()}/>);
 expect(screen.getByText(/Mật khẩu cần từ 12 đến 1024 ký tự/)).toBeInTheDocument();await user.click(screen.getByRole('button',{name:'Hiện mật khẩu'}));expect(screen.getByLabelText('Mật khẩu mới')).toHaveAttribute('type','text');expect(screen.getByLabelText('Nhập lại mật khẩu mới')).toHaveAttribute('type','text');await user.click(screen.getByRole('button',{name:'Ẩn mật khẩu'}));expect(screen.getByLabelText('Mật khẩu mới')).toHaveAttribute('type','password');expect(fetcher).not.toHaveBeenCalled()
})
async function fill(password='New-test-only-2026!'){
 const user=userEvent.setup();await user.type(screen.getByLabelText('Mật khẩu mới'),password);await user.type(screen.getByLabelText('Nhập lại mật khẩu mới'),password);await user.click(screen.getByRole('button',{name:'Xác nhận'}));return user
}
it('confirms the selected account, posts once and never renders the password in review',async()=>{
 const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify(account)))
 const saved=vi.fn();render(<AccountPasswordForm account={account} self={false} onSaved={saved} onCancel={vi.fn()} onConflict={vi.fn()}/>);
 const user=await fill();expect(screen.getByText('target@example.com')).toBeInTheDocument();expect(screen.queryByText('New-test-only-2026!')).toBeNull();expect(fetcher).not.toHaveBeenCalled()
 await user.dblClick(screen.getByRole('button',{name:'Xác nhận đổi mật khẩu'}));await waitFor(()=>expect(saved).toHaveBeenCalledTimes(1));expect(fetcher).toHaveBeenCalledTimes(1)
 const [path,options]=fetcher.mock.calls[0];expect(path).toBe('/api/v1/admin/accounts/target/password');expect(JSON.parse(String(options?.body))).toEqual({expected_updated_at:account.updated_at,password:'New-test-only-2026!',confirm_password:'New-test-only-2026!'})
})
it('rejects mismatching confirmation before any request',async()=>{
 const fetcher=vi.spyOn(globalThis,'fetch');const user=userEvent.setup();render(<AccountPasswordForm account={account} self={false} onSaved={vi.fn()} onCancel={vi.fn()} onConflict={vi.fn()}/>);
 await user.type(screen.getByLabelText('Mật khẩu mới'),'New-test-only-2026!');await user.type(screen.getByLabelText('Nhập lại mật khẩu mới'),'Different-test-only-2026!');await user.click(screen.getByRole('button',{name:'Xác nhận'}));expect(await screen.findByRole('alert')).toHaveTextContent('không khớp');expect(fetcher).not.toHaveBeenCalled()
})
it('shows server conflict and clears password inputs',async()=>{
 vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({error:{code:'resource_conflict',message:'Tài khoản đã thay đổi',fields:[]}}),{status:409}));const conflict=vi.fn();render(<AccountPasswordForm account={account} self={false} onSaved={vi.fn()} onCancel={vi.fn()} onConflict={conflict}/>);
 const user=await fill();await user.click(screen.getByRole('button',{name:'Xác nhận đổi mật khẩu'}));await waitFor(()=>expect(conflict).toHaveBeenCalledTimes(1));expect(screen.getByLabelText('Mật khẩu mới')).toHaveValue('');expect(screen.getByLabelText('Nhập lại mật khẩu mới')).toHaveValue('')
})
it('warns that resetting the current admin ends their login session',async()=>{
 render(<AccountPasswordForm account={account} self onSaved={vi.fn()} onCancel={vi.fn()} onConflict={vi.fn()}/>);await fill();expect(screen.getByText(/Bạn đang đổi mật khẩu của mình/)).toBeInTheDocument()
})
