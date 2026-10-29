import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchCommits, fetchCommitDetail, CommitItem } from "../api/client";

const statusColors: Record<CommitItem["status"], { bg: string; fg: string; border: string }> = {
  pending: { bg: "rgba(94, 106, 210, 0.14)", fg: "#8f9ae8", border: "rgba(94, 106, 210, 0.35)" },
  running: { bg: "rgba(234, 179, 8, 0.14)", fg: "#facc15", border: "rgba(234, 179, 8, 0.35)" },
  done: { bg: "rgba(34, 197, 94, 0.14)", fg: "#4ade80", border: "rgba(34, 197, 94, 0.35)" },
  failed: { bg: "rgba(239, 68, 68, 0.14)", fg: "#f87171", border: "rgba(239, 68, 68, 0.35)" },
};

export function CommitList() {
  const [selectedSha, setSelectedSha] = useState<string | null>(null);

  const { data: commits, isLoading, isError, error } = useQuery({
    queryKey: ["commits"],
    queryFn: fetchCommits,
    refetchInterval: 5000,
  });

  const { data: detail } = useQuery({
    queryKey: ["commit-detail", selectedSha],
    queryFn: () => fetchCommitDetail(selectedSha!),
    enabled: Boolean(selectedSha),
  });

  if (isLoading) {
    return (
      <div style={{ padding: "24px", color: "#8a8f98" }}>
        Commit listesi yükleniyor...
      </div>
    );
  }

  if (isError) {
    return (
      <div
        style={{
          padding: "16px",
          backgroundColor: "#0f1011",
          border: "1px solid rgba(239, 68, 68, 0.4)",
          borderRadius: "8px",
          color: "#f87171",
        }}
      >
        Hata: {(error as Error).message}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          color: "#8a8f98",
          fontSize: "13px",
        }}
      >
        <span>Toplam {commits?.length ?? 0} commit izleniyor</span>
        <span>Otomatik yenileme: 5 sn</span>
      </div>

      {!commits || commits.length === 0 ? (
        <div
          style={{
            padding: "32px",
            textAlign: "center",
            backgroundColor: "#0f1011",
            border: "1px solid #1e2024",
            borderRadius: "8px",
            color: "#8a8f98",
          }}
        >
          Henüz kayıtlı commit bulunmuyor.
        </div>
      ) : (
        <div
          style={{
            backgroundColor: "#0f1011",
            border: "1px solid #1e2024",
            borderRadius: "8px",
            overflow: "hidden",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "14px",
              textAlign: "left",
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: "1px solid #1e2024",
                  color: "#8a8f98",
                  fontSize: "12px",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                <th style={{ padding: "12px 16px" }}>SHA</th>
                <th style={{ padding: "12px 16px" }}>Mesaj</th>
                <th style={{ padding: "12px 16px" }}>Yazar</th>
                <th style={{ padding: "12px 16px" }}>Repo</th>
                <th style={{ padding: "12px 16px" }}>Durum</th>
              </tr>
            </thead>
            <tbody>
              {commits.map((c) => {
                const badge = statusColors[c.status] || statusColors.pending;
                return (
                  <tr
                    key={c.id}
                    onClick={() => setSelectedSha(c.sha)}
                    style={{
                      borderBottom: "1px solid #16181c",
                      cursor: "pointer",
                      backgroundColor:
                        selectedSha === c.sha ? "rgba(94, 106, 210, 0.08)" : "transparent",
                    }}
                  >
                    <td
                      style={{
                        padding: "12px 16px",
                        fontFamily: "monospace",
                        color: "#5e6ad2",
                      }}
                    >
                      {c.sha.slice(0, 8)}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#f7f8f8", fontWeight: 500 }}>
                      {c.subject || "(mesaj yok)"}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#8a8f98" }}>
                      {c.author || "-"}
                    </td>
                    <td
                      style={{
                        padding: "12px 16px",
                        color: "#8a8f98",
                        fontFamily: "monospace",
                        fontSize: "12px",
                      }}
                    >
                      {c.repo_path}
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "2px 8px",
                          borderRadius: "9999px",
                          fontSize: "12px",
                          fontWeight: 500,
                          backgroundColor: badge.bg,
                          color: badge.fg,
                          border: `1px solid ${badge.border}`,
                        }}
                      >
                        {c.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div
          style={{
            padding: "16px",
            backgroundColor: "#0f1011",
            border: "1px solid #1e2024",
            borderRadius: "8px",
            fontSize: "13px",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "8px", color: "#f7f8f8" }}>
            Commit Detayı: <code style={{ color: "#5e6ad2" }}>{detail.sha}</code>
          </div>
          <div style={{ color: "#8a8f98", marginBottom: "4px" }}>
            Patch ID: <code>{detail.patch_id}</code>
          </div>
          <div style={{ color: "#8a8f98" }}>
            Bulgular (Findings): {detail.findings.length} adet
          </div>
        </div>
      )}
    </div>
  );
}
