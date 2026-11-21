/** Quick-log entries typed while offline are kept here and replayed with the same client_id (idempotent). */
import { post } from "../api/client";

const KEY = "seetlu.sales-queue";

export interface QueuedSale {
  shopId: string;
  body: { client_id: string; source: "quick_log" | "cash_declaration"; amount_xof: number; occurred_at: string };
}

function read(): QueuedSale[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as QueuedSale[];
  } catch {
    return [];
  }
}

function write(items: QueuedSale[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* storage full or blocked */
  }
}

export function enqueue(item: QueuedSale): void {
  write([...read(), item]);
}

export function pending(): QueuedSale[] {
  return read();
}

export async function flush(): Promise<number> {
  let sent = 0;
  const left: QueuedSale[] = [];
  for (const item of read()) {
    try {
      await post(`/v1/shops/${item.shopId}/sales`, item.body);
      sent += 1;
    } catch {
      left.push(item);
    }
  }
  write(left);
  return sent;
}

/** Browser UUIDv7 (RFC 9562): 48-bit ms timestamp, version 7, variant 10, random rest. */
export function uuid7(now = Date.now()): string {
  const b = crypto.getRandomValues(new Uint8Array(16));
  let ms = now;
  for (let i = 5; i >= 0; i--) {
    b[i] = ms % 256;
    ms = Math.floor(ms / 256);
  }
  b[6] = 0x70 | (b[6] & 0x0f);
  b[8] = 0x80 | (b[8] & 0x3f);
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
