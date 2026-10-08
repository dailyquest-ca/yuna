"""law — §0.7: publish the law to the one place every session and Routine reads it from.

The plan (`docs/yuna_plan.md`) and the routines contract (`docs/routines-contract.md`) on `main` are
the only copies of the law. A merge that changes either is a promotion (§0.3 says who promotes), and
this job — run by `.github/workflows/law.yml` on every push to `main` that touches them — appends the
new text to Supabase's `law` table: the full text, its SHA-256, the plan's version and the commit.
`v_law` is the newest row per document; sessions read the law there (§0.4), the payload carries the
plan's version and hash (`v_session_payload.law`), and the brief prints them in its header.

Why: on 2026-10-06 Zak promoted v1.1 into the claude.ai project's copy of the plan, which predated
five rulings the repo's plan carried, and the Routines read that copy as the law (migration 076).

Idempotent. A document whose newest published row already carries this text's hash writes nothing,
so a re-run, a dispatch or a merge that touched neither file publishes nothing. The table is
append-only (076): a published law is never edited, and a revert is a new row.
"""
import hashlib
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat                                     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCUMENTS = {"plan": ROOT / "docs" / "yuna_plan.md",
             "routines-contract": ROOT / "docs" / "routines-contract.md"}
# The plan's first line names its version: "# yuna_plan.md — v1.2".
HEADER = re.compile(r"^# yuna_plan\.md — (v\d+(?:\.\d+)+)\s*$")


def plan_version(text):
    """The version the plan's first line names, or None."""
    first = text.splitlines()[0] if text else ""
    m = HEADER.match(first)
    return m.group(1) if m else None


def commit():
    """The commit being published: the workflow's own, or the checkout's when run by hand."""
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if sha:
        return sha
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit("no commit to publish the law under — GITHUB_SHA is unset and git has none")
    return out.stdout.strip()


def publish(cur, documents, sha, write=True):
    """Append each document whose text differs from its newest published row.

    Returns [(document, version, sha256, published)]. A plan whose first line names no version is
    refused before anything is written: a law readers cannot name is a law they cannot check.
    """
    texts = {doc: path.read_text(encoding="utf-8") for doc, path in documents.items()}
    if "plan" in texts and plan_version(texts["plan"]) is None:
        raise SystemExit(f"{documents['plan'].name}'s first line names no version "
                         f"(want '# yuna_plan.md — vN.N') — nothing published")
    out = []
    for doc, body in texts.items():
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        version = plan_version(body) if doc == "plan" else None
        cur.execute("select sha256 from law where document = %s order by id desc limit 1", (doc,))
        row = cur.fetchone()
        if row and row[0] == digest:
            out.append((doc, version, digest, False))
            continue
        if write:
            cur.execute("""insert into law (document, version, sha256, git_commit, body)
                           values (%s, %s, %s, %s, %s)""", (doc, version, digest, sha, body))
        out.append((doc, version, digest, True))
    return out


def main():
    sha = commit()
    with connect() as conn, Heartbeat(conn, "law", dry_run=dry()) as hb:
        with conn.cursor() as cur:
            done = publish(cur, DOCUMENTS, sha, write=not dry())
        hb.rows = 0 if dry() else sum(1 for d in done if d[3])
        hb.detail.update(commit=sha, documents=[
            dict(document=doc, version=version, sha256=digest, published=new)
            for doc, version, digest, new in done])
    for doc, version, digest, new in done:
        state = ("published" if not dry() else "would publish") if new else "unchanged"
        print(f"law: {doc}{f' {version}' if version else ''} {digest[:12]} — {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
