/** Typed API client (docs/04). Tokens live in localStorage; a 401 triggers one refresh, then logout. */

const ACCESS = "seetlu.access";
const REFRESH = "seetlu.refresh";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly type: string,
    readonly detail: string,
  ) {
    super(detail || type);
  }
}

export const tokens = {
  get access(): string | null {
    return localStorage.getItem(ACCESS);
  },
  set(access: string, refresh: string): void {
    localStorage.setItem(ACCESS, access);
    localStorage.setItem(REFRESH, refresh);
  },
  clear(): void {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  },
};

let onLogout: () => void = () => {};
export function setLogoutHandler(fn: () => void): void {
  onLogout = fn;
}

async function refresh(): Promise<boolean> {
  const rt = localStorage.getItem(REFRESH);
  if (!rt) return false;
  const r = await fetch("/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!r.ok) return false;
  const t = (await r.json()) as Tokens;
  tokens.set(t.access_token, t.refresh_token);
  return true;
}

type Query = Record<string, string | number | undefined>;

export async function api<T>(
  method: string,
  path: string,
  opts: { body?: unknown; query?: Query; retry?: boolean } = {},
): Promise<T> {
  const qs = opts.query
    ? "?" +
      new URLSearchParams(
        Object.entries(opts.query)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  const r = await fetch(path + qs, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (r.status === 401 && opts.retry !== false && !path.startsWith("/v1/auth/")) {
    if (await refresh()) return api<T>(method, path, { ...opts, retry: false });
    tokens.clear();
    onLogout();
  }
  if (!r.ok) {
    let type = "about:blank";
    let detail = "";
    try {
      const p = (await r.json()) as { type?: string; detail?: string; title?: string };
      type = p.type ?? type;
      detail = p.detail ?? p.title ?? "";
    } catch {
      /* not problem+json */
    }
    throw new ApiError(r.status, type, detail);
  }
  if (r.status === 204) return undefined as T;
  const text = await r.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const get = <T>(path: string, query?: Query) => api<T>("GET", path, { query });
export const post = <T>(path: string, body?: unknown, query?: Query) => api<T>("POST", path, { body, query });
export const put = <T>(path: string, body: unknown) => api<T>("PUT", path, { body });
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, { body });
export const del = <T>(path: string) => api<T>("DELETE", path);

// ---------- types (docs/04) ----------
export interface Tokens {
  access_token: string;
  refresh_token: string;
}
export type Role = "owner" | "manager" | "staff" | "installer" | "support";
export type Verdict =
  | "learning"
  | "normal"
  | "worth_a_look"
  | "large_gap"
  | "not_enough_activity"
  | "incomplete_data";
export type Confidence = "high" | "medium" | "low";

export interface User {
  id: string;
  name: string;
  phone_e164: string;
  role: Role;
  language: "fr" | "wo" | "en";
  receives_report: boolean;
  active: boolean;
}
export interface Shop {
  id: string;
  account_id: string;
  name: string;
  category: string;
  address: string | null;
  timezone: string;
  opening_hours: Record<string, string[][]>;
  report_time: string;
  cash_prompt_time: string;
  quiet_hours: { start?: string; end?: string };
  expected_staff: number;
  service_min_s: number;
  wait_min_s: number;
  unattended_min_s: number;
  cdp_declaration_ref: string | null;
  status: "installing" | "active" | "paused" | "closed";
}
export interface Me {
  user: User;
  account: { id: string; name: string; clip_access_for_managers: boolean } | null;
  shops: Shop[];
}
export interface Moment {
  rank: number;
  kind: "after_hours_motion" | "unattended" | "wait" | "low_rps_hour";
  started_at: string;
  duration_s: number;
  camera: string;
  hour?: number | null;
}
export interface Report {
  id: string | null;
  local_date: string;
  visitors_in: number | null;
  served: number | null;
  waits: number | null;
  unattended_min: number | null;
  busiest_hour: number | null;
  sales_count: number;
  sales_xof: number;
  sales_by_source: Record<string, number>;
  cash_declared_xof: number | null;
  rps_xof: string | null;
  verdict: Verdict | null;
  confidence: Record<string, Confidence>;
  missing_hours: number[];
  moments: Moment[];
  sent_at: string | null;
  updated_after_send: boolean;
  corrections: { metric: string; corrected_value: number; reported_value: number | null }[];
}
export interface Today extends Report {
  counter: { state: "empty" | "staffed" | "unknown"; since: string | null };
  last_heartbeat_at: string | null;
}
export interface Hour {
  hour: number;
  entries: number;
  served: number;
  waits: number;
  sales_xof: number;
  missing: boolean;
}
export interface Sale {
  id: string;
  source: string;
  amount_xof: number;
  occurred_at: string;
  local_date: string;
  entered_by: string | null;
  voided_at: string | null;
}
export interface Clip {
  id: string;
  kind: string;
  event_id: string | null;
  duration_s: number | null;
  saved: boolean;
  expires_at: string | null;
  created_at: string;
}
export interface ClipUrl {
  id: string;
  url: string;
  duration_s: number | null;
}
export interface ClipRequest {
  status: "queued" | "ready";
  clip_id?: string | null;
  command_id?: string | null;
}
export interface Command {
  id: string;
  status: string;
  clip_id: string | null;
}
export interface AuditRow {
  id: string;
  actor_name: string | null;
  actor_role: Role | null;
  action: string;
  target_type: string | null;
  detail: Record<string, unknown>;
  at: string;
}
export interface AlertRule {
  type: "not_opened" | "unattended" | "after_hours_motion" | "kit_offline";
  enabled: boolean;
  params: Record<string, number>;
}
export interface Kit {
  id: string;
  serial: string;
  shop_id: string | null;
  status: string;
  config_version: number;
}
export interface CountCheck {
  id: string;
  started_at: string;
  manual_count: number | null;
  agent_count: number | null;
  error_pct: string | null;
  passed: boolean | null;
  override_reason: string | null;
}
export interface SupportKit {
  id: string;
  serial: string;
  shop_name: string | null;
  status: string;
  health: "ok" | "degraded" | "offline";
  agent_version: string | null;
  frigate_version: string | null;
  target_agent_version: string | null;
  config_version: number;
  last_heartbeat_at: string | null;
  queue_depth: number | null;
  min_fps: number | null;
}
export interface SupportKitDetail extends SupportKit {
  heartbeats_7d: { hour: string; count: number; max_queue_depth: number | null; max_cpu_temp_c: number | null }[];
  config: Record<string, unknown>;
}
export type ZoneType = "door_line" | "customer_side" | "staff_side" | "ignore";
export interface Zone {
  type: ZoneType;
  geometry: number[][];
  inward_side?: "left" | "right" | null;
}
export interface CameraIn {
  name: string;
  role: "door" | "counter";
  zones: Zone[];
}
