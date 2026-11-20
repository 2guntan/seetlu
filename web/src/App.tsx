import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { fetchHealth } from "./api/client";

export function App() {
  const { t } = useTranslation();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 16, maxWidth: 640, margin: "0 auto" }}>
      <h1>{t("app.name")}</h1>
      <p>{t("app.tagline")}</p>
      <p role="status">
        {health.isPending ? t("status.loading") : health.isSuccess ? t("status.apiOk") : t("status.apiDown")}
      </p>
    </main>
  );
}
