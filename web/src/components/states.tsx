import { useTranslation } from "react-i18next";

export function Loading() {
  const { t } = useTranslation();
  return <p role="status">{t("status.loading")}</p>;
}

export function ErrorMessage({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p role="alert" className="error">
      {t("status.error")}
    </p>
  );
}

export function OfflineBanner() {
  const { t } = useTranslation();
  if (typeof navigator === "undefined" || navigator.onLine) return null;
  return <div className="banner">{t("status.offline")}</div>;
}
