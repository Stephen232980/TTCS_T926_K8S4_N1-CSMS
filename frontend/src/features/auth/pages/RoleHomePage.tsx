import { Icon, type IconName } from '../../../components/icons/Icon'

interface RoleHomePageProps {
  role: string
}

const roleContent: Record<
  string,
  { title: string; heading: string; description: string; icon: IconName }
> = {
  driver: {
    title: 'Khu vực tài xế',
    heading: 'Chưa có phiên sạc để theo dõi',
    description: 'Tài khoản này không có quyền xem hoặc quản lý dữ liệu trạm.',
    icon: 'session',
  },
  accountant: {
    title: 'Khu vực kế toán',
    heading: 'Chưa có dữ liệu đối soát',
    description: 'Tài khoản này không có quyền xem hoặc quản lý dữ liệu trạm.',
    icon: 'report',
  },
}

const fallbackContent = {
  title: 'Phạm vi tài khoản',
  heading: 'Chưa có chức năng phù hợp',
  description: 'Vai trò hiện tại chưa được cấp quyền sử dụng chức năng nào.',
  icon: 'settings' as IconName,
}

export function RoleHomePage({ role }: RoleHomePageProps) {
  const content = roleContent[role] ?? fallbackContent

  return (
    <section className="workspace role-home" aria-labelledby="page-title">
      <div className="page-heading">
        <div>
          <h1 id="page-title">{content.title}</h1>
          <p>Chỉ hiển thị dữ liệu và thao tác thuộc phạm vi vai trò của bạn.</p>
        </div>
      </div>
      <div className="role-home__state">
        <span className="role-home__icon"><Icon name={content.icon} /></span>
        <h2>{content.heading}</h2>
        <p>{content.description}</p>
      </div>
    </section>
  )
}
