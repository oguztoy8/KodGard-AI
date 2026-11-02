import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  API_URL,
  fetchCommits,
  fetchAssistantStatus,
  AssistantSourceItem,
  ChatHistoryMessage,
} from "../api/client";

interface ChatTurn {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: AssistantSourceItem[];
}

export function Assistant() {
  const [selectedCommitSha, setSelectedCommitSha] = useState<string>("");
  const [question, setQuestion] = useState<string>("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [errorBox, setErrorBox] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const nextIdRef = useRef<number>(1);

  const { data: statusData } = useQuery({
    queryKey: ["assistant-status"],
    queryFn: fetchAssistantStatus,
    refetchInterval: 5000,
  });

  const { data: commits } = useQuery({
    queryKey: ["commits"],
    queryFn: fetchCommits,
    refetchInterval: 5000,
  });

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming) {
      return;
    }

    setErrorBox(null);
    const historyPayload: ChatHistoryMessage[] = turns.slice(-6).map((t) => ({
      role: t.role,
      content: t.content,
    }));

    const userTurnId = nextIdRef.current++;
    const assistantTurnId = nextIdRef.current++;

    setTurns((prev) => [
      ...prev,
      { id: userTurnId, role: "user", content: trimmed },
      { id: assistantTurnId, role: "assistant", content: "", sources: [] },
    ]);
    setQuestion("");
    setIsStreaming(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch(`${API_URL}/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          commit_sha: selectedCommitSha ? selectedCommitSha : null,
          history: historyPayload,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP_${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const rawEvents = buffer.split("\n\n");
        buffer = rawEvents.pop() ?? "";

        for (const rawBlock of rawEvents) {
          if (!rawBlock.trim()) continue;
          let eventName = "message";
          let dataLine = "";
          for (const line of rawBlock.split("\n")) {
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLine += line.slice(5).trim();
            }
          }
          if (!dataLine) continue;

          try {
            const parsed = JSON.parse(dataLine);
            if (eventName === "sources") {
              setTurns((prev) =>
                prev.map((item) =>
                  item.id === assistantTurnId
                    ? { ...item, sources: Array.isArray(parsed) ? parsed : [] }
                    : item
                )
              );
            } else if (eventName === "token") {
              const tokenText = typeof parsed?.t === "string" ? parsed.t : "";
              if (tokenText) {
                setTurns((prev) =>
                  prev.map((item) =>
                    item.id === assistantTurnId
                      ? { ...item, content: item.content + tokenText }
                      : item
                  )
                );
              }
            } else if (eventName === "error") {
              const errClass = parsed?.class || "AssistantError";
              setErrorBox(`Asistan hatası: ${errClass}`);
            }
          } catch {
            // Ignore malformed JSON chunk
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setErrorBox(`İstek başarısız: ${(err as Error).message}`);
      }
    } finally {
      abortControllerRef.current = null;
      setIsStreaming(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* Top Filter & Indexing Status Bar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "12px",
          padding: "16px 20px",
          backgroundColor: "#0f1011",
          border: "1px solid #23252a",
          borderRadius: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          <label
            htmlFor="commit-filter-select"
            style={{ fontSize: "13px", fontWeight: 500, color: "#d0d6e0" }}
          >
            Commit filtresi:
          </label>
          <select
            id="commit-filter-select"
            value={selectedCommitSha}
            onChange={(e) => setSelectedCommitSha(e.target.value)}
            style={{
              padding: "8px 12px",
              borderRadius: "8px",
              border: "1px solid #23252a",
              backgroundColor: "#141516",
              color: "#f7f8f8",
              fontSize: "13px",
              outline: "none",
            }}
          >
            <option value="">Tümü</option>
            {commits?.map((c) => (
              <option key={c.id} value={c.sha}>
                {c.sha.slice(0, 8)} — {c.subject || "(mesaj yok)"}
              </option>
            ))}
          </select>
        </div>

        <div style={{ fontSize: "13px", color: "#8a8f98" }}>
          <span
            style={{
              display: "inline-block",
              padding: "4px 10px",
              borderRadius: "9999px",
              backgroundColor: "#141516",
              border: "1px solid #23252a",
              color: "#d0d6e0",
              fontSize: "12px",
              fontWeight: 500,
            }}
          >
            {statusData?.indexed_commits ?? 0} / {statusData?.total_commits ?? 0} commit indexli
            {statusData ? ` (${statusData.chunks} chunk)` : ""}
          </span>
        </div>
      </div>

      {/* Error Box */}
      {errorBox && (
        <div
          style={{
            padding: "12px 16px",
            backgroundColor: "rgba(239, 68, 68, 0.14)",
            border: "1px solid rgba(239, 68, 68, 0.4)",
            borderRadius: "8px",
            color: "#f87171",
            fontSize: "13px",
          }}
        >
          {errorBox}
        </div>
      )}

      {/* Messages Panel */}
      <div
        style={{
          minHeight: "380px",
          maxHeight: "560px",
          overflowY: "auto",
          padding: "20px",
          backgroundColor: "#0f1011",
          border: "1px solid #23252a",
          borderRadius: "12px",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        {turns.length === 0 ? (
          <div style={{ color: "#8a8f98", fontSize: "14px", textAlign: "center", margin: "auto" }}>
            Indexlenmiş commit dokümanları, güvenlik bulguları ve kod değişiklikleri hakkında soru sorun.
          </div>
        ) : (
          turns.map((turn) => (
            <div
              key={turn.id}
              style={{
                padding: "16px",
                borderRadius: "10px",
                backgroundColor: turn.role === "user" ? "#141516" : "#18191a",
                border: "1px solid #23252a",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              <div
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  color: turn.role === "user" ? "#5e6ad2" : "#d0d6e0",
                }}
              >
                {turn.role === "user" ? "Siz" : "KodGard Asistan"}
              </div>

              <div style={{ fontSize: "14px", lineHeight: 1.6, color: "#f7f8f8" }}>
                {turn.role === "assistant" ? (
                  turn.content ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown>
                  ) : (
                    <span style={{ color: "#8a8f98" }}>Yanıt hazırlanıyor...</span>
                  )
                ) : (
                  <div>{turn.content}</div>
                )}
              </div>

              {turn.role === "assistant" && turn.sources && turn.sources.length > 0 && (
                <div
                  style={{
                    marginTop: "6px",
                    paddingTop: "10px",
                    borderTop: "1px solid #23252a",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                  }}
                >
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "#8a8f98" }}>
                    Kaynaklar (Sources):
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                    {turn.sources.map((src) => (
                      <div
                        key={src.n}
                        style={{
                          padding: "4px 10px",
                          backgroundColor: "#0f1011",
                          border: "1px solid #23252a",
                          borderRadius: "6px",
                          fontSize: "12px",
                          fontFamily: "monospace",
                          color: "#d0d6e0",
                        }}
                      >
                        [{src.n}] <span style={{ color: "#5e6ad2" }}>{src.sha8}</span> • {src.kind} •{" "}
                        {src.ref}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Chat Input Form */}
      <form
        onSubmit={handleSend}
        style={{
          display: "flex",
          gap: "10px",
          alignItems: "center",
          padding: "16px",
          backgroundColor: "#0f1011",
          border: "1px solid #23252a",
          borderRadius: "12px",
        }}
      >
        <input
          type="text"
          maxLength={2000}
          placeholder="Commit'ler ve güvenlik bulguları hakkında sorunuzu yazın (maks. 2000 karakter)..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={isStreaming}
          style={{
            flex: 1,
            padding: "10px 14px",
            borderRadius: "8px",
            border: "1px solid #23252a",
            backgroundColor: "#141516",
            color: "#f7f8f8",
            fontSize: "14px",
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={isStreaming || !question.trim()}
          style={{
            padding: "10px 18px",
            borderRadius: "8px",
            border: "none",
            backgroundColor: isStreaming || !question.trim() ? "#23252a" : "#5e6ad2",
            color: "#ffffff",
            fontSize: "14px",
            fontWeight: 500,
            cursor: isStreaming || !question.trim() ? "not-allowed" : "pointer",
          }}
        >
          Gönder
        </button>
        {isStreaming && (
          <button
            type="button"
            onClick={handleStop}
            style={{
              padding: "10px 16px",
              borderRadius: "8px",
              border: "1px solid rgba(239, 68, 68, 0.45)",
              backgroundColor: "rgba(239, 68, 68, 0.14)",
              color: "#f87171",
              fontSize: "14px",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Durdur
          </button>
        )}
      </form>
    </div>
  );
}
