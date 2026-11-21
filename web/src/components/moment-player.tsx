import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, get, post, type ClipRequest, type ClipUrl, type Moment } from "../api/client";
import { hhmm } from "../lib/format";
import { useCommandClip } from "../lib/use-command";

export function MomentPlayer({ reportId, moment, timeZone }: { reportId: string; moment: Moment; timeZone: string }) {
  const { t } = useTranslation();
  const [commandId, setCommandId] = useState<string | null>(null);
  const [ready, setReady] = useState<ClipUrl | null>(null);
  const [state, setState] = useState<"idle" | "waiting" | "unavailable">("idle");
  const polled = useCommandClip(commandId);
  const clip = ready ?? polled.clip;

  async function play() {
    setState("waiting");
    try {
      const r = await post<ClipRequest>(`/v1/moments/${reportId}/${moment.rank}/clip`);
      if (r.status === "ready" && r.clip_id) setReady(await get<ClipUrl>(`/v1/clips/${r.clip_id}`));
      else setCommandId(r.command_id ?? null);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 410 || e.status === 404)) setState("unavailable");
      else setState("idle");
    }
  }

  return (
    <li className="card" data-testid={`moment-${moment.rank}`}>
      <div className="row">
        <b className="grow">
          {moment.rank}. {t(`moment.${moment.kind}`)} · {hhmm(moment.started_at, timeZone)}
        </b>
        {!clip && state === "idle" && <button onClick={() => void play()}>{t("moment.play")}</button>}
      </div>
      {!clip && state === "waiting" && !polled.failed && <p className="muted">{t("moment.preparing")}</p>}
      {(state === "unavailable" || polled.failed) && <p className="muted">{t("moment.unavailable")}</p>}
      {clip && <video src={clip.url} controls autoPlay playsInline data-testid="clip-video" />}
    </li>
  );
}
