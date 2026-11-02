import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  fetchCommits,
  fetchCommitDetail,
  fetchCommitDocs,
  getExportUrl,
  patchFindingStatus,
  CommitItem,
  FindingItem,
} from "../api/client";

const statusColors: Record<CommitItem["status"], { bg: string; fg: string; border: string }> = {
  pending: { bg: "rgba(94, 106, 210, 0.14)", fg: "#8f9ae8", border: "rgba(94, 106, 210, 0.35)" },
  running: { bg: "rgba(234, 179, 8, 0.14)", fg: "#facc15", border: "rgba(234, 179, 8, 0.35)" },
  done: { bg: "rgba(34, 197, 94, 0.14)", fg: "#4ade80", border: "rgba(34, 197, 94, 0.35)" },
  failed: { bg: "rgba(239, 68, 68, 0.14)", fg: "#f87171", border: "rgba(239, 68, 68, 0.35)" },
};

const severityColors: Record<FindingItem["severity"], { bg: string; fg: string; border: string }> = {
  critical: { bg: "rgba(239, 68, 68, 0.22)", fg: "#fca5a5", border: "rgba(239, 68, 68, 0.55)" },
  high: { bg: "rgba(249, 115, 22, 0.18)", fg: "#fdba74", border: "rgba(249, 115, 22, 0.45)" },
  medium: { bg: "rgba(234, 179, 8, 0.16)", fg: "#fde047", border: "rgba(234, 179, 8, 0.4)" },
  low: { bg: "rgba(94, 106, 210, 0.16)", fg: "#a5b4fc", border: "rgba(94, 106, 210, 0.4)" },
};

const findingStatusColors: Record<FindingItem["status"], { bg: string; fg: string; border: string }> = {
  open: { bg: "rgba(239, 68, 68, 0.14)", fg: "#f87171", border: "rgba(239, 68, 68, 0.35)" },
  ignored: { bg: "rgba(138, 143, 152, 0.16)", fg: "#d0d6e0", border: "rgba(138, 143, 152, 0.35)" },
  fixed: { bg: "rgba(39, 166, 68, 0.18)", fg: "#4ade80", border: "rgba(39, 166, 68, 0.4)" },
};

