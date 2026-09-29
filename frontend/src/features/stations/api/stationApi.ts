import type {
  PaginatedResult,
  Station,
  StationInput,
  StationListQuery,
  StationUpdate,
} from '../model/station'

export interface StationApi {
  listStations(
    query: StationListQuery,
    signal?: AbortSignal,
  ): Promise<PaginatedResult<Station>>

  createStation(input: StationInput): Promise<Station>

  updateStation(
    stationId: string,
    input: StationUpdate,
  ): Promise<Station>
}