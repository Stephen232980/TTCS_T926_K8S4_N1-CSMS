import type { AuthenticatedUser } from './auth'

export function getPermissions(user: AuthenticatedUser) {
  return {
    canViewStations: user.roles.some((role) =>
      ['station_owner', 'operator', 'admin'].includes(role),
    ),
    canManageStations: user.roles.includes('station_owner'),
    canManageChargePoints: user.roles.includes('station_owner'),
    canViewCharging: user.roles.some((role) => ['station_owner', 'operator', 'admin', 'accountant'].includes(role)),
    canCloseChargingSessions: user.roles.some((role) => ['operator', 'admin'].includes(role)),
    canControlChargers: user.roles.some((role) => ['operator', 'admin'].includes(role)),
    canViewControlAudit: user.roles.includes('admin'),
  }
}

export function getHomeRole(user: AuthenticatedUser): string {
  if (getPermissions(user).canViewStations) {
    return ['station_owner', 'operator', 'admin'].find((role) => user.roles.includes(role)) ?? ''
  }
  return ['driver', 'accountant'].find((role) => user.roles.includes(role)) ?? ''
}
