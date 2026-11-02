export const API_URL: string =
  import.meta.env.VITE_API_URL || "http://localhost:8000";

export interface CommitItem {
  id: number;
  sha: string;
  patch_id: string;
  author: string | null;
  committed_at: string | null;
  subject: string | null;
  repo_path: string;
  created_at: string | null;
  scan_id: number | null;
  status: "pending" | "running" | "done" | "failed";
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface FindingItem {
  id: number;
  commit_id: number;
  source: "semgrep" | "gitleaks" | "llm";
  rule_id: string | null;
  severity: "low" | "medium" | "high" | "critical";
  file: string | null;
  line: number | null;
  cwe: string | null;
  title: string | null;
  explanation: string | null;
  fix: string | null;
  status: "open" | "ignored" | "fixed";
  ignore_reason: string | null;
  fingerprint: string;
  created_at: string | null;
}

export interface CommitDetail extends CommitItem {
  findings: FindingItem[];
}

export interface CommitDocs {
  summary: string;
  detail: string;
}

export interface HealthResponse {
  status: string;
  db: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed with status ${res.status}`);
  }
  return res.json();
}

export async function fetchCommits(): Promise<CommitItem[]> {
  const res = await fetch(`${API_URL}/commits`);
  if (!res.ok) {
    throw new Error(`Failed to fetch commits (${res.status})`);
  }
  return res.json();
}

export async function fetchCommitDetail(sha: string): Promise<CommitDetail> {
  const res = await fetch(`${API_URL}/commits/${encodeURIComponent(sha)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch commit ${sha} (${res.status})`);
  }
  return res.json();
}

export async function fetchCommitDocs(sha: string): Promise<CommitDocs> {
  const res = await fetch(`${API_URL}/commits/${encodeURIComponent(sha)}/docs`);
  if (!res.ok) {
    throw new Error(`Failed to fetch docs for ${sha} (${res.status})`);
  }
  return res.json();
}

export function getExportUrl(sha: string, doc: "summary" | "detail"): string {
  return `${API_URL}/commits/${encodeURIComponent(sha)}/export?doc=${doc}`;
}

export async function patchFindingStatus(
  findingId: number,
  status: "open" | "ignored" | "fixed",
  ignoreReason?: string
): Promise<FindingItem> {
  const res = await fetch(`${API_URL}/findings/${findingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status,
      ignore_reason: ignoreReason ?? null,
    }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to update finding (${res.status})`);
  }
  return res.json();
}
