/** Display helpers. Money is integer XOF; missing values are never shown as 0 (rule 3). */

const nf = new Intl.NumberFormat("fr-FR");

export function money(xof: number | null | undefined): string {
  return xof === null || xof === undefined ? "—" : `${nf.format(xof)} F`;
}

export function count(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : nf.format(n);
}

/** Camera count for a partial day: a zero while hours are missing is unknown, not zero (rule 3). */
export function seen(n: number | null | undefined, missingHours: number[]): string {
  return n === 0 && missingHours.length > 0 ? "—" : count(n);
}

export function hhmm(iso: string, timeZone = "Africa/Dakar"): string {
  return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone }).format(new Date(iso));
}

export function dateLabel(isoDate: string, lang: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat(lang === "en" ? "en-GB" : "fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** "14h–16h" style list of missing hours, merged into ranges. */
export function hourRanges(hours: number[]): string {
  const sorted = [...hours].sort((a, b) => a - b);
  const out: string[] = [];
  let start = -1;
  let prev = -2;
  for (const h of [...sorted, 99]) {
    if (h !== prev + 1) {
      if (start >= 0) out.push(start === prev ? `${start}h` : `${start}h–${prev + 1}h`);
      start = h;
    }
    prev = h;
  }
  return out.join(", ");
}

export function localToday(timeZone = "Africa/Dakar"): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date());
}

export function addDays(isoDate: string, n: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}
