import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { get, type Shop, type Today } from "../api/client";
import { ErrorMessage, Loading } from "../components/states";
import { useAuth } from "../lib/use-auth";
import { hhmm, hourRanges, localToday, moneySeen, seen } from "../lib/format";

function ShopToday({ shop }: { shop: Shop }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["today", shop.id],
    queryFn: () => get<Today>(`/v1/shops/${shop.id}/today`),
    refetchInterval: 60_000,
  });
  const d = q.data;
  return (
    <section className="card" data-testid={`today-${shop.id}`}>
      <div className="row">
        <h2 className="grow m0">
          <Link to={`/day/${shop.id}/${localToday(shop.timezone)}`}>{shop.name}</Link>
        </h2>
        <button className="ghost" onClick={() => void q.refetch()}>
          {t("today.refresh")}
        </button>
      </div>
      {q.isPending && <Loading />}
      <ErrorMessage error={q.error} />
      {d && (
        <>
          <div className="stats">
            <div className="stat hero">
              <small>{t("today.money")}</small>
              <b>{moneySeen(d.sales_xof, d.missing_hours)}</b>
            </div>
            <div className="stat">
              <small>{t("today.visitors")}</small>
              <b>{seen(d.visitors_in, d.missing_hours)}</b>
            </div>
            <div className="stat">
              <small>{t("today.served")}</small>
              <b>{seen(d.served, d.missing_hours)}</b>
            </div>
            <div className="stat">
              <small>{t("today.counter")}</small>
              <b data-testid="counter-state">
                {d.counter.state === "staffed"
                  ? t("today.counterStaffed")
                  : d.counter.state === "empty" && d.counter.since
                    ? t("today.counterEmpty", { time: hhmm(d.counter.since, shop.timezone) })
                    : t("today.counterUnknown")}
              </b>
            </div>
          </div>
          {d.missing_hours.length > 0 && (
            <p className="banner">{t("today.missingSoFar", { hours: hourRanges(d.missing_hours) })}</p>
          )}
          <p className="muted small">
            {d.last_heartbeat_at
              ? t("today.lastHeartbeat", { time: hhmm(d.last_heartbeat_at, shop.timezone) })
              : t("today.noHeartbeat")}
          </p>
        </>
      )}
    </section>
  );
}

export function TodayPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const shops = me?.shops.filter((s) => s.status !== "closed") ?? [];
  return (
    <main>
      <h1>{t("today.title")}</h1>
      {shops.length === 0 && <p>{t("today.noShops")}</p>}
      {shops.map((s) => (
        <ShopToday key={s.id} shop={s} />
      ))}
    </main>
  );
}
