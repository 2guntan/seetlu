import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { get, patch, post, put, type AlertRule, type Shop, type User } from "../api/client";
import { ErrorMessage, Loading } from "../components/states";
import { useAuth } from "../lib/use-auth";
import { hhmm } from "../lib/format";
import { normalizePhone } from "../lib/parse";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const ALERTS: AlertRule["type"][] = ["not_opened", "unattended", "after_hours_motion", "kit_offline"];
const hm = (v: string) => v.slice(0, 5);

function ShopForm({ shop }: { shop: Shop }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [form, setForm] = useState(() => ({
    hours: Object.fromEntries(DAYS.map((d) => [d, shop.opening_hours[d]?.[0] ?? null])) as Record<string, string[] | null>,
    report_time: hm(shop.report_time),
    cash_prompt_time: hm(shop.cash_prompt_time),
    quiet_start: shop.quiet_hours.start ?? "22:00",
    quiet_end: shop.quiet_hours.end ?? "07:00",
    service_min_s: shop.service_min_s,
    wait_min_s: shop.wait_min_s,
    unattended_min_s: shop.unattended_min_s,
    expected_staff: shop.expected_staff,
    cdp: shop.cdp_declaration_ref ?? "",
  }));
  const save = useMutation({
    mutationFn: () =>
      patch<Shop>(`/v1/shops/${shop.id}`, {
        opening_hours: Object.fromEntries(DAYS.map((d) => [d, form.hours[d] ? [form.hours[d]] : []])),
        report_time: form.report_time,
        cash_prompt_time: form.cash_prompt_time,
        quiet_hours: { start: form.quiet_start, end: form.quiet_end },
        service_min_s: form.service_min_s,
        wait_min_s: form.wait_min_s,
        unattended_min_s: form.unattended_min_s,
        expected_staff: form.expected_staff,
        cdp_declaration_ref: form.cdp || null,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const num = (k: "service_min_s" | "wait_min_s" | "unattended_min_s" | "expected_staff", label: string, help?: string) => (
    <label>
      {label}
      <input type="number" name={k} value={form[k]} onChange={(e) => set(k, Number(e.target.value))} />
      {help && <small className="muted">{help}</small>}
    </label>
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="card" onSubmit={submit}>
      <h2>{t("settings.hours")}</h2>
      {DAYS.map((d) => {
        const v = form.hours[d];
        return (
          <div className="row" key={d} style={{ marginBottom: 6 }}>
            <span style={{ width: 100 }}>{t(`settings.days.${d}`)}</span>
            <label className="inline" style={{ margin: 0 }}>
              <input type="checkbox" checked={!v} onChange={(e) => set("hours", { ...form.hours, [d]: e.target.checked ? null : ["08:00", "21:00"] })} />
              {t("settings.closed")}
            </label>
            {v && (
              <>
                <input type="time" aria-label={`${d}-open`} value={v[0]} onChange={(e) => set("hours", { ...form.hours, [d]: [e.target.value, v[1]] })} />
                <input type="time" aria-label={`${d}-close`} value={v[1]} onChange={(e) => set("hours", { ...form.hours, [d]: [v[0], e.target.value] })} />
              </>
            )}
          </div>
        );
      })}
      <h2>{t("settings.reportTime")}</h2>
      <div className="row">
        <label>
          {t("settings.reportTime")}
          <input type="time" name="report_time" value={form.report_time} onChange={(e) => set("report_time", e.target.value)} />
        </label>
        <label>
          {t("settings.cashPromptTime")}
          <input type="time" name="cash_prompt_time" value={form.cash_prompt_time} onChange={(e) => set("cash_prompt_time", e.target.value)} />
        </label>
      </div>
      <div className="row">
        <span>{t("settings.quietHours")}</span>
        <input type="time" aria-label="quiet-start" value={form.quiet_start} onChange={(e) => set("quiet_start", e.target.value)} />
        <input type="time" aria-label="quiet-end" value={form.quiet_end} onChange={(e) => set("quiet_end", e.target.value)} />
      </div>
      <h2>{t("settings.thresholds")}</h2>
      {num("service_min_s", t("settings.serviceMin"), t("settings.serviceHelp"))}
      {num("wait_min_s", t("settings.waitMin"), t("settings.waitHelp"))}
      {num("unattended_min_s", t("settings.unattendedMin"), t("settings.unattendedHelp"))}
      {num("expected_staff", t("settings.expectedStaff"))}
      <label>
        {t("settings.cdp")}
        <input name="cdp" value={form.cdp} onChange={(e) => set("cdp", e.target.value)} maxLength={120} />
      </label>
      <button type="submit" disabled={save.isPending}>
        {t("settings.save")}
      </button>
      {save.isSuccess && <span role="status" style={{ marginLeft: 8 }}>{t("settings.saved")}</span>}
      <ErrorMessage error={save.error} />
    </form>
  );
}

function Alerts({ shopId }: { shopId: string }) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["alerts", shopId], queryFn: () => get<AlertRule[]>(`/v1/shops/${shopId}/alert-rules`) });
  const [rules, setRules] = useState<AlertRule[] | null>(null);
  const current = rules ?? q.data ?? [];
  const save = useMutation({ mutationFn: () => put(`/v1/shops/${shopId}/alert-rules`, { rules: current }) });
  const update = (type: string, change: Partial<AlertRule>) =>
    setRules(current.map((r) => (r.type === type ? { ...r, ...change } : r)));
  if (q.isPending) return <Loading />;
  return (
    <section className="card">
      <h2>{t("settings.alerts")}</h2>
      {ALERTS.map((type) => {
        const r = current.find((x) => x.type === type);
        if (!r) return null;
        const key = Object.keys(r.params)[0];
        return (
          <div className="row" key={type} style={{ marginBottom: 8 }}>
            <label className="inline grow" style={{ margin: 0 }}>
              <input type="checkbox" name={`alert-${type}`} checked={r.enabled} onChange={(e) => update(type, { enabled: e.target.checked })} />
              {t(`alert.${type}`)}
            </label>
            {key && (
              <label className="inline" style={{ margin: 0 }}>
                {t("alert.minutes")}
                <input type="number" style={{ width: 80 }} value={r.params[key]} onChange={(e) => update(type, { params: { [key]: Number(e.target.value) } })} />
              </label>
            )}
          </div>
        );
      })}
      <button onClick={() => save.mutate()} disabled={save.isPending || !rules}>
        {t("settings.save")}
      </button>
      {save.isSuccess && <span role="status" style={{ marginLeft: 8 }}>{t("settings.saved")}</span>}
      <ErrorMessage error={save.error} />
    </section>
  );
}

function Users({ shop }: { shop: Shop }) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users", shop.id], queryFn: () => get<User[]>(`/v1/shops/${shop.id}/users`) });
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<"manager" | "staff">("staff");
  const [receives, setReceives] = useState(false);
  const invite = useMutation({
    mutationFn: () =>
      post(`/v1/shops/${shop.id}/users`, { name, phone_e164: normalizePhone(phone), role, receives_report: receives }),
    onSuccess: () => {
      setName("");
      setPhone("");
      void qc.invalidateQueries({ queryKey: ["users", shop.id] });
    },
  });
  const clipAccess = useMutation({
    mutationFn: (v: boolean) => patch(`/v1/shops/${shop.id}`, { clip_access_for_managers: v }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate();
  };
  return (
    <section className="card">
      <h2>{t("settings.users")}</h2>
      <table>
        <tbody>
          {q.data?.map((u) => (
            <tr key={u.id}>
              <td>{u.name}</td>
              <td>{u.phone_e164}</td>
              <td>{t(`settings.roles.${u.role}`)}</td>
              <td>{u.receives_report ? t("settings.receivesReport") : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {me?.user.role === "owner" && (
        <>
          <form onSubmit={submit} style={{ marginTop: 12 }}>
            <div className="row">
              <input aria-label={t("settings.name")} placeholder={t("settings.name")} value={name} onChange={(e) => setName(e.target.value)} required />
              <input aria-label="phone" type="tel" placeholder="+221…" value={phone} onChange={(e) => setPhone(e.target.value)} required />
              <select aria-label={t("settings.role")} value={role} onChange={(e) => setRole(e.target.value as "manager" | "staff")}>
                <option value="manager">{t("settings.roles.manager")}</option>
                <option value="staff">{t("settings.roles.staff")}</option>
              </select>
              <label className="inline" style={{ margin: 0 }}>
                <input type="checkbox" checked={receives} onChange={(e) => setReceives(e.target.checked)} />
                {t("settings.receivesReport")}
              </label>
              <button type="submit" disabled={invite.isPending}>
                {t("settings.invite")}
              </button>
            </div>
            <ErrorMessage error={invite.error} />
          </form>
          <label className="inline" style={{ marginTop: 12 }}>
            <input
              type="checkbox"
              name="clip-access"
              checked={me.account?.clip_access_for_managers ?? false}
              onChange={(e) => clipAccess.mutate(e.target.checked)}
            />
            {t("settings.clipAccess")}
          </label>
        </>
      )}
    </section>
  );
}

interface Phone {
  id: string;
  model: string | null;
  app_version: string | null;
  parser_current: boolean;
  last_seen_at: string | null;
}

function PairPhone({ shopId }: { shopId: string }) {
  const { t } = useTranslation();
  const phones = useQuery({ queryKey: ["phones", shopId], queryFn: () => get<Phone[]>(`/v1/shops/${shopId}/phones`) });
  const code = useMutation({ mutationFn: () => post<{ code: string; expires_at: string }>(`/v1/shops/${shopId}/phone-pairing-codes`) });
  return (
    <section className="card">
      <h2>{t("settings.pairPhone")}</h2>
      <p className="muted">{t("settings.pairHelp")}</p>
      <button onClick={() => code.mutate()} disabled={code.isPending}>
        {t("settings.pairNew")}
      </button>
      {code.data && (
        <p>
          <b data-testid="pair-code" style={{ fontSize: "2rem", letterSpacing: "0.3em" }}>
            {code.data.code}
          </b>{" "}
          <small className="muted">{t("settings.pairExpires", { time: hhmm(code.data.expires_at) })}</small>
        </p>
      )}
      <ErrorMessage error={code.error} />
      {phones.data?.map((p) => (
        <p key={p.id} className="muted">
          {p.model ?? "—"} · {p.app_version ?? "—"} · {p.last_seen_at ? t("settings.phoneSeen", { time: hhmm(p.last_seen_at) }) : "—"}
          {!p.parser_current && <> · {t("settings.parserOld")}</>}
        </p>
      ))}
    </section>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { shopId } = useParams();
  const { me } = useAuth();
  const shop = me?.shops.find((s) => s.id === shopId) ?? me?.shops[0];
  if (!shop) return <main><Loading /></main>;
  return (
    <main>
      <h1>
        {t("settings.title")} · {shop.name}
      </h1>
      <ShopForm key={shop.id} shop={shop} />
      <Alerts shopId={shop.id} />
      <Users shop={shop} />
      <PairPhone shopId={shop.id} />
    </main>
  );
}
