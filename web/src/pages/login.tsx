import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, post, type Tokens } from "../api/client";
import { useAuth } from "../lib/use-auth";
import { normalizePhone } from "../lib/parse";

export function LoginPage() {
  const { t } = useTranslation();
  const { signIn } = useAuth();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/v1/auth/otp/request", { phone_e164: normalizePhone(phone) });
      setStep("code");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? t("login.tooMany") : t("status.error"));
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tk = await post<Tokens>("/v1/auth/otp/verify", { phone_e164: normalizePhone(phone), code: code.trim() });
      signIn(tk.access_token, tk.refresh_token);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? t("login.tooMany") : t("login.badCode"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{t("app.name")}</h1>
      <p className="muted">{t("app.tagline")}</p>
      <div className="card">
        <h2>{t("login.title")}</h2>
        {step === "phone" ? (
          <form onSubmit={(e) => void send(e)}>
            <label>
              {t("login.phone")}
              <input
                name="phone"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                placeholder="+221 77 123 45 67"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                required
              />
              <small className="muted">{t("login.phoneHelp")}</small>
            </label>
            <button type="submit" disabled={busy || phone.length < 7}>
              {t("login.send")}
            </button>
          </form>
        ) : (
          <form onSubmit={(e) => void verify(e)}>
            <label>
              {t("login.code")}
              <input
                name="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
              />
            </label>
            <div className="row">
              <button type="submit" disabled={busy || code.length < 4}>
                {t("login.verify")}
              </button>
              <button type="button" className="ghost" onClick={() => setStep("phone")}>
                {t("login.changePhone")}
              </button>
            </div>
          </form>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
