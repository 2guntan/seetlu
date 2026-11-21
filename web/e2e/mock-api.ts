import type { Page, Route } from "@playwright/test";

export const SHOP = "01a1fafe-f9c8-73cb-a279-549c18f65a38";
export const KIT = "01a1fafe-0000-7000-8000-000000000001";
export const REPORT = "01a1fafe-0000-7000-8000-0000000000aa";
export const CLIP = "01a1fafe-0000-7000-8000-0000000000cc";
export const DAY = "2026-11-17";

type Role = "owner" | "installer";

const shop = {
  id: SHOP,
  account_id: "acc",
  name: "Boutique Awa",
  category: "boutique",
  address: "Médina",
  timezone: "Africa/Dakar",
  opening_hours: { mon: [["08:00", "21:00"]], tue: [["08:00", "21:00"]], wed: [["08:00", "21:00"]], thu: [["08:00", "21:00"]], fri: [["08:00", "21:00"]], sat: [["08:00", "21:00"]], sun: [] },
  report_time: "21:30:00",
  cash_prompt_time: "21:00:00",
  quiet_hours: { start: "22:00", end: "07:00" },
  expected_staff: 1,
  service_min_s: 20,
  wait_min_s: 120,
  unattended_min_s: 300,
  cdp_declaration_ref: null as string | null,
  status: "active",
};

const report = {
  id: REPORT,
  local_date: DAY,
  visitors_in: 84,
  served: 61,
  waits: 3,
  unattended_min: 12,
  busiest_hour: 18,
  sales_count: 40,
  sales_xof: 262500,
  sales_by_source: { wave: 120000, quick_log: 142500 },
  cash_declared_xof: 140000,
  rps_xof: "4303.28",
  verdict: "normal",
  confidence: { visitors_in: "high", served: "high", sales: "high" },
  missing_hours: [14, 15],
  moments: [{ rank: 1, kind: "unattended", started_at: "2026-11-17T16:05:00Z", duration_s: 420, camera: "counter" }],
  sent_at: "2026-11-17T21:30:00Z",
  updated_after_send: false,
  corrections: [] as unknown[],
};

