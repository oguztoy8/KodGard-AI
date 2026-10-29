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

export interface CommitDetail extends CommitItem {
  findings: unknown[];
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
