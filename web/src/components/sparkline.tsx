export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const W = 300;
  const H = 40;
  const nums = values.map((v) => v ?? 0);
  const max = Math.max(1, ...nums);
  const step = W / Math.max(1, values.length - 1);
  const pts = nums.map((v, i) => `${(i * step).toFixed(1)},${(H - (v / max) * H).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={label}>
      <polyline points={pts} fill="none" stroke="#0f766e" strokeWidth="1.5" />
    </svg>
  );
}
