from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import assistant, db
from app.findings import VALID_STATUSES


class FindingStatusPatch(BaseModel):
    status: str
    ignore_reason: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    db.close_pool()


app = FastAPI(
    title="KodGard AI API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        ok = db.check_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "db": "disconnected", "message": str(exc)},
        ) from exc
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "error", "db": "disconnected"})
    return {"status": "ok", "db": "ok"}


@app.get("/commits")
def get_commits(
    repo: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return db.list_commits_with_status(repo_path=repo, limit=limit)


@app.get("/commits/{sha}")
def get_commit_detail(sha: str) -> dict[str, Any]:
    commit = db.get_commit_by_sha(sha)
    if commit is None:
        raise HTTPException(status_code=404, detail="Commit not found")
    return commit


@app.get("/commits/{sha}/docs")
def get_commit_docs(sha: str) -> dict[str, str]:
    docs = db.get_docs_by_sha(sha)
    if docs is None:
        raise HTTPException(status_code=404, detail="Commit not found")
    return {
        "summary": docs.get("summary") or "",
        "detail": docs.get("detail") or "",
    }


@app.get("/commits/{sha}/export")
def export_commit_doc(
    sha: str,
    doc: str = Query(..., description="Document kind: summary or detail"),
) -> Response:
    if doc not in ("summary", "detail"):
        raise HTTPException(status_code=400, detail="doc must be 'summary' or 'detail'")
    docs = db.get_docs_by_sha(sha)
    if docs is None:
        raise HTTPException(status_code=404, detail="Commit not found")
    body_md = docs.get(doc) or ""
    sha8 = str(docs.get("sha") or sha)[:8]
    filename = f"{sha8}-{doc}.md"
    return Response(
        content=body_md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.patch("/findings/{finding_id}")
def patch_finding(finding_id: int, payload: FindingStatusPatch) -> dict[str, Any]:
    status_val = (payload.status or "").strip()
    if status_val not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status_val}'. Allowed: {sorted(VALID_STATUSES)}",
        )
    reason_val = (payload.ignore_reason or "").strip() if payload.ignore_reason else None
    if status_val == "ignored" and not reason_val:
        raise HTTPException(
            status_code=400,
            detail="ignore_reason is required when status is 'ignored'",
        )
    updated = db.update_finding_status(
        finding_id=finding_id,
        status=status_val,
        ignore_reason=reason_val,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return updated


@app.get("/assistant/status")
def assistant_status() -> dict[str, int]:
    return db.get_assistant_status()


@app.post("/assistant/chat")
async def assistant_chat(payload: assistant.ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        assistant.stream_assistant_chat(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
