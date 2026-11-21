import { useRef, type PointerEvent } from "react";

import type { Zone, ZoneType } from "../api/client";

const COLOURS: Record<ZoneType, string> = {
  door_line: "#f43f5e",
  customer_side: "#3b82f6",
  staff_side: "#22c55e",
  ignore: "#9ca3af",
};

/** Tap points on the snapshot; coordinates are normalised to 0..1 (what the API and agent expect). */
export function ZoneEditor({
  imageUrl,
  zones,
  drawing,
  onPoint,
}: {
  imageUrl: string | null;
  zones: Zone[];
  drawing: ZoneType | null;
  onPoint: (p: [number, number]) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const tap = (e: PointerEvent<HTMLDivElement>) => {
    if (!drawing || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    onPoint([Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000]);
  };
  return (
    <div className="zone-canvas" ref={ref} onPointerDown={tap} data-testid="zone-canvas">
      {imageUrl ? <img src={imageUrl} alt="" draggable={false} /> : <div className="placeholder" />}
      <svg viewBox="0 0 1 1" preserveAspectRatio="none">
        {zones.map((z, i) => {
          const pts = z.geometry.map((p) => p.join(",")).join(" ");
          const c = COLOURS[z.type];
          return z.type === "door_line" ? (
            <polyline key={i} points={pts} stroke={c} strokeWidth={0.008} fill="none" />
          ) : (
            <polygon key={i} points={pts} stroke={c} strokeWidth={0.005} fill={c} fillOpacity={0.25} />
          );
        })}
        {zones.flatMap((z, i) =>
          z.geometry.map((p, j) => <circle key={`${i}-${j}`} cx={p[0]} cy={p[1]} r={0.012} fill={COLOURS[z.type]} />),
        )}
      </svg>
    </div>
  );
}
