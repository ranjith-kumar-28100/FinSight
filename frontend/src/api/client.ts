import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  timeout: 120_000,
});

export function dateParams(
  start: string | null,
  end: string | null
): Record<string, string> {
  const out: Record<string, string> = {};
  if (start) out.start = start;
  if (end) out.end = end;
  return out;
}
