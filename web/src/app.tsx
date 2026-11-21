import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import type { Role } from "./api/client";
import { Loading, OfflineBanner } from "./components/states";
import { languages, setLanguage, type Language } from "./i18n";
import { useAuth } from "./lib/use-auth";
import { LoginPage } from "./pages/login";
import { TodayPage } from "./pages/today";

// Secondary areas load on demand to keep the first load small (AC-F7-3).
const HistoryPage = lazy(() => import("./pages/history").then((m) => ({ default: m.HistoryPage })));
const DayPage = lazy(() => import("./pages/day").then((m) => ({ default: m.DayPage })));
const MomentsPage = lazy(() => import("./pages/moments").then((m) => ({ default: m.MomentsPage })));
const SalesPage = lazy(() => import("./pages/sales").then((m) => ({ default: m.SalesPage })));
const SettingsPage = lazy(() => import("./pages/settings").then((m) => ({ default: m.SettingsPage })));
const AuditPage = lazy(() => import("./pages/audit").then((m) => ({ default: m.AuditPage })));
const InstallPage = lazy(() => import("./pages/install").then((m) => ({ default: m.InstallPage })));
const SupportKitsPage = lazy(() => import("./pages/support").then((m) => ({ default: m.SupportKitsPage })));
const SupportKitPage = lazy(() => import("./pages/support").then((m) => ({ default: m.SupportKitPage })));

const TABS: Record<Role, [string, string][]> = {
  owner: [["/", "today"], ["/history", "history"], ["/moments", "moments"], ["/sales", "sales"], ["/settings", "settings"], ["/audit", "audit"]],
  manager: [["/", "today"], ["/history", "history"], ["/moments", "moments"], ["/sales", "sales"]],
  staff: [["/sales", "sales"]],
  installer: [["/install", "install"]],
  support: [["/support/kits", "support"], ["/audit", "audit"]],
};
const HOME: Record<Role, string> = { owner: "/", manager: "/", staff: "/sales", installer: "/install", support: "/support/kits" };

function Shell() {
  const { t, i18n } = useTranslation();
  const { me, signOut } = useAuth();
  if (!me) return <Loading />;
  const role = me.user.role;
  return (
    <>
      <header className="top">
        <b>{t("app.name")}</b>
        <div className="row">
          <select
            aria-label={t("nav.language")}
            value={i18n.language}
            onChange={(e) => setLanguage(e.target.value as Language)}
          >
            {languages.map((l) => (
              <option key={l} value={l}>
                {t(`lang.${l}`)}
              </option>
            ))}
          </select>
          <button className="ghost" onClick={signOut}>
            {t("nav.logout")}
          </button>
        </div>
      </header>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 16px" }}>
        <OfflineBanner />
      </div>
      <Suspense fallback={<Loading />}>
        <Routes>
          {role === "owner" || role === "manager" ? (
            <>
              <Route path="/" element={<TodayPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/day/:shopId/:date" element={<DayPage />} />
              <Route path="/moments" element={<MomentsPage />} />
            </>
          ) : null}
          {role !== "installer" && role !== "support" && <Route path="/sales" element={<SalesPage />} />}
          {role === "owner" && (
            <>
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/shops/:shopId/settings" element={<SettingsPage />} />
            </>
          )}
          {(role === "owner" || role === "support") && <Route path="/audit" element={<AuditPage />} />}
          {role === "installer" && <Route path="/install" element={<InstallPage />} />}
          {role === "support" && (
            <>
              <Route path="/support/kits" element={<SupportKitsPage />} />
              <Route path="/support/kits/:kitId" element={<SupportKitPage />} />
            </>
          )}
          <Route path="*" element={<Navigate to={HOME[role]} replace />} />
        </Routes>
      </Suspense>
      <nav className="tabs">
        {TABS[role].map(([to, key]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
            {t(`nav.${key}`)}
          </NavLink>
        ))}
      </nav>
    </>
  );
}

export function App() {
  const { signedIn } = useAuth();
  return signedIn ? <Shell /> : <LoginPage />;
}
