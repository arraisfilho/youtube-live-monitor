import { t, translateServer } from "./i18n";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-YLM-Request"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? translateServer(data.detail) : t("Falha na comunicação com o servidor");
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export type Metrics = {
  concurrent_viewers: number | null;
  peak_viewers: number | null;
  average_viewers: number | null;
  viewer_change_per_minute: number | null;
  viewer_change_percent: number | null;
  total_views: number | null;
  new_views_per_minute: number | null;
  views_since_start: number | null;
  like_count: number | null;
  likes_per_minute: number | null;
  comment_count: number | null;
  comments_per_minute: number | null;
  engagement_rate: number | null;
  elapsed_seconds: number | null;
  scheduled_delay_seconds: number | null;
  time_to_peak_seconds: number | null;
  peak_timestamp: number | null;
  viewer_count_available: number | null;
  seconds_until_start: number | null;
  overdue_seconds: number | null;
};

export type Live = {
  video_id: string;
  youtube_url: string;
  thumbnail: string;
  title: string;
  channel_name: string;
  display_name: string;
  status: number;
  status_name: string;
  scheduled_start: string | null;
  actual_start: string | null;
  actual_end: string | null;
  last_update: number | null;
  metrics: Metrics;
  url?: string;
  enabled?: boolean;
  share_enabled?: boolean;
  share_path?: string | null;
};

export type Series = {
  step: number;
  start: number;
  end: number;
  range: number;
  aggregated: boolean;
  series: Record<string, [number, number][]>;
};

export type Health = {
  api_calls_total: number;
  videos_polled_total: number;
  api_calls_today: number;
  scheduled_polls_skipped_total: number;
  last_success_age: number | null;
  consecutive_errors: number;
  db_size_bytes: number;
  lives: Record<string, number>;
  quota: { used: number; limit: number; paused: boolean; paused_until: number | null };
  api_key_configured: boolean;
  collector: { version: string; interval: number; alive: boolean; last_cycle_at: number | null };
};

export type Settings = {
  daily_quota: number;
  live_interval: number;
  display_timezone: string;
  api_key: { configured: boolean; masked: string | null };
};

export type Session = { authenticated: boolean; must_change_password: boolean; version: string };
