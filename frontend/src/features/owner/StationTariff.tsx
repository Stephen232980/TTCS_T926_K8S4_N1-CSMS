import { useEffect, useRef, useState } from 'react'
import { TariffForm, type CurrentTariff } from './TariffForm'
import {
  createStationTariff,
  readTariffContext,
  type TariffContext,
  type TariffDisplay,
} from './tariffApi'

function formTariff(tariff: TariffDisplay | null): CurrentTariff | null {
  return (
    tariff && {
      effectiveFrom: tariff.effective_from,
      pricePerKwh: tariff.bands[0]?.energy_rate_vnd_per_kwh ?? '0',
      idleFeePerMinute: tariff.idle_rate_vnd_per_minute,
      graceMinutes: tariff.grace_minutes,
      bands: tariff.bands,
    }
  )
}

export function StationTariff({ stationId }: { stationId: string }) {
  const [context, setContext] = useState<TariffContext | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    readTariffContext(stationId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setContext(data)
          setError('')
        }
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : 'Không tải được biểu giá.',
          )
      })
    return () => {
      mounted.current = false
      controller.abort()
    }
  }, [stationId, retry])
  return (
    <>
      {error && (
        <p className="owner-error" role="alert">
          {error}
          <button onClick={() => setRetry((value) => value + 1)}>
            Tải lại biểu giá
          </button>
        </p>
      )}
      {!context && !error && <p role="status">Đang tải biểu giá…</p>}
      {context && (
        <>
          {context.upcoming && (
            <section className="owner-panel">
              <h2>Biểu giá sắp áp dụng</h2>
              <p>
                Hiệu lực từ {context.upcoming.effective_from}; biểu giá hiện
                hành giữ nguyên đến ngày này.
              </p>
              <p>
                Đơn giá:{' '}
                {context.upcoming.bands
                  .map(
                    (band) =>
                      `${BigInt(band.energy_rate_vnd_per_kwh).toLocaleString('vi-VN')} VNĐ/kWh`,
                  )
                  .join(' · ')}
                . Phí chiếm trụ:{' '}
                {BigInt(
                  context.upcoming.idle_rate_vnd_per_minute,
                ).toLocaleString('vi-VN')}{' '}
                VNĐ/phút. Ân hạn: {context.upcoming.grace_minutes} phút.
              </p>
            </section>
          )}
          {!error && (
            <TariffForm
              currentTariff={formTariff(context.current)}
              stationTimezone={context.timezone}
              tariffToday={context.today}
              hasVersions={context.has_versions}
              onSave={async (values) => {
                await createStationTariff(stationId, values)
                if (!mounted.current) return
                const saved: TariffDisplay = {
                  effective_from: values.effectiveFrom,
                  idle_rate_vnd_per_minute: values.idleFeePerMinute.trim(),
                  grace_minutes: Number(values.graceMinutes),
                  bands: [
                    {
                      start_min: 0,
                      end_min: 1440,
                      label: 'Cả ngày',
                      energy_rate_vnd_per_kwh: values.pricePerKwh.trim(),
                    },
                  ],
                }
                setContext(
                  (previous) =>
                    previous && {
                      ...previous,
                      has_versions: true,
                      current:
                        values.effectiveFrom <= previous.today
                          ? saved
                          : previous.current,
                      upcoming:
                        values.effectiveFrom > previous.today &&
                        (!previous.upcoming ||
                          values.effectiveFrom <=
                            previous.upcoming.effective_from)
                          ? saved
                          : previous.upcoming,
                    },
                )
                try {
                  const data = await readTariffContext(stationId)
                  if (mounted.current) setContext(data)
                } catch {
                  if (mounted.current)
                    setError(
                      'Đã lưu biểu giá, nhưng chưa tải lại được dữ liệu. Hãy tải lại biểu giá trước khi tiếp tục.',
                    )
                }
              }}
            />
          )}
        </>
      )}
    </>
  )
}
