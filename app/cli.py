import argparse
import logging
from pathlib import Path
import sys

from app import db, git_reader, indexer, worker

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class _MergeLogCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "Skipping merge commit" in record.getMessage():
            self.count += 1


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


def cmd_worker(loop: bool = False, interval: float = 5.0) -> int:
    return worker.run_worker(loop=loop, interval=interval)


def cmd_reindex(sha: str | None = None, reindex_all: bool = False) -> int:
    if not sha and not reindex_all:
        print("Error: reindex requires either --sha <SHA> or --all", file=sys.stderr)
        return 2
    commits = db.list_done_commits(sha=sha if not reindex_all else None)
    if not commits:
        print("No matching commits found to index.")
        return 0
    for c in commits:
        commit_id = int(c["id"])
        sha8 = str(c["sha"])[:8]
        counts = indexer.index_commit(commit_id)
        print(
            f"sha={sha8} total={counts['total']} "
            f"doc_summary={counts['doc_summary']} "
            f"doc_detail={counts['doc_detail']} "
            f"finding={counts['finding']} "
            f"diff={counts['diff']} "
            f"file={counts['file']}"
        )
    return 0


def cmd_backfill(repo: str, limit: int = 20, yes: bool = False) -> int:
    if limit < 1 or limit > 200:
        print("Error: --limit must be between 1 and 200.", file=sys.stderr)
        return 2
    if limit > 20 and not yes:
        msg = "Uyarı: limit > 20 için --yes zorunludur; her commit bir Claude çağrısı demektir."
        print(msg, file=sys.stderr)
        print(msg)
        return 1

    repo_path = str(Path(repo).resolve())
    counter = _MergeLogCounter()
    gr_logger = logging.getLogger(git_reader.__name__)
    prev_level = gr_logger.level
    gr_logger.setLevel(logging.INFO)
    gr_logger.addHandler(counter)
    try:
        commits = git_reader.list_commits(repo_path, limit=limit)
    finally:
        gr_logger.removeHandler(counter)
        gr_logger.setLevel(prev_level)

    added = 0
    skipped = 0
    for c in reversed(commits):
        commit_id = db.upsert_commit(c, repo_path)
        _scan_id, created = db.enqueue_scan_if_missing(commit_id)
        if created:
            added += 1
        else:
            skipped += 1

    print(f"eklenen={added} atlanan={skipped} merge={counter.count}")
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

    worker_parser = subparsers.add_parser("worker", help="Process pending scans sequentially")
    worker_parser.add_argument("--loop", action="store_true", help="Continuously poll for pending scans")
    worker_parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds")

    reindex_parser = subparsers.add_parser("reindex", help="Index commit chunks into pgvector")
    reindex_group = reindex_parser.add_mutually_exclusive_group(required=True)
    reindex_group.add_argument("--sha", help="Reindex a specific commit by SHA")
    reindex_group.add_argument("--all", dest="reindex_all", action="store_true", help="Reindex all done commits")

    backfill_parser = subparsers.add_parser("backfill", help="Backfill recent commits from a repository")
    backfill_parser.add_argument("--repo", required=True, help="Path to git repository")
    backfill_parser.add_argument("--limit", type=int, default=20, help="Number of commits (1..200)")
    backfill_parser.add_argument("--yes", action="store_true", help="Confirm when limit > 20")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "enqueue":
            return cmd_enqueue(args.repo, args.sha)
        if args.command == "list":
            return cmd_list(args.repo, args.limit)
        if args.command == "worker":
            return cmd_worker(loop=args.loop, interval=args.interval)
        if args.command == "reindex":
            return cmd_reindex(sha=args.sha, reindex_all=args.reindex_all)
        if args.command == "backfill":
            return cmd_backfill(repo=args.repo, limit=args.limit, yes=args.yes)
        return 1
    finally:
        db.close_pool()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
