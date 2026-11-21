import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { del, get, post, type Sale } from "../api/client";
import { ShopPicker } from "../components/shop-picker";
import { ErrorMessage, Loading } from "../components/states";
import { useAuth } from "../lib/use-auth";
import { addDays, hhmm, localToday, money } from "../lib/format";
import { enqueue, flush, uuid7 } from "../lib/offline-queue";
import { useShopChoice } from "../lib/use-shop";

const SOURCES = ["wave", "orange_money", "free_money", "quick_log", "cash_declaration", "pos"];

export function SalesPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const [shop, choose, shops] = useShopChoice();
  const tz = shop?.timezone ?? "Africa/Dakar";
  const today = localToday(tz);
  const [date, setDate] = useState(today);
  const [source, setSource] = useState("");
  const [amount, setAmount] = useState("");
  const [queued, setQueued] = useState(false);
  const key = ["sales", shop?.id, date];
  const q = useQuery({ queryKey: key, queryFn: () => get<Sale[]>(`/v1/shops/${shop?.id}/sales`, { date }), enabled: !!shop });
  useEffect(() => {
    const online = () =>
      void flush().then((n) => {
        if (n) void qc.invalidateQueries({ queryKey: ["sales"] });
      });
    window.addEventListener("online", online);
    online();
    return () => window.removeEventListener("online", online);
  }, [qc]);
  const add = useMutation({
    mutationFn: async (amountXof: number) => {
      const body = { client_id: uuid7(), source: "quick_log" as const, amount_xof: amountXof, occurred_at: new Date().toISOString() };
      if (!shop) return;
      try {
        await post(`/v1/shops/${shop.id}/sales`, body);
        setQueued(false);
      } catch (e) {
        if (!navigator.onLine) {
          enqueue({ shopId: shop.id, body });
          setQueued(true);
          return;
        }
        throw e;
      }
    },
    onSuccess: () => {
      setAmount("");
      void qc.invalidateQueries({ queryKey: key });
    },
  });
  const voidSale = useMutation({
    mutationFn: (id: string) => del(`/v1/shops/${shop?.id}/sales/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  });
  const rows = (q.data ?? []).filter((s) => !source || s.source === source);
  const total = rows.filter((s) => !s.voided_at && s.source !== "cash_declaration").reduce((a, s) => a + s.amount_xof, 0);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = Number(amount);
    if (n > 0) add.mutate(n);
  };
  return (
    <main>
      <h1>{t("sales.title")}</h1>
      <ShopPicker shop={shop} shops={shops} onChange={choose} />
      <div className="row">
        <button className="ghost" onClick={() => setDate(addDays(date, -1))} aria-label={t("history.prev")}>‹</button>
        <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} aria-label={t("sales.date")} />
        <button className="ghost" onClick={() => setDate(addDays(date, 1))} disabled={date >= today} aria-label={t("history.next")}>›</button>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label={t("sales.source")}>
          <option value="">{t("sales.all")}</option>
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {t(`sales.src.${s}`)}
            </option>
          ))}
        </select>
      </div>
      {date === today && (
        <form className="card row bottom" onSubmit={submit}>
          <label className="grow m0">
            {t("sales.amount")}
            <input name="amount" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} />
          </label>
          <button type="submit" disabled={!amount || add.isPending}>
            {t("sales.add")}
          </button>
        </form>
      )}
      {queued && <p className="banner">{t("sales.queued")}</p>}
      <ErrorMessage error={add.error ?? q.error} />
      {q.isPending && shop && <Loading />}
      {q.data && rows.length === 0 && <p className="muted">{t("sales.empty")}</p>}
      {rows.length > 0 && (
        <div className="scroll-x">
        <table>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} data-testid={`sale-${s.id}`} className={s.voided_at ? "voided" : undefined}>
                <td>{hhmm(s.occurred_at, tz)}</td>
                <td>{t(`sales.src.${s.source}`)}</td>
                <td className="num">{money(s.amount_xof)}</td>
                <td>
                  {!s.voided_at && s.entered_by === me?.user.id && date === today && (
                    <button className="ghost" onClick={() => voidSale.mutate(s.id)}>
                      {t("sales.void")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      <p><b>{t("sales.total", { amount: money(total) })}</b></p>
    </main>
  );
}
