import { useState } from "react";
import { CommitList } from "./pages/CommitList";
import { Health } from "./pages/Health";

type Tab = "commits" | "health";

export function App() {
  const [activeTab, setActiveTab] = useState<Tab>("commits");

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "#010102", color: "#f7f8f8" }}>
      <header
        style={{
          borderBottom: "1px solid #1e2024",
          backgroundColor: "#08090a",
          padding: "0 24px",
        }}
      >
        <div
          style={{
            maxWidth: "1040px",
            margin: "0 auto",
            height: "56px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span
              style={{
                width: "10px",
                height: "10px",
                borderRadius: "50%",
                backgroundColor: "#5e6ad2",
                display: "inline-block",
              }}
            />
            <span style={{ fontWeight: 600, fontSize: "16px", letterSpacing: "-0.02em" }}>
              KodGard AI
            </span>
          </div>

          <nav style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={() => setActiveTab("commits")}
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                border:
                  activeTab === "commits"
                    ? "1px solid rgba(94, 106, 210, 0.5)"
                    : "1px solid transparent",
                backgroundColor:
                  activeTab === "commits" ? "rgba(94, 106, 210, 0.16)" : "transparent",
                color: activeTab === "commits" ? "#f7f8f8" : "#8a8f98",
                fontSize: "13px",
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Commit'ler
            </button>
            <button
              onClick={() => setActiveTab("health")}
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                border:
                  activeTab === "health"
                    ? "1px solid rgba(94, 106, 210, 0.5)"
                    : "1px solid transparent",
                backgroundColor:
                  activeTab === "health" ? "rgba(94, 106, 210, 0.16)" : "transparent",
                color: activeTab === "health" ? "#f7f8f8" : "#8a8f98",
                fontSize: "13px",
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Sağlık
            </button>
          </nav>
        </div>
      </header>

      <main style={{ maxWidth: "1040px", margin: "0 auto", padding: "24px" }}>
        {activeTab === "commits" ? <CommitList /> : <Health />}
      </main>
    </div>
  );
}

export default App;
