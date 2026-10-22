import { PrivacyRequestReview } from './PrivacyRequestReview'

export function AdminPrivacyRetention() {
  return <>
    <header className="admin-heading"><div>
      <h1>Lưu trữ & quyền riêng tư</h1>
      <p>Duyệt yêu cầu ẩn danh tài khoản và theo dõi kết quả xử lý.</p>
    </div></header>
    <PrivacyRequestReview />
  </>
}
