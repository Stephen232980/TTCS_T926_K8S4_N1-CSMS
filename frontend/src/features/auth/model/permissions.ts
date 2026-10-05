import type { AuthenticatedUser } from './auth'

export function getPermissions(user: AuthenticatedUser) {
  return {
    canUseDriver: user.roles.includes('driver'),
    canViewStations: user.roles.some((role) =>
      ['station_owner', 'operator', 'admin'].includes(role),
    ),
    canManageStations: user.roles.includes('station_owner'),
    canManageChargePoints: user.roles.includes('station_owner'),
    canViewCharging: user.roles.some((role) => ['station_owner', 'operator', 'admin', 'accountant'].includes(role)),
    canCloseChargingSessions: user.roles.includes('operator'),
    canControlChargers: user.roles.includes('operator'),
    canViewControlAudit: user.roles.includes('admin'),
    canManageAccounts: user.roles.includes('admin'),
    canViewSystemHealth: user.roles.includes('admin'),
  }
}

export function getHomeRole(user: AuthenticatedUser): string {
  if (user.defaultRole && user.roles.includes(user.defaultRole)) return user.defaultRole
  return user.roles.length === 1 ? user.roles[0] : ''
}
