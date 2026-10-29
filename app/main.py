from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import db


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
    allow_origins=["http://localhost:5173"],
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
