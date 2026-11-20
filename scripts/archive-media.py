#!/usr/bin/env python3
"""Archive testimonial media from Cloudflare KV to a private local folder.

Every asset is downloaded once, the original is kept, and a normalized copy is
written in the format the website and the social tools want:

    audio  -> .m4a  (AAC 96k mono)   webm / wav / mp3 all land here
    image  -> .jpg  (q2)             heic / png / heif all land here
    video  -> .mp4  (h264 + aac)

Layout (default ~/coach-andre-archive, chmod 700):

    manifest.csv              one row per asset, authoritative
    YYYY-MM-DD/<name>.m4a     normalized, ready to publish
    _originals/YYYY-MM-DD/..  untouched bytes as uploaded

Idempotent: a key already in the manifest is never re-downloaded, so this is
safe to run every few minutes from a launchd agent.

Usage:
    python3 scripts/archive-media.py [--archive DIR] [--dry-run] [--no-originals]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

NAMESPACE_ID = "9943cf4bc8bd47559a13f22d91e03f5a"
WORKER = "https://testimonial-upload.louisbohanreports.workers.dev"
REPO = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE = Path.home() / "coach-andre-archive"

AUDIO = ("audio/",)
IMAGE = ("image/",)
VIDEO = ("video/",)
CANONICAL = {"audio": ".m4a", "image": ".jpg", "video": ".mp4"}


def ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    for base in (Path.home() / ".hermes" / "tools",):
        for cand in sorted(base.glob("ffmpeg-*/ffmpeg")):
            if cand.exists():
                return str(cand)
    return None


def local_day(iso: str) -> str:
    """Folder by the client's local day, not UTC (16:03 PT is still the 19th)."""
    from datetime import datetime

    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except Exception:
        return (iso or "")[:10] or "undated"


def kind_of(content_type: str) -> str:
    ct = (content_type or "").lower()
    if ct.startswith(AUDIO):
        return "audio"
    if ct.startswith(IMAGE):
        return "image"
    if ct.startswith(VIDEO):
        return "video"
    return "other"


def kv_index() -> list:
    out = subprocess.run(
        ["wrangler", "kv", "key", "list", f"--namespace-id={NAMESPACE_ID}", "--remote"],
        capture_output=True, text=True, cwd=str(REPO), check=True,
    ).stdout
    return json.loads(out)


def safe(name: str, fallback: str) -> str:
    keep = "-_. "
    cleaned = "".join(c for c in (name or fallback) if c.isalnum() or c in keep).strip()
    return cleaned or fallback


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; testimonial-archive/1.0)",
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def convert(src: Path, dest: Path, kind: str, ff: str) -> bool:
    if kind == "audio":
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(src), "-vn",
               "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "44100", str(dest)]
    elif kind == "image":
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(src), "-q:v", "2", str(dest)]
    elif kind == "video":
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(src),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)]
    else:
        return False
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        return dest.exists() and dest.stat().st_size > 0
    except Exception as exc:
        print(f"  convert failed: {exc}", file=sys.stderr)
        return False


def unique_path(directory: Path, stem: str, ext: str, key6: str) -> Path:
    """Never overwrite: plain name, then key-suffixed, then numbered."""
    p = directory / f"{stem}{ext}"
    if not p.exists():
        return p
    p = directory / f"{stem}-{key6}{ext}"
    n = 2
    while p.exists():
        p = directory / f"{stem}-{key6}-{n}{ext}"
        n += 1
    return p


def load_manifest(path: Path) -> dict:
    rows = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("key"):
                    rows[row["key"]] = row
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-originals", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.archive).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass

    # One run at a time: a slow video conversion must not race the next tick.
    import fcntl
    lock_path = root / ".archive.lock"
    lock = lock_path.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not args.quiet:
            print("another archive run is in progress; skipping")
        return 0
    manifest = root / "manifest.csv"
    previous = load_manifest(manifest)

    ff = ffmpeg()
    index = kv_index()
    new = [e for e in index if e["name"] not in previous]

    if not args.quiet:
        print(f"{len(index)} asset(s) in KV, {len(new)} new")

    rows = list(previous.values())
    for entry in new:
        key = entry["name"]
        meta = entry.get("metadata") or {}
        received = local_day(meta.get("received") or "")
        ct = meta.get("contentType") or ""
        kind = kind_of(ct)
        size = meta.get("bytes") or 0

        day = root / received
        orig_dir = root / "_originals" / received
        day.mkdir(parents=True, exist_ok=True)

        base = safe(meta.get("filename") or "", key)
        stem = Path(base).stem or Path(key).stem

        row = {
            "received": meta.get("received", ""),
            "kind": kind,
            "original_format": ct,
            "uploaded_bytes": size,
            "key": key,
            "url": f"{WORKER}/f/{key}",
            "archive_file": "",
            "original_file": "",
            "status": "",
        }

        if args.dry_run:
            row["status"] = "would-fetch"
            rows.append(row)
            print(f"would-fetch {key}")
            continue

        try:
            blob = download(row["url"])
        except Exception as exc:
            row["status"] = f"FAILED download: {exc}"
            rows.append(row)
            print(f"FAILED {key}: {exc}", file=sys.stderr)
            continue

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(base).suffix or Path(key).suffix) as tmp:
            tmp.write(blob)
            tmp_path = Path(tmp.name)

        ext = CANONICAL.get(kind, Path(base).suffix or Path(key).suffix)
        key6 = Path(key).stem[:6]
        out = unique_path(day, stem, ext, key6)

        # keep originals out of the way but never lose them
        if not args.no_originals:
            orig_dir.mkdir(parents=True, exist_ok=True)
            orig = unique_path(orig_dir, stem, Path(base).suffix or Path(key).suffix, key6)
            shutil.copyfile(tmp_path, orig)
            row["original_file"] = str(orig.relative_to(root))

        already_canonical = ext.lower() == (Path(base).suffix or Path(key).suffix).lower()
        ok = True
        if already_canonical:
            shutil.copyfile(tmp_path, out)
        else:
            ok = convert(tmp_path, out, kind, ff) if ff else False
            if not ok:
                # conversion unavailable or failed: keep the file readable as-is
                out = day / (stem + (Path(base).suffix or Path(key).suffix))
                shutil.copyfile(tmp_path, out)
                row["status"] = "kept-original-format"

        tmp_path.unlink(missing_ok=True)
        row["archive_file"] = str(out.relative_to(root))
        row["status"] = row["status"] or ("archived" if ok else "archived-raw")
        rows.append(row)
        if not args.quiet or row["status"].startswith("FAILED"):
            print(f"{row['status']:20} {row['archive_file']}")

    rows.sort(key=lambda r: r.get("received", ""), reverse=True)
    fields = ["received", "kind", "status", "archive_file", "original_file",
              "original_format", "uploaded_bytes", "key", "url"]
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    if not args.quiet:
        print(f"\n{len(rows)} row(s) -> {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
