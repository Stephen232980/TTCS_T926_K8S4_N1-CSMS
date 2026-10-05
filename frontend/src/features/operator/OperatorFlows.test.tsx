import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { OperatorMonitoring } from "./OperatorMonitoring";
import { OwnerCharging } from "../owner/OwnerCharging";
const connector = (number: number, status = "Available") => ({
  id: `c${number}`,
  number,
  status,
  status_updated_at: "2026-10-05T01:00:00Z",
  last_error_code: null,
});
const charger = {
  id: "cp",
  code: "CP-OPS",
  station_name: "Trạm ngoài sở hữu",
  online: true,
  connectors: [connector(2), connector(1, "Charging")],
  last_seen_at: "2026-10-05T01:00:00Z",
};
const session = {
  id: 91,
  station_name: "Trạm ngoài sở hữu",
  charge_point_code: "CP-OPS",
  connector_number: 1,
  started_at: "2026-10-05T01:00:00Z",
  ended_at: null,
  energy_kwh: null,
  latest_meter_wh: "3500",
  latest_meter_at: "2026-10-05T01:10:00Z",
  meter_start_wh: "1000",
  tag_tail: "TEST",
  review_reasons: ["offline_timeout"],
  abnormal_since: "2026-10-05T01:10:00Z",
};
const page = (items: unknown[]) => ({
  items,
  page: 1,
  total: items.length,
  total_pages: 1,
});
class Stream {
  static current: Stream;
  onmessage: ((e: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  addEventListener = vi.fn();
  constructor() {
    Stream.current = this;
  }
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function setup(abnormal = true) {
  vi.stubGlobal("EventSource", Stream);
  const fetcher = vi.fn(
    async (url: string, options?: RequestInit) =>
      new Response(
        JSON.stringify(
          url.endsWith("/close")
            ? { energy_kwh: "2.5" }
            : url.includes("/samples?")
              ? page([])
              : url.includes("/connections?")
                ? page([charger])
                : url.includes("/events")
                  ? []
                  : page([
                      {
                        ...session,
                        abnormal_since: abnormal
                          ? session.abnormal_since
                          : null,
                      },
                    ]),
        ),
        { status: options?.method === "POST" ? 200 : 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
it("defaults to connector 1 regardless of backend order and switches without retaining its telemetry", async () => {
  const fetcher = setup();
  const open = vi.fn();
  const user = userEvent.setup();
  render(<OperatorMonitoring onOpenSession={open} />);
  await user.click(
    await screen.findByRole("button", { name: "Chọn trụ CP-OPS" }),
  );
  await screen.findByRole("heading", { name: "Đầu nối 1" });
  await user.click(
    await screen.findByRole("button", { name: "Xem phiên #91" }),
  );
  expect(open).toHaveBeenCalledWith(91);
  await user.click(screen.getByRole("button", { name: /CP-OPS · Đầu nối 2/ }));
  await screen.findByText("Không có phiên đang mở tại đầu nối này.");
  expect(
    screen.queryByRole("button", { name: "Xem phiên #91" }),
  ).not.toBeInTheDocument();
  expect(
    fetcher.mock.calls.every(([url]) => url.includes("/api/v1/ops/")),
  ).toBe(true);
});
it("updates selected connector from SSE and closes the stream on unmount", async () => {
  setup();
  const user = userEvent.setup();
  const view = render(<OperatorMonitoring onOpenSession={vi.fn()} />);
  await user.click(
    await screen.findByRole("button", { name: "Chọn trụ CP-OPS" }),
  );
  await screen.findByRole("heading", { name: "Đầu nối 1" });
  await act(async () =>
    Stream.current.onmessage?.({
      data: JSON.stringify(
        page([
          { ...charger, online: false, connectors: [connector(1, "unknown")] },
        ]),
      ),
    }),
  );
  expect(screen.getAllByText("Ngoại tuyến").length).toBeGreaterThan(0);
  expect(
    screen.getByRole("button", { name: /CP-OPS · Đầu nối 1/ }),
  ).toHaveAttribute("aria-label", expect.stringContaining("Chưa rõ"));
  view.unmount();
  expect(Stream.current.close).toHaveBeenCalled();
});
it("reuses session details through ops endpoints, hides cards, and closes only with a reason and confirmation", async () => {
  const fetcher = setup();
  const user = userEvent.setup();
  render(<OwnerCharging area="ops" initialSessionId={91} />);
  await screen.findByRole("heading", { name: "Phiên #91" });
  expect(
    screen.queryByRole("button", { name: "Thẻ tài xế" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Đóng hồ sơ phiên" }));
  expect(
    screen.getByRole("button", { name: "Xác nhận đóng phiên" }),
  ).toBeDisabled();
  await user.type(screen.getByLabelText("Lý do đóng tay"), "Đã kiểm tra trụ");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Xác nhận đóng phiên" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) => url === "/api/v1/charging/sessions/91/close",
      ),
    ).toBe(true),
  );
  const call = fetcher.mock.calls.find(([url]) => url.endsWith("/close"))!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    reason: "Đã kiểm tra trụ",
  });
  expect(
    fetcher.mock.calls
      .filter(([, options]) => options?.method !== "POST")
      .every(([url]) => url.startsWith("/api/v1/ops/")),
  ).toBe(true);
});
it("does not offer manual closure for ordinary open sessions even if they have review reasons", async () => {
  setup(false);
  render(<OwnerCharging area="ops" initialSessionId={91} />);
  await screen.findByRole("heading", { name: "Phiên #91" });
  expect(
    screen.queryByRole("button", { name: "Đóng hồ sơ phiên" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Dừng từ xa #91" }),
  ).toBeInTheDocument();
});
it('keeps operator sessions as flat rows and loads shared details only after selection', async () => {
  const fetcher = setup();
  const user = userEvent.setup();
  render(<OwnerCharging area="ops" />);
  const row = await screen.findByRole('button', {name:/Phiên #91/});
  expect(row).toHaveClass('operator-session-row');
  expect(screen.queryByRole('heading', {name:'Phiên #91'})).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url])=>url.includes('/samples?'))).toBe(false);
  await user.type(screen.getByRole('searchbox', {name:'Tìm phiên trong trang'}), 'không khớp');
  expect(screen.queryByRole('button', {name:/Phiên #91/})).not.toBeInTheDocument();
  await user.clear(screen.getByRole('searchbox', {name:'Tìm phiên trong trang'}));
  await user.click(await screen.findByRole('button', {name:/Phiên #91/}));
  await screen.findByRole('heading', {name:'Phiên #91'});
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.startsWith('/api/v1/ops/charging/sessions/91/samples?'))).toBe(true));
  await user.click(screen.getByRole('button', {name:'Quay lại danh sách phiên'}));
  expect(await screen.findByRole('button', {name:/Phiên #91/})).toHaveClass('operator-session-row');
});
