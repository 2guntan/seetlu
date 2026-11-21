/** Missing days (null) break the line instead of dropping to 0 (CLAUDE.md rule 3). */
export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const W = 300;
  const H = 40;
  const max = Math.max(1, ...values.map((v) => v ?? 0));
  const step = W / Math.max(1, values.length - 1);
  const runs: string[][] = [[]];
  values.forEach((v, i) => {
    if (v === null) {
      if (runs[runs.length - 1].length) runs.push([]);
      return;
    }
    runs[runs.length - 1].push(`${(i * step).toFixed(1)},${(H - (v / max) * H).toFixed(1)}`);
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={label}>
      {runs
        .filter((r) => r.length)
        .map((r, i) => (
          <polyline key={i} className="spark" points={r.join(" ")} fill="none" strokeWidth="2" />
        ))}
    </svg>
  );
}