export function CommitList() {
  const [selectedSha, setSelectedSha] = useState<string | null>(null);
  const [docTab, setDocTab] = useState<"summary" | "detail">("summary");
  const [ignoreReasons, setIgnoreReasons] = useState<Record<number, string>>({});
  const [formErrors, setFormErrors] = useState<Record<number, string>>({});
  const queryClient = useQueryClient();

  const { data: commits, isLoading, isError, error } = useQuery({
    queryKey: ["commits"],
    queryFn: fetchCommits,
    refetchInterval: 5000,
  });

  const { data: detail } = useQuery({
    queryKey: ["commit-detail", selectedSha],
    queryFn: () => fetchCommitDetail(selectedSha!),
    enabled: Boolean(selectedSha),
    refetchInterval: 5000,
  });

  const { data: docs } = useQuery({
    queryKey: ["commit-docs", selectedSha],
    queryFn: () => fetchCommitDocs(selectedSha!),
    enabled: Boolean(selectedSha),
    refetchInterval: 5000,
  });

  const ignoreMutation = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      patchFindingStatus(id, "ignored", reason),
    onSuccess: (_data, variables) => {
      setFormErrors((prev) => ({ ...prev, [variables.id]: "" }));
      queryClient.invalidateQueries({ queryKey: ["commit-detail", selectedSha] });
    },
    onError: (err: Error, variables) => {
      setFormErrors((prev) => ({ ...prev, [variables.id]: err.message }));
    },
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

  const activeDocContent =
    docTab === "summary" ? docs?.summary || "" : docs?.detail || "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
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
            border: "1px solid #23252a",
            borderRadius: "12px",
            color: "#8a8f98",
          }}
        >
          Henüz kayıtlı commit bulunmuyor.
        </div>
      ) : (
        <div
          style={{
            backgroundColor: "#0f1011",
            border: "1px solid #23252a",
            borderRadius: "12px",
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
                  borderBottom: "1px solid #23252a",
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
                      borderBottom: "1px solid #18191a",
                      cursor: "pointer",
                      backgroundColor:
                        selectedSha === c.sha ? "rgba(94, 106, 210, 0.1)" : "transparent",
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
            display: "flex",
            flexDirection: "column",
            gap: "20px",
            padding: "24px",
            backgroundColor: "#0f1011",
            border: "1px solid #23252a",
            borderRadius: "12px",
          }}
        >
          {/* Commit Header */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: "12px",
              borderBottom: "1px solid #23252a",
              paddingBottom: "16px",
            }}
          >
            <div>
              <div style={{ fontSize: "18px", fontWeight: 600, color: "#f7f8f8", marginBottom: "6px" }}>
                Commit Detayı:{" "}
                <code style={{ color: "#5e6ad2", fontSize: "15px" }}>{detail.sha.slice(0, 12)}</code>
              </div>
              <div style={{ color: "#d0d6e0", fontSize: "14px", marginBottom: "4px" }}>
                {detail.subject || "(mesaj yok)"}
              </div>
              <div style={{ color: "#8a8f98", fontSize: "12px", fontFamily: "monospace" }}>
                Patch ID: {detail.patch_id.slice(0, 16)}... | Durum: {detail.status}
                {detail.error ? ` (${detail.error})` : ""}
              </div>
            </div>

            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <a
                href={getExportUrl(detail.sha, "summary")}
                download={`${detail.sha.slice(0, 8)}-summary.md`}
                style={{
                  padding: "8px 14px",
                  borderRadius: "8px",
                  backgroundColor: "#141516",
                  border: "1px solid #23252a",
                  color: "#f7f8f8",
                  fontSize: "13px",
                  fontWeight: 500,
                  textDecoration: "none",
                }}
              >
                Summary İndir (.md)
              </a>
              <a
                href={getExportUrl(detail.sha, "detail")}
                download={`${detail.sha.slice(0, 8)}-detail.md`}
                style={{
                  padding: "8px 14px",
                  borderRadius: "8px",
                  backgroundColor: "#5e6ad2",
                  color: "#ffffff",
                  fontSize: "13px",
                  fontWeight: 500,
                  textDecoration: "none",
                }}
              >
                Detail İndir (.md)
              </a>
            </div>
          </div>

          {/* Docs Tabs (Summary / Detail) */}
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <button
                type="button"
                onClick={() => setDocTab("summary")}
                style={{
                  padding: "6px 14px",
                  borderRadius: "9999px",
                  border: docTab === "summary" ? "1px solid #34343a" : "1px solid transparent",
                  backgroundColor: docTab === "summary" ? "#141516" : "#010102",
                  color: docTab === "summary" ? "#f7f8f8" : "#8a8f98",
                  fontSize: "13px",
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                Özet (Summary)
              </button>
              <button
                type="button"
                onClick={() => setDocTab("detail")}
                style={{
                  padding: "6px 14px",
                  borderRadius: "9999px",
                  border: docTab === "detail" ? "1px solid #34343a" : "1px solid transparent",
                  backgroundColor: docTab === "detail" ? "#141516" : "#010102",
                  color: docTab === "detail" ? "#f7f8f8" : "#8a8f98",
                  fontSize: "13px",
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                Detaylı Doküman (Detail)
              </button>
            </div>

            <div
              style={{
                padding: "20px",
                backgroundColor: "#141516",
                border: "1px solid #23252a",
                borderRadius: "8px",
                color: "#f7f8f8",
                fontSize: "14px",
                lineHeight: 1.6,
              }}
            >
              {activeDocContent ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{activeDocContent}</ReactMarkdown>
              ) : (
                <span style={{ color: "#8a8f98" }}>
                  Bu commit için henüz doküman üretilmedi ({detail.status}).
                </span>
              )}
            </div>
          </div>

          {/* Findings List */}
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={{ fontSize: "16px", fontWeight: 600, color: "#f7f8f8" }}>
              Bulgular (Findings): {detail.findings.length} adet
            </div>

            {detail.findings.length === 0 ? (
              <div
                style={{
                  padding: "16px",
                  backgroundColor: "#141516",
                  border: "1px solid #23252a",
                  borderRadius: "8px",
                  color: "#8a8f98",
                  fontSize: "13px",
                }}
              >
                Bu commit için kayıtlı güvenlik bulgusu yok.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {detail.findings.map((f) => {
                  const sevStyle = severityColors[f.severity] || severityColors.medium;
                  const stStyle = findingStatusColors[f.status] || findingStatusColors.open;
                  const reasonInput = ignoreReasons[f.id] ?? "";
                  const errMsg = formErrors[f.id];

                  return (
                    <div
                      key={f.id}
                      style={{
                        padding: "16px",
                        backgroundColor: "#141516",
                        border: "1px solid #23252a",
                        borderRadius: "8px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "10px",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: "8px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                          <span
                            style={{
                              padding: "2px 8px",
                              borderRadius: "9999px",
                              fontSize: "11px",
                              fontWeight: 600,
                              textTransform: "uppercase",
                              backgroundColor: sevStyle.bg,
                              color: sevStyle.fg,
                              border: `1px solid ${sevStyle.border}`,
                            }}
                          >
                            {f.severity}
                          </span>
                          <span
                            style={{
                              fontFamily: "monospace",
                              fontSize: "13px",
                              color: "#5e6ad2",
                              fontWeight: 500,
                            }}
                          >
                            {f.file || "-"}:{f.line ?? "-"}
                          </span>
                          <span style={{ color: "#f7f8f8", fontWeight: 600, fontSize: "14px" }}>
                            {f.title || f.rule_id}
                          </span>
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span
                            style={{
                              fontSize: "11px",
                              color: "#8a8f98",
                              fontFamily: "monospace",
                            }}
                          >
                            {f.source}
                            {f.cwe ? ` • ${f.cwe}` : ""}
                          </span>
                          <span
                            style={{
                              padding: "2px 8px",
                              borderRadius: "9999px",
                              fontSize: "12px",
                              fontWeight: 500,
                              backgroundColor: stStyle.bg,
                              color: stStyle.fg,
                              border: `1px solid ${stStyle.border}`,
                            }}
                          >
                            {f.status}
                          </span>
                        </div>
                      </div>

                      {f.explanation && (
                        <div style={{ color: "#d0d6e0", fontSize: "13px", lineHeight: 1.5 }}>
                          {f.explanation}
                        </div>
                      )}

                      {f.fix && (
                        <div style={{ color: "#8a8f98", fontSize: "12px" }}>
                          <strong style={{ color: "#d0d6e0" }}>Çözüm:</strong> {f.fix}
                        </div>
                      )}

                      {f.status === "ignored" && f.ignore_reason && (
                        <div
                          style={{
                            padding: "8px 12px",
                            backgroundColor: "#0f1011",
                            border: "1px solid #23252a",
                            borderRadius: "6px",
                            color: "#8a8f98",
                            fontSize: "12px",
                          }}
                        >
                          <strong style={{ color: "#d0d6e0" }}>Yoksayma Gerekçesi:</strong>{" "}
                          {f.ignore_reason}
                        </div>
                      )}

                      {f.status !== "ignored" && (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            const trimmed = reasonInput.trim();
                            if (!trimmed) {
                              setFormErrors((prev) => ({
                                ...prev,
                                [f.id]: "Yoksaymak için gerekçe zorunludur.",
                              }));
                              return;
                            }
                            ignoreMutation.mutate({ id: f.id, reason: trimmed });
                          }}
                          style={{
                            display: "flex",
                            flexWrap: "wrap",
                            gap: "8px",
                            alignItems: "center",
                            marginTop: "4px",
                          }}
                        >
                          <input
                            type="text"
                            placeholder="Yoksayma gerekçesi girin..."
                            value={reasonInput}
                            onChange={(e) =>
                              setIgnoreReasons((prev) => ({ ...prev, [f.id]: e.target.value }))
                            }
                            style={{
                              flex: "1 1 240px",
                              padding: "8px 12px",
                              borderRadius: "8px",
                              border: "1px solid #23252a",
                              backgroundColor: "#0f1011",
                              color: "#f7f8f8",
                              fontSize: "13px",
                            }}
                          />
                          <button
                            type="submit"
                            disabled={ignoreMutation.isPending}
                            style={{
                              padding: "8px 14px",
                              borderRadius: "8px",
                              border: "1px solid #23252a",
                              backgroundColor: "#5e6ad2",
                              color: "#ffffff",
                              fontSize: "13px",
                              fontWeight: 500,
                              cursor: "pointer",
                            }}
                          >
                            Yoksay (Ignore)
                          </button>
                          {errMsg && (
                            <span style={{ color: "#f87171", fontSize: "12px" }}>{errMsg}</span>
                          )}
                        </form>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
