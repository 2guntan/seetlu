import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { get, post, type Hour, type Report, type Sale } from "../api/client";
import { HourlyBars } from "../components/hourly-bars";
import { MomentPlayer } from "../components/moment-player";
import { ErrorMessage, Loading } from "../components/states";
import { useAuth } from "../lib/use-auth";
import { count, dateLabel, hhmm, hourRanges, money } from "../lib/format";
import { verdictClass } from "../lib/parse";

function Metric({ label, value, conf, hero }: { label: string; value: string; conf?: string; hero?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className={hero ? "stat hero" : "stat"}>
      <small>{label}</small>
      <b>{value}</b>
      {conf && <small data-confidence={conf}>{t(`day.confidence.${conf}`)}</small>}
    </div>
  );
}

function CorrectionForm({ shopId, date, onDone }: { shopId: string; date: string; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [metric, setMetric] = useState<"visitors_in" | "served">("visitors_in");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const m = useMutation({
    mutationFn: () =>
      post(`/v1/shops/${shopId}/corrections`, {
        local_date: date,
        metric,
        corrected_value: Number(value),
        note: note || null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["reports", shopId] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <form className="card" onSubmit={submit}>
      <h2>{t("correction.title")}</h2>
      <label>
        {t("correction.metric")}
        <select value={metric} onChange={(e) => setMetric(e.target.value as "visitors_in" | "served")}>
          <option value="visitors_in">{t("day.visitors")}</option>
          <option value="served">{t("day.served")}</option>
        </select>
      </label>
      <label>
        {t("correction.value")}
        <input name="value" inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))} required />
      </label>
      <label>
        {t("correction.note")}
        <input name="note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </label>
      <div className="row">
        <button type="submit" disabled={!value || m.isPending}>
          {t("correction.save")}
        </button>
        <button type="button" className="ghost" onClick={onDone}>
          {t("correction.cancel")}
        </button>
      </div>
      <ErrorMessage error={m.error} />
    </form>
  );
}

export function DayPage() {
  const { t, i18n } = useTranslation();
  const { shopId = "", date = "" } = useParams();
  const { me } = useAuth();
  const shop = me?.shops.find((s) => s.id === shopId);
  const tz = shop?.timezone ?? "Africa/Dakar";
  const [correcting, setCorrecting] = useState(false);
  const report = useQuery({
    queryKey: ["reports", shopId, date, date],
    queryFn: () => get<Report[]>(`/v1/shops/${shopId}/reports`, { from: date, to: date }),
  });
  const hours = useQuery({ queryKey: ["hourly", shopId, date], queryFn: () => get<Hour[]>(`/v1/shops/${shopId}/hourly`, { date }) });
  const sales = useQuery({ queryKey: ["sales", shopId, date], queryFn: () => get<Sale[]>(`/v1/shops/${shopId}/sales`, { date }) });
  const r = report.data?.[0];
  const c = r?.confidence ?? {};
  const canCorrect = me?.user.role === "owner" || me?.user.role === "manager";
  return (
    <main>
      <Link to="/history">‹ {t("common.back")}</Link>
      <h1 className="cap">{shop?.name} · {dateLabel(date, i18n.language)}</h1>
      {report.isPending && <Loading />}
      <ErrorMessage error={report.error} />
      {report.isSuccess && !r && <p className="muted">{t("history.noReport")}</p>}
      {r && (
        <section className="card">
          {r.verdict && (
            <p className={`badge v-${verdictClass(r.verdict)}`} data-testid="verdict">
              {t(`verdict.${r.verdict}`, { hours: hourRanges(r.missing_hours) })}
            </p>
          )}
          {r.updated_after_send && <p className="muted">{t("day.updatedAfterSend")}</p>}
          {r.missing_hours.length > 0 && (
            <p className="banner" data-testid="missing-hours">
              {t("day.missingHours", { hours: hourRanges(r.missing_hours) })}
            </p>
          )}
          <div className="stats">
            <Metric label={t("day.sales")} value={money(r.sales_xof)} conf={c.sales} hero />
            <Metric label={t("day.visitors")} value={count(r.visitors_in)} conf={c.visitors_in} />
            <Metric label={t("day.served")} value={count(r.served)} conf={c.served} />
            <Metric label={t("day.cash")} value={money(r.cash_declared_xof)} />
            <Metric label={t("day.waits")} value={count(r.waits)} />
            <Metric label={t("day.unattended")} value={count(r.unattended_min)} />
            <Metric label={t("day.rps")} value={r.rps_xof === null ? "—" : money(Math.round(Number(r.rps_xof)))} />
          </div>
          {r.corrections.map((x) => (
            <p key={x.metric} className="muted">
              {x.metric === "served" ? t("day.served") : t("day.visitors")} —{" "}
              {t("day.corrected", { value: x.corrected_value, reported: count(x.reported_value) })}
            </p>
          ))}
          {canCorrect && !correcting && (
            <button className="ghost mt" onClick={() => setCorrecting(true)}>
              {t("day.correct")}
            </button>
          )}
        </section>
      )}
      {correcting && <CorrectionForm shopId={shopId} date={date} onDone={() => setCorrecting(false)} />}
      <h2>{t("day.hourly")}</h2>
      {hours.data && <HourlyBars hours={hours.data} />}
      <h2>{t("day.moments")}</h2>
      {r && r.id && r.moments.length > 0 ? (
        <ul className="plain list surface">
          {r.moments.map((m) => (
            <MomentPlayer key={m.rank} reportId={r.id as string} moment={m} timeZone={tz} />
          ))}
        </ul>
      ) : (
        <p className="muted">{t("day.noMoments")}</p>
      )}
      <h2>{t("day.salesList")}</h2>
      {sales.data && sales.data.length === 0 && <p className="muted">{t("sales.empty")}</p>}
      {sales.data && sales.data.length > 0 && (
        <div className="scroll-x">
        <table>
          <tbody>
            {sales.data.map((s) => (
              <tr key={s.id} className={s.voided_at ? "voided" : undefined}>
                <td>{hhmm(s.occurred_at, tz)}</td>
                <td>{t(`sales.src.${s.source}`)}</td>
                <td className="num">{money(s.amount_xof)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </main>
  );
}
