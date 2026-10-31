import argparse
import json
from .storage import Archive
from .media import download
from .exporting import export_archive


def main():
    parser = argparse.ArgumentParser(description="空间记忆：本地后端开发工具")
    parser.add_argument("--archive", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    imp = sub.add_parser("import-jsonl")
    imp.add_argument("file")
    imp.add_argument("--job", help="Resume a paused import of the same immutable file")
    listing = sub.add_parser("list")
    listing.add_argument("--search", default="")
    listing.add_argument("--offset", type=int, default=0)
    sub.add_parser("download-media")
    exp = sub.add_parser("export")
    exp.add_argument("destination")
    args = parser.parse_args()
    archive = Archive(args.archive)
    try:
        if args.command == "init":
            archive.recover_jobs()
            print("Archive initialized")
        elif args.command == "import-jsonl":
            import hashlib
            from pathlib import Path

            data = Path(args.file).read_bytes()
            fingerprint = hashlib.sha256(data).hexdigest()
            key = args.job or archive.create_job()
            row = archive.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
            checkpoint = json.loads(row["cursor"]) if row and row["cursor"] else None
            if checkpoint and checkpoint["sha256"] != fingerprint:
                raise ValueError("Import file has changed")
            archive.transition(key, "running")
            print("job:", key)
            try:
                for index, line in enumerate(data.decode("utf-8").splitlines()):
                    if checkpoint and index < checkpoint["line"]:
                        continue
                    records = [json.loads(line)] if line.strip() else []
                    archive.ingest(records, key, {"line": index + 1, "sha256": fingerprint})
                archive.transition(key, "completed")
            except KeyboardInterrupt:
                archive.transition(key, "paused")
            except Exception:
                archive.transition(key, "failed")
                raise
        elif args.command == "list":
            print(
                json.dumps(
                    archive.posts(args.search, offset=args.offset), ensure_ascii=False, indent=2
                )
            )
        elif args.command == "download-media":
            for row in archive.db.execute("SELECT id FROM media WHERE state!='saved'").fetchall():
                print(row["id"], bool(download(archive, row["id"])))
        elif args.command == "export":
            print(export_archive(archive, args.destination))
    finally:
        archive.close()


if __name__ == "__main__":
    main()
