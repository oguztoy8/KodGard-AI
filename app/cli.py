import argparse
import logging
import sys
from pathlib import Path

from app import db, git_reader

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def cmd_enqueue(repo: str, sha: str) -> int:
    repo_path = str(Path(repo).resolve())
    commit = git_reader.get_commit(repo_path, sha)
    if commit is None:
        logger.info("Commit %s skipped (merge commit or not found)", sha)
        return 0
    commit_id = db.upsert_commit(commit, repo_path)
    scan_id = db.enqueue_scan(commit_id)
    print(f"Enqueued commit_id={commit_id} scan_id={scan_id} sha={commit['sha']}")
    return 0


def cmd_list(repo: str | None, limit: int) -> int:
    rows = db.list_commits_with_status(repo_path=repo, limit=limit)
    if not rows:
        print("No commits found.")
        return 0
    for row in rows:
        short_sha = row["sha"][:8]
        short_patch = row["patch_id"][:8]
        status = row["status"]
        subject = row.get("subject") or ""
        author = row.get("author") or ""
        print(f"{short_sha}  patch={short_patch}  status={status:<8}  {subject} ({author})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kodgard", description="KodGard AI CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    enqueue_parser = subparsers.add_parser("enqueue", help="Enqueue a commit for scanning")
    enqueue_parser.add_argument("--repo", required=True, help="Path to git repository")
    enqueue_parser.add_argument("--sha", required=True, help="Commit SHA")

    list_parser = subparsers.add_parser("list", help="List tracked commits and scan statuses")
    list_parser.add_argument("--repo", required=False, default=None, help="Filter by repository path")
    list_parser.add_argument("--limit", type=int, default=20, help="Maximum commits to list")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "enqueue":
            return cmd_enqueue(args.repo, args.sha)
        if args.command == "list":
            return cmd_list(args.repo, args.limit)
        return 1
    finally:
        db.close_pool()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
