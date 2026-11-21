import { useTranslation } from "react-i18next";

import type { Hour } from "../api/client";

/** Lightweight SVG bars (no chart library, AC-F7-3). Missing hours are hatched, never drawn as 0. */
export function HourlyBars({ hours, open }: { hours: Hour[]; open?: [number, number] }) {
  const { t } = useTranslation();
  const [a, b] = open ?? [
    Math.min(...hours.filter((h) => h.entries || h.served || h.sales_xof || h.missing).map((h) => h.hour), 8),
    Math.max(...hours.filter((h) => h.entries || h.served || h.sales_xof || h.missing).map((h) => h.hour + 1), 21),
  ];
  const shown = hours.filter((h) => h.hour >= a && h.hour < b);
  const maxCount = Math.max(1, ...shown.map((h) => Math.max(h.entries, h.served)));
  const maxMoney = Math.max(1, ...shown.map((h) => h.sales_xof));
  const W = 320;
  const H = 140;
  const bw = W / Math.max(1, shown.length);
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label={t("day.hourly")} width="100%">
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#9ca3af" strokeWidth="2" />
          </pattern>
        </defs>
        {shown.map((h, i) => {
          const x = i * bw;
          if (h.missing)
            return (
              <g key={h.hour} data-testid={`hour-${h.hour}`} data-missing="true">
                <rect x={x + 1} y={0} width={bw - 2} height={H} fill="url(#hatch)" opacity={0.5} />
                <text x={x + bw / 2} y={H + 14} fontSize="9" textAnchor="middle" fill="#6b7280">{h.hour}</text>
              </g>
            );
          const e = (h.entries / maxCount) * H;
          const s = (h.served / maxCount) * H;
          const mo = (h.sales_xof / maxMoney) * H;
          const third = (bw - 2) / 3;
          return (
            <g key={h.hour} data-testid={`hour-${h.hour}`}>
              <rect x={x + 1} y={H - e} width={third} height={e} fill="#93c5fd" />
              <rect x={x + 1 + third} y={H - s} width={third} height={s} fill="#0f766e" />
              <rect x={x + 1 + 2 * third} y={H - mo} width={third} height={mo} fill="#f59e0b" />
              <text x={x + bw / 2} y={H + 14} fontSize="9" textAnchor="middle" fill="#6b7280">{h.hour}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="row muted" style={{ fontSize: "0.85rem" }}>
        <span style={{ color: "#3b82f6" }}>■</span> {t("day.entries")}
        <span style={{ color: "#0f766e" }}>■</span> {t("day.served")}
        <span style={{ color: "#f59e0b" }}>■</span> {t("day.moneyHour")}
      </figcaption>
    </figure>
  );
}
