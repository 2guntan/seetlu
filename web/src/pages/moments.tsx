import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, del, get, post, type Clip, type ClipUrl } from "../api/client";
import { ShopPicker } from "../components/shop-picker";
import { ErrorMessage, Loading } from "../components/states";
import { dateLabel, hhmm } from "../lib/format";
import { useShopChoice } from "../lib/use-shop";

function ClipRow({ clip, shopId, timeZone }: { clip: Clip; shopId: string; timeZone: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [url, setUrl] = useState<string | null>(null);
  const toggle = useMutation({
    mutationFn: () => (clip.saved ? del(`/v1/clips/${clip.id}/save`) : post(`/v1/clips/${clip.id}/save`)),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["clips", shopId] }),
  });
  const play = async () => setUrl((await get<ClipUrl>(`/v1/clips/${clip.id}`)).url); // audit-logged server side
  const limit = toggle.error instanceof ApiError && toggle.error.status === 409;
  return (
    <li data-testid={`clip-${clip.id}`}>
      <div className="row">
        <span className="grow stack">
          <b className="num-inline">{hhmm(clip.created_at, timeZone)}</b>
          <span className="muted small cap">{dateLabel(clip.created_at.slice(0, 10), i18n.language)}</span>
          {clip.saved && <span className="badge">{t("moments.saved")}</span>}
        </span>
        {!url && (
          <button className="ghost" onClick={() => void play()}>
            {t("moment.play")}
          </button>
        )}
        <button className="ghost compact" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
          {clip.saved ? t("moments.unsave") : t("moments.save")}
        </button>
      </div>
      {!clip.saved && clip.expires_at && (
        <small className="muted">{t("moments.expires", { date: dateLabel(clip.expires_at.slice(0, 10), i18n.language) })}</small>
      )}
      {limit && <p className="error">{t("moments.limit")}</p>}
      {url && <video src={url} controls autoPlay playsInline />}
    </li>
  );
}

export function MomentsPage() {
  const { t } = useTranslation();
  const [shop, choose, shops] = useShopChoice();
  const q = useQuery({
    queryKey: ["clips", shop?.id],
    queryFn: () => get<Clip[]>(`/v1/shops/${shop?.id}/clips`),
    enabled: !!shop,
  });
  return (
    <main>
      <h1>{t("moments.title")}</h1>
      <ShopPicker shop={shop} shops={shops} onChange={choose} />
      {q.isPending && shop && <Loading />}
      <ErrorMessage error={q.error} />
      {q.data?.length === 0 && <p className="muted">{t("moments.empty")}</p>}
      <ul className="plain list surface">
        {shop && q.data?.map((c) => <ClipRow key={c.id} clip={c} shopId={shop.id} timeZone={shop.timezone} />)}
      </ul>
    </main>
  );
}
