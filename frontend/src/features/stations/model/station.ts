export type StationStatus = 'inactive' | 'active' | 'suspended' | 'blocked'

export interface Station {
  photoUrl?: string | null
  id: string
  timezone?: string
  name: string
  address: string
  latitude: number
  longitude: number
  status: StationStatus
  createdAt: string
  updatedAt: string
}

export interface StationInput {
  name: string
  address: string
  latitude: number
  longitude: number
}

export type StationUpdate = Partial<StationInput>

export interface StationListQuery {
  page: number
  pageSize: number
  status?: StationStatus
  search?: string
}

export interface PaginatedResult<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
  totalPages: number
}
