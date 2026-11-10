"""Push commits to GitHub via the Git Data API when git-over-HTTPS is blocked.

Rebuilds the commit chain commit-by-commit (blob -> tree -> commit -> ref)
on the fork, preserving author, dates and messages exactly as committed
locally. Usage: python -I api-push.py <owner> <repo> <branch> <sha1 sha2 sha3...>
The last SHA becomes the branch head; parents chain through the listed order.
"""
import base64
import json
import subprocess
import sys

OWNER, REPO, BRANCH = sys.argv[1], sys.argv[2], sys.argv[3]
SHAS = sys.argv[4:]
# Optional: an API-created commit that already corresponds to SHAS[0]; the
# chain then starts from SHAS[1] with this commit as its parent.
import os
INITIAL_PARENT = os.environ.get("INITIAL_PARENT") or None


def gh(endpoint, payload=None, method=None):
    cmd = ["gh", "api", f"repos/{OWNER}/{REPO}/{endpoint}"]
    if payload is None:
        cmd += ["--paginate"]
    if method:
        cmd += ["-X", method]
    if payload is not None:
        cmd += ["--input", "-", "-H", "Content-Type: application/json"]
        proc = subprocess.run(cmd, input=json.dumps(payload).encode(), capture_output=True)
    else:
        proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"gh api {endpoint} failed:\n{proc.stderr.decode(errors='replace')[:800]}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def git(args):
    proc = subprocess.run(["git"] + args, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"git {args[:3]} failed: {proc.stderr.decode(errors='replace')[:400]}")
    return proc.stdout


def commit_meta(sha):
    raw = git(["show", "-s", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B", sha])
    parts = raw.decode(errors="replace").rstrip("\n").split("\x00")
    return {"author_name": parts[0], "author_email": parts[1], "author_date": parts[2],
            "committer_name": parts[3], "committer_email": parts[4],
            "committer_date": parts[5], "message": parts[6]}


head = None
for index, sha in enumerate(SHAS):
    if index == 0 and INITIAL_PARENT:
        # SHAS[0] already exists on the API side; chain from its created SHA.
        head = INITIAL_PARENT
        continue
    meta = commit_meta(sha)
    if index == 0:
        parent = git(["show", "-s", "--format=%P", sha]).decode().strip()
        parent_tree_api = gh(f"commits/{parent}")["commit"]["tree"]["sha"]
        parent_tree = git(["show", "-s", "--format=%T", f"{sha}^"]).decode().strip()
        if parent_tree != parent_tree_api:
            raise SystemExit(f"tree mismatch for parent {parent}: local {parent_tree} "
                             f"vs api {parent_tree_api}")
    else:
        # Chained rebuild: the previous API commit IS the parent; its tree is
        # the base for this commit's tree (identical content by construction).
        parent = head
        parent_tree_api = gh(f"commits/{parent}")["commit"]["tree"]["sha"]
    files = subprocess.run(["git", "show", "--name-status", "--format=", sha],
                           capture_output=True, text=True).stdout.strip().splitlines()
    tree_entries = []
    for line in files:
        status, path = line[:1], line[2:].strip()
        if status == "D":
            tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            continue
        blob = git(["cat-file", "blob", f"{sha}:{path}"])
        created = gh("git/blobs", {"content": base64.b64encode(blob).decode(),
                                   "encoding": "base64"})
        tree_entries.append({"path": path, "mode": "100644", "type": "blob",
                             "sha": created["sha"]})
    tree = gh("git/trees", {"base_tree": parent_tree_api, "tree": tree_entries})
    author = {"name": meta["author_name"], "email": meta["author_email"],
              "date": meta["author_date"]}
    commit = gh("git/commits", {
        "message": meta["message"],
        "tree": tree["sha"],
        "parents": [parent],
        "author": author,
        "committer": {"name": meta["committer_name"], "email": meta["committer_email"],
                      "date": meta["committer_date"]},
    })
    print(f"{sha} -> {commit['sha']} ({meta['message'].splitlines()[0][:60]})")
    head = commit["sha"]

existing = None
proc = subprocess.run(["gh", "api", f"repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}"],
                      capture_output=True)
if proc.returncode == 0:
    existing = json.loads(proc.stdout)["object"]["sha"]
if existing:
    result = gh(f"git/refs/heads/{BRANCH}", {"sha": head, "force": False}, method="PATCH")
else:
    result = gh("git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": head})
print(f"branch {BRANCH} -> {result['object']['sha']}")
