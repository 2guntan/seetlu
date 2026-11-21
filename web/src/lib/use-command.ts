import { useEffect, useState } from "react";

import { get, type ClipUrl, type Command } from "../api/client";

/** Poll an edge command (snapshot/clip) until it yields a clip, then fetch its audited signed URL. */
export function useCommandClip(commandId: string | null | undefined, intervalMs = 2000) {
  const [clip, setClip] = useState<ClipUrl | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!commandId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const cmd = await get<Command>(`/v1/commands/${commandId}`);
        if (stop) return;
        if (cmd.clip_id) {
          setClip(await get<ClipUrl>(`/v1/clips/${cmd.clip_id}`));
          return;
        }
        if (cmd.status === "failed" || cmd.status === "expired") {
          setFailed(true);
          return;
        }
      } catch {
        /* keep polling */
      }
      timer = setTimeout(() => void tick(), intervalMs);
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [commandId, intervalMs]);
  return { clip, failed };
}
