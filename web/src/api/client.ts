export interface Health {
  status: string;
  version: string;
}

export async function fetchHealth(): Promise<Health> {
  const resp = await fetch("/healthz");
  if (!resp.ok) throw new Error(`healthz ${resp.status}`);
  return (await resp.json()) as Health;
}
