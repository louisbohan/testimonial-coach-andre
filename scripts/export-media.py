#!/usr/bin/env python3
"""Export every testimonial asset from Cloudflare KV to a local folder + CSV.

Usage:
    python3 scripts/export-media.py [--out ~/coach-andre-media] [--dry-run]

Reads the KV index via wrangler, then downloads each file over the public
worker URL. Idempotent: files already on disk with the same size are skipped.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

NAMESPACE_ID = "9943cf4bc8bd47559a13f22d91e03f5a"
WORKER = "https://testimonial-upload.louisbohanreports.workers.dev"
REPO = Path(__file__).resolve().parent.parent


def kv_index() -> list[dict]:
    out = subprocess.run(
        ["wrangler", "kv", "key", "list", f"--namespace-id={NAMESPACE_ID}", "--remote"],
        capture_output=True, text=True, cwd=REPO, check=True,
    ).stdout
    return json.loads(out)


def safe(name: str, fallback: str) -> str:
    keep = "-_. "
    cleaned = "".join(c for c in (name or fallback) if c.isalnum() or c in keep).strip()
    return cleaned or fallback


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "coach-andre-media"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.out).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.csv"

    # Reuse the previous manifest so re-runs recognise their own downloads
    # (and so two assets that happen to share a filename never overwrite).
    known: dict[str, str] = {}
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("key") and row.get("filename"):
                    known[row["key"]] = row["filename"]
    taken = {fn for fn in known.values()}

    rows = []
    for entry in kv_index():
        key = entry["name"]
        meta = entry.get("metadata") or {}
        received = (meta.get("received") or "")[:10] or "undated"
        day_dir = root / received
        day_dir.mkdir(parents=True, exist_ok=True)

        if key in known:
            filename = Path(known[key]).name
        else:
            filename = safe(meta.get("filename") or "", key)
            if not Path(filename).suffix:
                filename += Path(key).suffix
            stem, suffix = Path(filename).stem, Path(filename).suffix
            candidate = filename
            if str(Path(received) / candidate) in taken:
                candidate = f"{stem}-{Path(key).stem[:6]}{suffix}"
            filename = candidate

        dest = day_dir / filename
        taken.add(str(dest.relative_to(root)))
        if dest.exists() and dest.stat().st_size == meta.get("bytes"):
            status = "cached"
        elif args.dry_run:
            status = "would-fetch"
        else:
            url = f"{WORKER}/f/{key}"
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; testimonial-export/1.0)",
                })
                with urllib.request.urlopen(req, timeout=120) as r:
                    blob = r.read()
                dest.write_bytes(blob)
                status = f"saved {len(blob)}b"
            except Exception as exc:
                status = f"FAILED {exc}"

        rows.append({
            "received": meta.get("received", ""),
            "filename": str(dest.relative_to(root)),
            "content_type": meta.get("contentType", ""),
            "bytes": meta.get("bytes", ""),
            "key": key,
            "url": f"{WORKER}/f/{key}",
            "status": status,
        })
        print(f"{status:22} {rows[-1]['filename']}")

    rows.sort(key=lambda r: r["received"], reverse=True)
    manifest = root / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["received"])
        w.writeheader()
        w.writerows(rows)

    print(f"\n{len(rows)} asset(s) -> {root}\nmanifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
