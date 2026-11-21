import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { get, post, type AuditRow } from "../api/client";
import { ErrorMessage, Loading } from "../components/states";
import { useAuth } from "../lib/use-auth";

const fmt = (iso: string) =>
  new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: "Africa/Dakar" }).format(new Date(iso));

export function AuditPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["audit"], queryFn: () => get<AuditRow[]>("/v1/audit-log", { limit: 200 }) });
  const grant = useMutation({
    mutationFn: () => post<{ expires_at: string }>("/v1/support-grants", { hours: 24 }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["audit"] }),
  });
  return (
    <main>
      <h1>{t("audit.title")}</h1>
      {me?.user.role === "owner" && (
        <p>
          <button className="ghost" onClick={() => grant.mutate()} disabled={grant.isPending}>
            {t("audit.grant")}
          </button>
          {grant.data && <span role="status"> {t("audit.granted", { time: fmt(grant.data.expires_at) })}</span>}
        </p>
      )}
      {q.isPending && <Loading />}
      <ErrorMessage error={q.error ?? grant.error} />
      {q.data?.length === 0 && <p className="muted">{t("audit.empty")}</p>}
      {q.data && q.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>{t("audit.when")}</th>
              <th>{t("audit.who")}</th>
              <th>{t("audit.what")}</th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((r) => (
              <tr key={r.id}>
                <td>{fmt(r.at)}</td>
                <td>
                  {r.actor_name ?? t("common.none")}
                  {r.actor_role && <small className="muted"> · {t(`settings.roles.${r.actor_role}`)}</small>}
                </td>
                <td>
                  <code>{r.action}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
