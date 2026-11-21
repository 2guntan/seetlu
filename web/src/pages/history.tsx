import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { get, type Report } from "../api/client";
import { ShopPicker } from "../components/shop-picker";
import { ErrorMessage, Loading } from "../components/states";
import { localToday } from "../lib/format";
import { verdictClass } from "../lib/parse";
import { useShopChoice } from "../lib/use-shop";

function monthBounds(ym: string): [string, string, number, number] {
  const [y, m] = ym.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const last = new Date(Date.UTC(y, m, 0));
  const lead = (first.getUTCDay() + 6) % 7; // weeks start Monday
  return [first.toISOString().slice(0, 10), last.toISOString().slice(0, 10), last.getUTCDate(), lead];
}

function shiftMonth(ym: string, n: number): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 7);
}

export function HistoryPage() {
  const { t, i18n } = useTranslation();
  const [shop, choose, shops] = useShopChoice();
  const [ym, setYm] = useState(() => localToday().slice(0, 7));
  const [from, to, days, lead] = monthBounds(ym);
  const q = useQuery({
    queryKey: ["reports", shop?.id, from, to],
    queryFn: () => get<Report[]>(`/v1/shops/${shop?.id}/reports`, { from, to }),
    enabled: !!shop,
  });
  const byDate = new Map((q.data ?? []).map((r) => [r.local_date, r]));
  const title = new Intl.DateTimeFormat(i18n.language === "en" ? "en-GB" : "fr-FR", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${ym}-01T00:00:00Z`));
  return (
    <main>
      <h1>{t("history.title")}</h1>
      <ShopPicker shop={shop} shops={shops} onChange={choose} />
      <div className="row">
        <button className="ghost" onClick={() => setYm(shiftMonth(ym, -1))} aria-label={t("history.prev")}>
          ‹
        </button>
        <b className="grow center cap">
          {title}
        </b>
        <button className="ghost" onClick={() => setYm(shiftMonth(ym, 1))} aria-label={t("history.next")}>
          ›
        </button>
      </div>
      {q.isPending && shop && <Loading />}
      <ErrorMessage error={q.error} />
      <div className="calendar">
        {Array.from({ length: lead }, (_, i) => (
          <span key={`l${i}`} />
        ))}
        {Array.from({ length: days }, (_, i) => {
          const date = `${ym}-${String(i + 1).padStart(2, "0")}`;
          const r = byDate.get(date);
          if (!r || !shop)
            return (
              <span key={date} className="d-none" title={t("history.noReport")}>
                {i + 1}
              </span>
            );
          return (
            <Link
              key={date}
              to={`/day/${shop.id}/${date}`}
              className={`d-${verdictClass(r.verdict)}`}
              data-testid={`cal-${date}`}
              data-verdict={r.verdict ?? ""}
              title={r.verdict ? t(`verdict.${r.verdict}`, { hours: r.missing_hours.join(", ") }) : ""}
            >
              {i + 1}
            </Link>
          );
        })}
      </div>
      <div className="row mt">
        <span className="badge v-normal">{t("verdict.normal")}</span>
        <span className="badge v-worth_a_look">{t("verdict.worth_a_look").split(":")[0]}</span>
        <span className="badge v-large_gap">{t("verdict.large_gap").split(":")[0]}</span>
      </div>
    </main>
  );
}
