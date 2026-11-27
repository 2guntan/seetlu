import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { put, type CameraSetup, type KitSetup } from "../api/client";
import { ErrorMessage } from "./states";

/** Stream reported by the box (AC-F8-7) and the angle checklist (AC-F8-8) for one camera slot. */
export function CameraChecks({ kitId, cam }: { kitId: string; cam: CameraSetup }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [items, setItems] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(cam.angle_items.map((i) => [i, false])),
  );
  const save = useMutation({
    mutationFn: () =>
      put<KitSetup>(`/v1/kits/${kitId}/angle-checks/${cam.name}`, { role: cam.role, items }),
    onSuccess: (setup) => qc.setQueryData(["kit-setup", kitId], setup),
  });
  const s = cam.stream;
  // calm colours (DESIGN.md): ok = normal, anything to fix = worth a look, waiting = neutral
  const verdictClass = !s ? "other" : s.verdict === "ok" ? "normal" : "worth_a_look";
  return (
    <div className="stack mt" data-testid={`checks-${cam.name}`}>
      <p className={`badge v-${verdictClass}`} role="status">
        {s ? t(`install.stream.${s.verdict}`) : t("install.stream.waiting")}
      </p>
      {s?.reachable && (
        <p className="muted small num-inline">
          {s.codec?.toUpperCase()} · {s.width}×{s.height} · {s.fps ?? "—"} {t("install.stream.fps")}
        </p>
      )}
      {s && (
        <fieldset className="plain">
          <legend>{t("install.angle.title")}</legend>
          {cam.angle_items.map((item) => (
            <label key={item} className="inline">
              <input
                type="checkbox"
                checked={items[item] ?? false}
                onChange={(e) => setItems({ ...items, [item]: e.target.checked })}
              />
              {t(`install.angle.items.${item}`)}
            </label>
          ))}
          <button type="button" className="ghost" onClick={() => save.mutate()} disabled={save.isPending}>
            {t("install.angle.save")}
          </button>
        </fieldset>
      )}
      {cam.angle_passed && <p className="badge v-normal">{t("install.angle.passed")}</p>}
      {cam.addon_camera_needed && (
        <p className="banner" data-testid={`addon-${cam.name}`}>
          {t("install.angle.addon")}
        </p>
      )}
      <ErrorMessage error={save.error} />
    </div>
  );
}
