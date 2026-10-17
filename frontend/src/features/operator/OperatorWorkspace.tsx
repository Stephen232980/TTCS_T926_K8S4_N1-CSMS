import { useCallback, useEffect, useRef, useState } from "react";
import type { AuthenticatedUser } from "../auth/model/auth";
import { Icon, type IconName } from "../../components/icons/Icon";
import { OwnerCharging, type SessionListState } from "../owner/OwnerCharging";
import { OperatorMonitoring } from "./OperatorMonitoring";
import "../owner/owner.css";
import "./operator.css";
type Area = "monitor" | "sessions" | "review";
const navigation: { area: Area; label: string; icon: IconName }[] = [
  { area: "monitor", label: "Giám sát trụ", icon: "bolt" },
  { area: "sessions", label: "Phiên sạc", icon: "session" },
  { area: "review", label: "Cần xem xét", icon: "report" },
];
function hashArea(): Area {
  return window.location.hash.split("?")[0] === "#ops-sessions"
    ? "sessions"
    : window.location.hash.split("?")[0] === "#ops-review"
      ? "review"
      : "monitor";
}
export function OperatorWorkspace({
  currentUser,
  onLogout,
  onExit,
}: {
  currentUser: AuthenticatedUser;
  onLogout: () => Promise<void>;
  onExit?: () => void;
}) {
  const [area, setArea] = useState<Area>(hashArea);
  const lists = useRef<Partial<Record<Area, SessionListState>>>(window.history.state?.operatorLists ?? {});
  const [listStates, setListStates] = useState<Partial<Record<Area, SessionListState>>>(() => window.history.state?.operatorLists ?? {});
  const rememberList = useCallback((value: SessionListState) => {
    lists.current[area] = value;
    setListStates({ ...lists.current });
    window.history.replaceState({ ...window.history.state, operatorLists: lists.current }, "");
  }, [area]);
  const [sessionId, setSessionId] = useState<number | undefined>(() => Number(new URLSearchParams(window.location.hash.split("?")[1]).get("session")) || undefined);
  const [accountOpen, setAccountOpen] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => {
    const change = () => {
      lists.current = window.history.state?.operatorLists ?? lists.current;
      setListStates({ ...lists.current });
      setArea(hashArea());
      setSessionId(Number(new URLSearchParams(window.location.hash.split("?")[1]).get("session")) || undefined);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  function selectSession(id?: number) {
    window.history.pushState({ ...window.history.state, operatorLists: lists.current }, "", `#ops-${area}${id ? `?session=${id}` : ""}`);
    setSessionId(id);
  }
  function navigate(next: Area) {
    window.history.pushState({ ...window.history.state, operatorLists: lists.current }, "", `#ops-${next}`);
    setArea(next);
    setSessionId(undefined);
  }
  async function logout() {
    setLoggingOut(true);
    try {
      await onLogout();
    } catch {
      setLogoutError("Chưa đăng xuất được. Hãy thử lại.");
    } finally {
      setLoggingOut(false);
    }
  }
  // THESIS: Prioritize real operational exceptions while preserving the approved owner visual world.
  // OWN-WORLD: CSMS teal shell, equipment silhouettes and numbered connector symbols.
  // STORY: Find the charger, inspect connector 1, inspect its session, then confirm an authorized command.
  // FIRST VIEWPORT: Fixed shell with independently scrolling equipment and detail.
  // FORM: Approved status-groups variant 3, seed 0bbde6cb.
  // FINISH: Real ops APIs, SSE and shared owner session detail; no synthetic telemetry.
  return (
    <div className="owner-shell operator-shell">
      <aside className="owner-sidebar">
        <a
          className="owner-brand"
          href="#ops-monitor"
          onClick={(event) => { event.preventDefault(); navigate("monitor"); }}
        >
          <Icon name="bolt" />
          CSMS
        </a>
        <nav aria-label="Khu vực vận hành">
          {navigation.map((item) => (
            <a
              key={item.area}
              href={`#ops-${item.area}`}
              className={area === item.area ? "is-active" : ""}
              aria-current={area === item.area ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                navigate(item.area);
              }}
            >
              <Icon name={item.icon} />
              {item.label}
            </a>
          ))}
        </nav>
        <footer>
          <button className="operator-account-toggle" aria-expanded={accountOpen} aria-controls="operator-account" onClick={() => setAccountOpen(!accountOpen)}>Tài khoản</button>
          <div id="operator-account" className={`operator-account-body ${accountOpen ? "is-open" : ""}`}>
          <strong>Vận hành viên</strong>
          <span title={currentUser.email}>{currentUser.email}</span>
          {onExit && <button onClick={onExit}>Đổi khu vực</button>}
          {logoutError && <p role="alert">{logoutError}</p>}
          <button disabled={loggingOut} onClick={() => void logout()}>
            <Icon name="logout" />
            {loggingOut ? "Đang đăng xuất…" : "Đăng xuất"}
          </button>
        </div>
        </footer>
      </aside>
      <main className="owner-main">
        {area === "monitor" ? (
          <OperatorMonitoring
            canConfigure={currentUser.roles.includes('operator')}
            onOpenSession={(id) => {
              navigate("sessions");
              window.history.replaceState(window.history.state, "", `#ops-sessions?session=${id}`);
              setSessionId(id);
            }}
          />
        ) : (
          <OwnerCharging
            key={`${area}-${sessionId ?? "list"}`}
            area="ops"
            initialState={area === "review" ? "review" : "all"}
            initialSessionId={sessionId}
            initialListState={listStates[area]}
            onRememberList={rememberList}
            onSessionSelection={selectSession}
          />
        )}
      </main>
    </div>
  );
}
