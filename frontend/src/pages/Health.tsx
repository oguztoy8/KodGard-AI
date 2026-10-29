import { useQuery } from "@tanstack/react-query";
import { fetchHealth, API_URL } from "../api/client";

export function Health() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 5000,
  });

  return (
    <div
      style={{
        backgroundColor: "#0f1011",
        border: "1px solid #1e2024",
        borderRadius: "8px",
        padding: "24px",
        display: "flex",
        flexDirection: "column",
        gap: "16px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0, fontSize: "18px", fontWeight: 600, color: "#f7f8f8" }}>
          Backend & Veritabanı Durumu
        </h2>
        <button
          onClick={() => refetch()}
          style={{
            backgroundColor: "#5e6ad2",
            color: "#f7f8f8",
            border: "none",
            borderRadius: "6px",
            padding: "6px 12px",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Yenile
        </button>
      </div>

      <div style={{ fontSize: "13px", color: "#8a8f98" }}>
        API Adresi: <code style={{ color: "#f7f8f8" }}>{API_URL}</code>
      </div>

      {isLoading && <div style={{ color: "#8a8f98" }}>Kontrol ediliyor...</div>}

      {isError && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: "6px",
            backgroundColor: "rgba(239, 68, 68, 0.14)",
            border: "1px solid rgba(239, 68, 68, 0.35)",
            color: "#f87171",
          }}
        >
          Bağlantı Hatası: {(error as Error).message}
        </div>
      )}

      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <div
            style={{
              padding: "16px",
              backgroundColor: "#08090a",
              border: "1px solid #1e2024",
              borderRadius: "6px",
            }}
          >
            <div style={{ fontSize: "12px", color: "#8a8f98", marginBottom: "4px" }}>
              API Durumu
            </div>
            <div style={{ fontSize: "16px", fontWeight: 600, color: "#4ade80" }}>
              {data.status}
            </div>
          </div>

          <div
            style={{
              padding: "16px",
              backgroundColor: "#08090a",
              border: "1px solid #1e2024",
              borderRadius: "6px",
            }}
          >
            <div style={{ fontSize: "12px", color: "#8a8f98", marginBottom: "4px" }}>
              PostgreSQL + pgvector
            </div>
            <div style={{ fontSize: "16px", fontWeight: 600, color: "#4ade80" }}>
              {data.db}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
