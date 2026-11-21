/** Pure helpers shared by pages (kept out of component files for fast refresh). */

/** AC-F7-2: phone number (+221 by default, +225 allowed) → one-time code over WhatsApp. */
export function normalizePhone(raw: string): string {
  const digits = raw.replace(/[^\d+]/g, "");
  if (digits.startsWith("+")) return digits;
  if (digits.startsWith("00")) return `+${digits.slice(2)}`;
  return `+221${digits}`;
}

/** QR payload: "seetlu:<serial>:<claim token>" (or JSON {serial, claim_token}). */
export function parseQr(text: string): { serial: string; claim_token: string } | null {
  const t = text.trim();
  if (t.startsWith("{")) {
    try {
      const j = JSON.parse(t) as { serial?: string; claim_token?: string };
      return j.serial && j.claim_token ? { serial: j.serial, claim_token: j.claim_token } : null;
    } catch {
      return null;
    }
  }
  const m = /^seetlu:([^:]+):(.+)$/.exec(t);
  return m ? { serial: m[1], claim_token: m[2] } : null;
}

const COLOURED = new Set(["normal", "worth_a_look", "large_gap"]);

export function verdictClass(v: string | null | undefined): string {
  return v && COLOURED.has(v) ? v : "other";
}