export interface MockState {
  calls: { method: string; path: string; body: unknown }[];
  shop: typeof shop;
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

/** In-memory fake of the parts of docs/04 the journeys use. */
export async function mockApi(page: Page, role: Role = "owner", opts: { signedIn?: boolean } = {}): Promise<MockState> {
  const state: MockState = { calls: [], shop: { ...shop, status: role === "installer" ? "installing" : "active" } };
  let commandPolls = 0;
  let checkStarted = "";
  if (opts.signedIn !== false) {
    await page.addInitScript(() => {
      localStorage.setItem("seetlu.access", "test-access");
      localStorage.setItem("seetlu.refresh", "test-refresh");
    });
  }
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    const body = req.postDataJSON() as unknown;
    state.calls.push({ method, path, body });
    const user = { id: "u1", name: role === "owner" ? "Awa" : "Moussa", phone_e164: "+221771234567", role, language: "fr", receives_report: true, active: true };

    if (path === "/v1/auth/otp/request") return route.fulfill({ status: 204 });
    if (path === "/v1/auth/otp/verify")
      return (body as { code: string }).code === "123456"
        ? json(route, { access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 900 })
        : json(route, { type: "https://seetlu.sn/problems/bad-code", status: 401 }, 401);
    if (path === "/v1/me")
      return json(route, { user, account: { id: "acc", name: "Awa", clip_access_for_managers: false }, shops: [state.shop] });
    if (path === `/v1/shops/${SHOP}/today`)
      return json(route, { ...report, id: null, verdict: null, missing_hours: [], counter: { state: "empty", since: new Date(Date.now() - 600_000).toISOString() }, last_heartbeat_at: new Date().toISOString() });
    if (path === `/v1/shops/${SHOP}/reports`) return json(route, url.searchParams.get("from")?.startsWith("2026-11") ? [report] : []);
    if (path === `/v1/shops/${SHOP}/hourly`)
      return json(route, Array.from({ length: 24 }, (_, h) => ({ hour: h, entries: h >= 8 && h < 21 ? 6 : 0, served: h >= 8 && h < 21 ? 4 : 0, waits: 0, sales_xof: h >= 8 && h < 21 ? 20000 : 0, missing: h === 14 || h === 15 })));
    if (path === `/v1/shops/${SHOP}/sales`) return json(route, [{ id: "s1", source: "wave", amount_xof: 5000, occurred_at: "2026-11-17T10:00:00Z", local_date: DAY, entered_by: null, voided_at: null }]);
    if (path === `/v1/moments/${REPORT}/1/clip`) return json(route, { status: "queued", command_id: "cmd-1" }, 202);
    if (path.startsWith("/v1/commands/")) {
      commandPolls += 1;
      return json(route, { id: "cmd", status: commandPolls > 1 ? "done" : "sent", clip_id: commandPolls > 1 ? CLIP : null });
    }
    if (path === `/v1/clips/${CLIP}`) return json(route, { id: CLIP, kind: "clip", url: "/clip.mp4", expires_in_s: 900, duration_s: 30 });
    if (path === `/v1/shops/${SHOP}` && method === "PATCH") {
      Object.assign(state.shop, body);
      return json(route, state.shop);
    }
    if (path === `/v1/shops/${SHOP}/alert-rules`)
      return json(route, method === "PUT" ? (body as { rules: unknown }).rules : [
        { type: "not_opened", enabled: true, params: { grace_min: 30 } },
        { type: "unattended", enabled: true, params: { min: 10 } },
        { type: "after_hours_motion", enabled: true, params: {} },
        { type: "kit_offline", enabled: true, params: { min: 30 } },
      ]);
    if (path === `/v1/shops/${SHOP}/users`)
      return method === "POST" ? json(route, { ...user, id: "u2", ...(body as object) }, 201) : json(route, [user]);
    if (path === `/v1/shops/${SHOP}/phone-pairing-codes`) return json(route, { code: "482913", expires_at: new Date(Date.now() + 600_000).toISOString() }, 201);
    if (path === `/v1/shops/${SHOP}/phones`) return json(route, []);
    // installer
    if (path === "/v1/shops" && method === "POST") return json(route, { ...state.shop, ...(body as object) }, 201);
    if (path === "/v1/kits/claim")
      return (body as { claim_token: string }).claim_token === "good-token"
        ? json(route, { id: KIT, serial: "SN-0001", shop_id: SHOP, status: "installing", config_version: 1 })
        : json(route, { type: "https://seetlu.sn/problems/not-found", status: 404 }, 404);
    if (path === `/v1/shops/${SHOP}/snapshot`) return json(route, { status: "queued", command_id: "snap-1" }, 202);
    if (path === `/v1/kits/${KIT}/cameras`) return json(route, body);
    if (path === `/v1/kits/${KIT}/count-checks`) {
      checkStarted = new Date().toISOString();
      return json(route, { id: "chk", started_at: checkStarted, manual_count: null, agent_count: null, error_pct: null, passed: null, override_reason: null }, 201);
    }
    if (path === "/v1/count-checks/chk/stop") {
      const n = (body as { manual_count: number }).manual_count;
      return json(route, { id: "chk", started_at: checkStarted, manual_count: n, agent_count: n + 1, error_pct: ((100 / n) || 0).toFixed(2), passed: n >= 20, override_reason: null });
    }
    if (path === `/v1/kits/${KIT}/activate`)
      return state.shop.cdp_declaration_ref
        ? json(route, { id: KIT, serial: "SN-0001", shop_id: SHOP, status: "active", config_version: 2 })
        : json(route, { type: "https://seetlu.sn/problems/cdp-missing", status: 409 }, 409);
    return json(route, { type: "https://seetlu.sn/problems/not-found", status: 404, detail: path }, 404);
  });
  await page.route("**/clip.mp4", (r) => r.fulfill({ status: 200, contentType: "video/mp4", body: "" }));
  return state;
}
