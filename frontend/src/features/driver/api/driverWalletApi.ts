export interface DriverWallet {
  id: string
  driver_id: string
  balance: number | string
  currency: string
  status: 'active' | 'locked' | 'suspended' | string
  is_negative: boolean
  debt_amount: number | string
}

export interface WalletLedgerItem {
  id: number
  wallet_id: string
  amount: number | string
  balance_after: number | string
  entry_type: 'topup' | 'charge' | 'refund' | 'adjustment' | string
  reference_type?: string | null
  reference_id?: string | null
  description: string
  created_at: string
}

export interface WalletLedgerList {
  items: WalletLedgerItem[]
  next_cursor: number | null
  has_more: boolean
}

export interface DriverWalletApi {
  getWallet(signal?: AbortSignal): Promise<DriverWallet>
  getTransactions(
    params?: { cursor?: number; limit?: number },
    signal?: AbortSignal,
  ): Promise<WalletLedgerList>
}

export class HttpDriverWalletApi implements DriverWalletApi {
  private readonly baseUrl: string

  constructor(baseUrl: string = '/api/v1/driver/wallet') {
    this.baseUrl = baseUrl
  }

  async getWallet(signal?: AbortSignal): Promise<DriverWallet> {
    const res = await fetch(this.baseUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'include',
      signal,
    })
    if (!res.ok) {
      throw new Error(`Không thể lấy thông tin ví (HTTP ${res.status})`)
    }
    return res.json()
  }

  async getTransactions(
    params?: { cursor?: number; limit?: number },
    signal?: AbortSignal,
  ): Promise<WalletLedgerList> {
    const query = new URLSearchParams()
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.cursor) query.set('cursor', String(params.cursor))
    const url = `${this.baseUrl}/transactions${query.toString() ? `?${query.toString()}` : ''}`
    const res = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'include',
      signal,
    })
    if (!res.ok) {
      throw new Error(`Không thể lấy lịch sử ví (HTTP ${res.status})`)
    }
    return res.json()
  }
}
