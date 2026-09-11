/** Formatting shared by server and client. Always UTC, so the server render and hydration agree. */

const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "UTC" });

export function fmtDate(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateFmt.format(d);
}

export function fmtTime(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${timeFmt.format(d)}Z`;
}

export function fmtCount(n: number): string {
  return n >= 10_000 ? `${(n / 1000).toFixed(1)}K` : n.toLocaleString("en-US");
}

export function fmtUsd(n: number | null): string {
  return n == null ? "-" : n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
