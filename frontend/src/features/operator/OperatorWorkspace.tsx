import { useCallback, useEffect, useState } from "react";
import type { AuthenticatedUser } from "../auth/model/auth";
import { Icon, type IconName } from "../../components/icons/Icon";
import { OwnerCharging } from "../owner/OwnerCharging";
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
  return window.location.hash === "#ops-sessions"
    ? "sessions"
    : window.location.hash === "#ops-review"
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
  const [sessionId, setSessionId] = useState<number>();
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  useEffect(() => {
    const change = () => {
      setArea(hashArea());
      setSessionId(undefined);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  const opened = useCallback(() => setSessionId(undefined), []);
  function navigate(next: Area) {
    window.history.replaceState(null, "", `#ops-${next}`);
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
          onClick={() => navigate("monitor")}
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
          <strong>Vận hành viên</strong>
          <span title={currentUser.email}>{currentUser.email}</span>
          {onExit && <button onClick={onExit}>Đổi khu vực</button>}
          {logoutError && <p role="alert">{logoutError}</p>}
          <button disabled={loggingOut} onClick={() => void logout()}>
            <Icon name="logout" />
            {loggingOut ? "Đang đăng xuất…" : "Đăng xuất"}
          </button>
        </footer>
      </aside>
      <main className="owner-main">
        {area === "monitor" ? (
          <OperatorMonitoring
            onOpenSession={(id) => {
              navigate("sessions");
              setSessionId(id);
            }}
          />
        ) : (
          <OwnerCharging
            key={area}
            area="ops"
            initialState={area === "review" ? "review" : "all"}
            initialSessionId={sessionId}
            onInitialSessionOpened={opened}
          />
        )}
      </main>
    </div>
  );
}
