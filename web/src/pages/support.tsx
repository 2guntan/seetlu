import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError, get, post, put, type SupportKit, type SupportKitDetail } from "../api/client";
import { Sparkline } from "../components/sparkline";
import { ErrorMessage, Loading } from "../components/states";

const ago = (iso: string | null) =>
  iso ? new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: "Africa/Dakar" }).format(new Date(iso)) : "—";

export function SupportKitsPage() {
  const { t } = useTranslation();
  const [health, setHealth] = useState("");
  const q = useQuery({
    queryKey: ["support-kits", health],
    queryFn: () => get<SupportKit[]>("/v1/support/kits", { health: health || undefined }),
    refetchInterval: 60_000,
  });
  return (
    <main>
      <h1>{t("support.title")}</h1>
      <label className="inline">
        {t("support.health")}
        <select name="health" value={health} onChange={(e) => setHealth(e.target.value)}>
          <option value="">{t("support.all")}</option>
          {(["ok", "degraded", "offline"] as const).map((h) => (
            <option key={h} value={h}>
              {t(`support.${h}`)}
            </option>
          ))}
        </select>
      </label>
      {q.isPending && <Loading />}
      <ErrorMessage error={q.error} />
      <div className="scroll-x">
      <table>
        <thead>
          <tr>
            <th>{t("support.serial")}</th>
            <th>{t("support.shop")}</th>
            <th>{t("support.health")}</th>
            <th>{t("support.lastHeartbeat")}</th>
            <th>{t("support.versions")}</th>
            <th>{t("support.queue")}</th>
          </tr>
        </thead>
        <tbody>
          {q.data?.map((k) => (
            <tr key={k.id} data-testid={`kit-${k.serial}`}>
              <td>
                <Link to={`/support/kits/${k.id}`}>{k.serial}</Link>
              </td>
              <td>{k.shop_name ?? "—"}</td>
              <td className={`h-${k.health}`}>{t(`support.${k.health}`)}</td>
              <td>{ago(k.last_heartbeat_at)}</td>
              <td>
                {k.agent_version ?? "—"}
                {k.target_agent_version && k.target_agent_version !== k.agent_version && <> → {k.target_agent_version}</>}
              </td>
              <td>{k.queue_depth ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </main>
  );
}

export function SupportKitPage() {
  const { t } = useTranslation();
  const { kitId = "" } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["support-kit", kitId], queryFn: () => get<SupportKitDetail>(`/v1/support/kits/${kitId}`) });
  const [version, setVersion] = useState("");
  const cmd = useMutation({ mutationFn: (type: "reboot" | "snapshot") => post(`/v1/support/kits/${kitId}/commands`, { type }) });
  const target = useMutation({
    mutationFn: () => put(`/v1/support/kits/${kitId}/target-version`, { version: version || null }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["support-kit", kitId] }),
  });
  const k = q.data;
  const grantMissing = cmd.error instanceof ApiError && cmd.error.status === 403;
  return (
    <main>
      <Link to="/support/kits">‹ {t("common.back")}</Link>
      {q.isPending && <Loading />}
      <ErrorMessage error={q.error} />
      {k && (
        <>
          <h1>{t("support.kit", { serial: k.serial })}</h1>
          <p>
            <span className={`h-${k.health}`}>{t(`support.${k.health}`)}</span> · {k.shop_name ?? "—"} · {ago(k.last_heartbeat_at)}
          </p>
          <section className="card">
            <h2>{t("support.heartbeats")}</h2>
            <Sparkline label={t("support.heartbeats")} values={k.heartbeats_7d.map((p) => p.count)} />
            <Sparkline label={t("support.queue")} values={k.heartbeats_7d.map((p) => p.max_queue_depth)} />
          </section>
          <section className="card">
            <h2>{t("support.commands")}</h2>
            <div className="row">
              <button className="ghost" onClick={() => cmd.mutate("reboot")}>{t("support.reboot")}</button>
              <button className="ghost" onClick={() => cmd.mutate("snapshot")}>
                {t("support.snapshot")}
              </button>
            </div>
            {cmd.isSuccess && <p role="status">{t("support.queued")}</p>}
            {grantMissing && <p className="error">{t("support.grantRequired")}</p>}
            <div className="row mt">
              <label className="inline grow m0">
                {t("support.targetVersion")}
                <input name="version" placeholder={k.target_agent_version ?? k.agent_version ?? ""} value={version} onChange={(e) => setVersion(e.target.value)} />
              </label>
              <button onClick={() => target.mutate()} disabled={target.isPending}>
                {t("support.setTarget")}
              </button>
            </div>
            <ErrorMessage error={target.error} />
          </section>
          <section className="card">
            <h2>{t("support.config")}</h2>
            <pre>{JSON.stringify(k.config, null, 2)}</pre>
          </section>
        </>
      )}
    </main>
  );
}
