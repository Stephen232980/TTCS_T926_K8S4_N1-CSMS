import { useEffect, useState } from "react";
import { notifySessionUnauthorized } from "../auth/sessionEvents";
import { ControlAction } from "../ocpp/ControlAction";
import {
  ChargerDrawing,
  ConnectionSymbol,
  ConnectorSymbol,
} from "../owner/OwnerVisuals";
import {
  ownerRequest,
  clock,
  decimal,
  statusLabel,
  type OwnerPage,
  type OwnerSession,
  type MeterSample,
} from "../owner/ownerApi";
interface Connector {
  id: string;
  number: number;
  status: string;
  raw_ocpp_status: string | null;
  status_updated_at: string;
  last_error_code: string | null;
  last_vendor_error_code: string | null;
  last_error_at: string | null;
}
interface Connection {
  id: string;
  code: string;
  station_name: string;
  online: boolean;
  connected: boolean;
  boot_accepted: boolean;
  connected_at: string | null;
  last_boot_at: string | null;
  last_seen_at: string | null;
  raw_ocpp_status: string | null;
  error_code: string | null;
  vendor: string | null;
  model: string | null;
  firmware_version: string | null;
  connectors: Connector[];
}
interface Result {
  items: Connection[];
  total: number;
  page: number;
  total_pages: number;
}
function connectionGroup(c: Connection) {
  if (
    !c.online ||
    c.raw_ocpp_status === "Faulted" ||
    c.connectors.some((k) =>
      ["Faulted", "Unavailable", "unknown"].includes(k.status),
    )
  )
    return "attention";
  if (c.connectors.some((k) => k.status === "Charging")) return "charging";
  return "other";
}
function defaultConnector(c: Connection) {
  return (
    c.connectors.find((k) => k.number === 1) ??
    [...c.connectors].sort((a, b) => a.number - b.number)[0]
  );
}
function ConnectorSession({
  charger,
  connector,
  onOpen,
}: {
  charger: Connection;
  connector: Connector;
  onOpen: (id: number) => void;
}) {
  const [data, setData] = useState<{
    session: OwnerSession | null;
    samples: MeterSample[];
  } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function load() {
      if (running) return;
      running = true;
      try {
        let session: OwnerSession | null = null;
        for (let page = 1; ; page++) {
          const result = await ownerRequest<OwnerPage<OwnerSession>>(
            `/ops/charging/sessions?state=open&page_size=100&page=${page}`,
            { signal: controller.signal },
          );
          session =
            result.items.find(
              (item) =>
                item.charge_point_code === charger.code &&
                item.connector_number === connector.number,
            ) ?? null;
          if (session || page >= result.total_pages) break;
        }
        const samples = session
          ? (
              await ownerRequest<OwnerPage<MeterSample>>(
                `/ops/charging/sessions/${session.id}/samples?page=1&page_size=100`,
                { signal: controller.signal },
              )
            ).items
          : [];
        if (!controller.signal.aborted) {
          setData({ session, samples });
          setError("");
        }
      } catch (err) {
        if (!controller.signal.aborted)
          setError(
            err instanceof Error
              ? err.message
              : "Không tải được phiên. Thử lại.",
          );
      } finally {
        running = false;
      }
    }
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [charger.code, connector.number, retry]);
  return (
    <section className="operator-telemetry">
      <h3>Phiên tại đầu nối {connector.number}</h3>
      {error && (
        <p role="alert">
          {error}
          <button onClick={() => setRetry((v) => v + 1)}>Thử lại</button>
        </p>
      )}
      {!data && !error && <p role="status">Đang tải số đo…</p>}
      {data && (
        <>
          {error && <p>Dữ liệu lần tải trước có thể đã cũ.</p>}
          {data.session ? (
            <>
              <div className="operator-readings">
                {[
                  {
                    key: "Power.Active.Import",
                    label: "Công suất",
                    units: ["W", "kW"],
                    unit: "kW",
                  },
                  {
                    key: "Temperature",
                    label: "Nhiệt độ",
                    units: ["Celsius", "Celcius"],
                    unit: "°C",
                  },
                ].map((metric) => {
                  const reading = data.samples
                    .filter(
                      (s) =>
                        s.measurand === metric.key &&
                        !s.phase &&
                        metric.units.includes(s.unit) &&
                        s.value.trim() &&
                        Number.isFinite(Number(s.value)),
                    )
                    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0];
                  return (
                    <div key={metric.key}>
                      <span>{metric.label}</span>
                      <strong>
                        {reading
                          ? decimal(
                              Number(reading.value) /
                                (reading.unit === "W" ? 1000 : 1),
                            )
                          : "—"}{" "}
                        {metric.unit}
                      </strong>
                      <small>
                        {reading ? clock(reading.timestamp) : "Chưa nhận số đo"}
                      </small>
                    </div>
                  );
                })}
              </div>
              <p>
                Điện đã cấp:{" "}
                {decimal(
                  data.session.latest_meter_wh !== null &&
                    Number(data.session.latest_meter_wh) >=
                      Number(data.session.meter_start_wh)
                    ? (Number(data.session.latest_meter_wh) -
                        Number(data.session.meter_start_wh)) /
                        1000
                    : null,
                )}{" "}
                kWh
              </p>
              <button
                className="primary-button"
                onClick={() => onOpen(data.session!.id)}
              >
                Xem phiên #{data.session.id}
              </button>
            </>
          ) : (
            <p>
              {connector.status === "Charging"
                ? "Trụ báo đang sạc; chưa tìm thấy hồ sơ phiên mở. Cần kiểm tra dữ liệu nhận từ trụ."
                : "Không có phiên đang mở tại đầu nối này."}
            </p>
          )}
        </>
      )}
    </section>
  );
}
export function OperatorMonitoring({
  onOpenSession,
}: {
  onOpenSession: (id: number) => void;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [streamState, setStreamState] = useState("Đang nối luồng cập nhật…");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selection, setSelection] = useState<{
    id: string;
    number: number;
  } | null>(null);
  useEffect(() => {
    let stopped = false;
    let controller: AbortController | undefined;
    let source: EventSource | undefined;
    let version = 0;
    const base = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
    const accept = (payload: Result) => {
      setResult(payload);
      setError("");
      setUpdatedAt(new Date().toISOString());
      setLoading(false);
    };
    async function load() {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      const issuedVersion = version;
      try {
        const response = await fetch(
          `${base}/api/v1/ops/ocpp/connections?page=${page}&page_size=100`,
          { credentials: "include", signal },
        );
        if (response.status === 401) {
          source?.close();
          notifySessionUnauthorized();
        }
        if (response.status === 403) source?.close();
        if (!response.ok)
          throw new Error(
            response.status === 403
              ? "Bạn không có quyền xem kết nối trụ."
              : "Không tải được trạng thái trụ. Hãy thử lại.",
          );
        const payload = (await response.json()) as Result;
        if (!stopped && issuedVersion === version) accept(payload);
      } catch (err: unknown) {
        if (!stopped && !signal.aborted && issuedVersion === version) {
          setError(
            err instanceof Error ? err.message : "Không tải được dữ liệu.",
          );
          setLoading(false);
        }
      }
    }
    const first = window.setTimeout(() => {
      setLoading(true);
      setResult(null);
      void load();
      if (typeof EventSource !== "undefined") {
        source = new EventSource(
          `${base}/api/v1/ops/ocpp/connections/events?page=${page}&page_size=100`,
          { withCredentials: true },
        );
        source.onopen = () => {
          if (!stopped) {
            setStreamState("Đang cập nhật trực tiếp");
            void load();
          }
        };
        source.onmessage = (event) => {
          if (stopped) return;
          try {
            const payload = JSON.parse(event.data) as Result;
            version++;
            accept(payload);
            setStreamState("Đang cập nhật trực tiếp");
          } catch {
            setStreamState("Không đọc được cập nhật. Đang kết nối lại…");
            source?.close();
            setRevision((r) => r + 1);
          }
        };
        source.onerror = () => {
          if (!stopped) {
            setStreamState(
              "Mất luồng cập nhật · Đang tự kết nối lại. Dữ liệu có thể đã cũ.",
            );
            void load();
          }
        };
        source.addEventListener("access-denied", () => {
          source?.close();
          notifySessionUnauthorized();
        });
      } else setStreamState("Tự tải lại mỗi giây");
    }, 0);
    // Fallback for browsers without EventSource; native EventSource handles retries otherwise.
    const fallback = window.setInterval(() => {
      if (!source && !document.hidden) void load();
    }, 1000);
    return () => {
      stopped = true;
      window.clearTimeout(first);
      window.clearInterval(fallback);
      source?.close();
      controller?.abort();
    };
  }, [page, revision]);

  const visible =
    result?.items.filter(
      (c) =>
        `${c.code} ${c.station_name}`
          .toLocaleLowerCase("vi-VN")
          .includes(search.toLocaleLowerCase("vi-VN")) &&
        (filter === "all" ||
          (filter === "offline" && !c.online) ||
          filter === connectionGroup(c)),
    ) ?? [];
  const selected = result?.items.find((c) => c.id === selection?.id);
  const connector = selected?.connectors.find(
    (c) => c.number === selection?.number,
  );
  function select(c: Connection, number = defaultConnector(c)?.number) {
    setSelection(
      number === undefined ? { id: c.id, number: 0 } : { id: c.id, number },
    );
  }
  return (
    <section className="owner-page operator-monitor">
      <header className="owner-heading">
        <div>
          <h1>Giám sát trụ</h1>
          <p>Toàn hệ thống · ưu tiên trụ cần chú ý.</p>
        </div>
        <button
          className="secondary-button"
          onClick={() => setRevision((v) => v + 1)}
        >
          Cập nhật ngay
        </button>
      </header>
      <p className="operator-stream" role="status">
        {streamState}
        {updatedAt && ` · ${clock(updatedAt)}`}
      </p>
      <div className="owner-toolbar">
        <label>
          Tìm trong trang{" "}
          <input
            type="search"
            value={search}
            placeholder="Mã trụ hoặc tên trạm"
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          Hiển thị{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">Tất cả</option>
            <option value="attention">Cần chú ý</option>
            <option value="charging">Đang sạc</option>
            <option value="offline">Ngoại tuyến</option>
          </select>
        </label>
        <span>
          {visible.length} / {result?.total ?? 0} trụ
        </span>
      </div>
      {error && (
        <p role="alert" className="owner-error">
          {error} {result && "Dữ liệu có thể đã cũ."}
          <button onClick={() => setRevision((v) => v + 1)}>Thử lại</button>
        </p>
      )}
      <div
        className={`operator-monitor-body${selected ? " has-selection" : ""}`}
      >
        <div className="owner-scroll operator-equipment">
          {loading && !result && <p role="status">Đang tải trụ…</p>}
          {!loading && !error && !visible.length && (
            <div className="owner-panel owner-placeholder">
              {result?.total
                ? "Không có trụ khớp bộ lọc trong trang này."
                : "Chưa có trụ được đăng ký."}
            </div>
          )}
          {[
            ["attention", "Cần chú ý"],
            ["charging", "Đang sạc"],
            ["other", "Sẵn sàng và trạng thái khác"],
          ].map(([group, label]) => {
            const items = visible.filter((c) => connectionGroup(c) === group);
            return (
              items.length > 0 && (
                <section className="operator-group" key={group}>
                  <h2>
                    {label} <small>{items.length}</small>
                  </h2>
                  <div className="operator-device-grid">
                    {items.map((c) => (
                      <article
                        className={`operator-device${selected?.id === c.id ? " is-selected" : ""}`}
                        key={c.id}
                      >
                        <button
                          className="operator-device-heading"
                          onClick={() => select(c)}
                          aria-label={`Chọn trụ ${c.code}`}
                        >
                          <span>
                            <strong>{c.code}</strong>
                            <small>{c.station_name}</small>
                          </span>
                          <ConnectionSymbol online={c.online} />
                        </button>
                        <button
                          className="operator-device-picture"
                          aria-label={`Xem trụ ${c.code}`}
                          onClick={() => select(c)}
                        >
                          <ChargerDrawing online={c.online} />
                        </button>
                        <div className="owner-connectors">
                          {c.connectors.map((k) => (
                            <button
                              key={k.id}
                              className={`connector-${k.status.toLowerCase()}${selected?.id === c.id && connector?.number === k.number ? " is-selected" : ""}`}
                              title={`Đầu nối ${k.number}: ${statusLabel[k.status.toLowerCase()] ?? k.status}`}
                              aria-label={`${c.code} · Đầu nối ${k.number} · ${statusLabel[k.status.toLowerCase()] ?? k.status}`}
                              aria-pressed={
                                selected?.id === c.id &&
                                connector?.number === k.number
                              }
                              onClick={() => select(c, k.number)}
                            >
                              <small>{k.number}</small>
                              <ConnectorSymbol status={k.status} />
                            </button>
                          ))}
                        </div>
                        <small>
                          {c.connectors.length} đầu nối ·{" "}
                          {c.online ? "Trực tuyến" : "Ngoại tuyến"}
                        </small>
                      </article>
                    ))}
                  </div>
                </section>
              )
            );
          })}
        </div>
        <aside
          className="owner-panel owner-scroll operator-detail"
          aria-label="Chi tiết trụ"
        >
          {selected ? (
            <>
              <button
                className="text-button operator-detail-back"
                onClick={() => setSelection(null)}
              >
                Quay lại trụ
              </button>
              <h2>{selected.code}</h2>
              <p>{selected.station_name}</p>
              <p>
                <ConnectionSymbol online={selected.online} />
                {selected.online ? "Trực tuyến" : "Ngoại tuyến"}
              </p>
              <p>Liên lạc cuối: {clock(selected.last_seen_at)}</p>
              {connector ? (
                <>
                  <h3>Đầu nối {connector.number}</h3>
                  <p>
                    {statusLabel[connector.status.toLowerCase()] ??
                      connector.status}{" "}
                    · {clock(connector.status_updated_at)}
                  </p>
                  {connector.last_error_code &&
                    connector.last_error_code !== "NoError" && (
                      <p className="owner-error">
                        Lỗi gần nhất: {connector.last_error_code}{" "}
                        {connector.last_vendor_error_code} ·{" "}
                        {clock(connector.last_error_at)}
                      </p>
                    )}
                  <ConnectorSession
                    key={`${selected.id}:${connector.number}`}
                    charger={selected}
                    connector={connector}
                    onOpen={onOpenSession}
                  />
                </>
              ) : (
                <p>Chưa khai báo đầu nối.</p>
              )}
              <ControlAction
                key={selected.id}
                chargerId={selected.id}
                label={selected.code}
              />
              <details>
                <summary>Thông tin trụ và kết nối</summary>
                <p>
                  {selected.vendor ?? "Chưa có hãng"} ·{" "}
                  {selected.model ?? "Chưa có model"}
                </p>
                <p>Firmware: {selected.firmware_version ?? "Chưa có"}</p>
                <p>
                  Khởi động: {clock(selected.last_boot_at)} ·{" "}
                  {selected.boot_accepted
                    ? "Đã chấp nhận"
                    : "Chưa được chấp nhận"}
                </p>
                {selected.error_code && selected.error_code !== "NoError" && (
                  <p>Lỗi trụ: {selected.error_code}</p>
                )}
              </details>
            </>
          ) : (
            <div className="owner-placeholder">
              <ChargerDrawing />
              <h2>Chọn một trụ</h2>
              <p>Đầu nối 1 sẽ được mở trước để xem trạng thái và số đo.</p>
            </div>
          )}
        </aside>
      </div>
      <footer className="operator-pagination">
        <span>
          Trang {page} / {result?.total_pages || 1} · Lọc trong trang
        </span>
        <button
          className="secondary-button"
          disabled={page <= 1}
          onClick={() => {
            setSelection(null);
            setPage((v) => v - 1);
          }}
        >
          Trước
        </button>
        <button
          className="secondary-button"
          disabled={!result || page >= result.total_pages}
          onClick={() => {
            setSelection(null);
            setPage((v) => v + 1);
          }}
        >
          Sau
        </button>
      </footer>
    </section>
  );
}
