import { addDays, count, hourRanges, money } from "./format";
import { uuid7 } from "./offline-queue";
import { normalizePhone, parseQr, verdictClass } from "./parse";

describe("format", () => {
  it("never shows zero for missing data (rule 3)", () => {
    expect(count(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(count(0)).toBe("0");
  });
  it("formats integer XOF with French grouping", () => {
    expect(money(262500)).toBe("262 500 F");
  });
  it("merges missing hours into ranges", () => {
    expect(hourRanges([14, 15, 16, 9])).toBe("9h, 14h–17h");
  });
  it("adds days across months", () => {
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
  });
});

describe("login phone (AC-F7-2)", () => {
  it("defaults to +221 and keeps +225", () => {
    expect(normalizePhone("77 123 45 67")).toBe("+221771234567");
    expect(normalizePhone("+225 07 00 00 00 00")).toBe("+2250700000000");
    expect(normalizePhone("00221771234567")).toBe("+221771234567");
  });
});

describe("installer QR (AC-F8-1)", () => {
  it("reads serial and claim token", () => {
    expect(parseQr("seetlu:SN-001:abc:def")).toEqual({ serial: "SN-001", claim_token: "abc:def" });
    expect(parseQr('{"serial":"S","claim_token":"T"}')).toEqual({ serial: "S", claim_token: "T" });
    expect(parseQr("hello")).toBeNull();
  });
});

describe("history colours (AC-F7-1)", () => {
  it("only three verdicts get a colour", () => {
    expect(verdictClass("normal")).toBe("normal");
    expect(verdictClass("large_gap")).toBe("large_gap");
    expect(verdictClass("incomplete_data")).toBe("other");
    expect(verdictClass(null)).toBe("other");
  });
});

describe("uuid7", () => {
  it("is version 7, variant 10, and sortable by time", () => {
    const a = uuid7(1_700_000_000_000);
    const b = uuid7(1_700_000_000_001);
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(a < b).toBe(true);
  });
});
