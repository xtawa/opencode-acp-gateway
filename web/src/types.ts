export type Channel = {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  providers: string[];
  free_only: boolean;
  allow_training: boolean;
  timeout_seconds: number;
  max_concurrency: number;
  aliases: Record<string, string>;
  credential_providers: string[];
  proxy_configured: boolean;
  models: Model[];
  synced_at: number | null;
  last_error: string | null;
};
export type Model = {
  id: string;
  name: string;
  provider: string;
  upstream: string;
  free: boolean;
  context: number | null;
  reasoning: boolean;
};
export type Key = {
  id: string;
  name: string;
  enabled: boolean;
  prefix: string;
  expires_at: number | null;
  rpm: number;
  daily_requests: number;
  token_limit: number;
  max_concurrency: number;
  allowed_models: string[];
};
export type Log = {
  id: string;
  model: string;
  status: string;
  code: string | null;
  started: number;
  duration_ms: number | null;
  total_tokens: number | null;
  ttft_ms: number | null;
};
