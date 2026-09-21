"""Reading and moving items in a folder-of-documents stream.

The container shape is `PACKAGES/work-streams/CONTRACT.md`'s: one item per
Markdown file, fields as `key: value` frontmatter lines, the body below.
`container.path` may hold `<target>`, which the runner fills with the target's
id, so one manifest serves one folder per target. It is resolved from the
agent's own folder.

Frontmatter is edited one line at a time rather than through a YAML writer, the
same as the planning agent's `stream.py`, because a parser would reflow values
that contain a colon.

Every write takes the stream's writer claim first (`work-streams/writer.py`),
so a move from the board and a move from a run cannot land on the same file at
once.
"""

import hashlib
import json
import os
import random
import re
import string
import sys

WS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "..", "..", "work-streams"))
if WS not in sys.path:
    sys.path.insert(0, WS)
try:
    import manifest as ws_manifest  # noqa: E402
    import writer as ws_writer  # noqa: E402
except ImportError:  # the runner still works without it, minus validation and the claim
    ws_manifest = ws_writer = None

FM_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)

# Fields the runner or the person moving the card writes. Left out of the
# fingerprint, because moving an item is not changing what it asks for.
# `feedback` is kept in: sending an item back with a reason is a change.
MOVES = ("state", "owner", "seen", "needs_you", "resolution", "id", "created")


class QueueError(RuntimeError):
    pass


def load_manifest(path):
    if ws_manifest is not None:
        m, errors = ws_manifest.load(path)
        if m is None or errors:
            raise QueueError("; ".join(errors) or "could not read %s" % path)
        return m
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise QueueError("could not read %s: %s" % (path, exc))


def folder(m, root, target_id):
    c = m.get("container") or {}
    if c.get("kind") != "doc-folder":
        raise QueueError("the runner reads doc-folder streams only, not %r" % c.get("kind"))
    return os.path.normpath(os.path.join(root, c["path"].replace("<target>", target_id)))


def lock_path(m, root):
    lock = (m.get("writer") or {}).get("lock")
    return os.path.join(root, lock) if lock else None


def truthy(value):
    return str(value or "").strip().lower() in ("yes", "true", "1")


def parse(text):
    fields, body = {}, text
    m = FM_RE.match(text)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t", "#")):
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip()
    return fields, body


def read(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fields, body = parse(text)
    heading = re.search(r"^#\s+(.+)$", body, re.M)
    title = fields.get("title") or (heading.group(1).strip() if heading else
                                    os.path.splitext(os.path.basename(path))[0])
    return {"name": os.path.basename(path), "path": path, "fields": fields,
            "body": body, "title": title, "id": fields.get("id") or ""}


def items(where, m=None):
    skip = set(((m or {}).get("container") or {}).get("skip") or []) | {"README.md", "stream.json"}
    if not os.path.isdir(where):
        return []
    out = []
    for name in sorted(os.listdir(where)):
        if name.endswith(".md") and name not in skip and not name.startswith((".", "_")):
            out.append(read(os.path.join(where, name)))
    out.sort(key=lambda i: (i["fields"].get("created") or "", i["name"]))
    return out


def fingerprint(item):
    keep = sorted((k, " ".join(v.split())) for k, v in item["fields"].items() if k not in MOVES)
    body = " ".join(item["body"].split())
    return hashlib.sha1(json.dumps([keep, body]).encode("utf-8")).hexdigest()[:16]


def _set(text, key, value):
    if not FM_RE.match(text):
        text = "---\n---\n" + text
    head = FM_RE.match(text)
    block, rest = head.group(1), text[head.end():]
    lines = [l for l in block.split("\n") if l != ""] if block else []
    value = " ".join(str(value).split()) if value is not None else ""
    found = False
    for i, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == key:
            found = True
            lines[i] = None if value == "" else "%s: %s" % (key, value)
            break
    if not found and value != "":
        lines.append("%s: %s" % (key, value))
    lines = [l for l in lines if l is not None]
    return "---\n" + "\n".join(lines) + "\n---\n" + rest


def _mint():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def write(item, changes, lock=None, who="the runner"):
    """Write whole values onto one item's frontmatter. None or '' removes a key."""
    if lock and ws_writer is not None:
        refused = ws_writer.refusal(lock, who)
        if refused:
            raise QueueError(refused)
        ws_writer.claim(lock, who)
    try:
        with open(item["path"], encoding="utf-8") as fh:
            text = fh.read()
        if not parse(text)[0].get("id"):
            changes = dict(changes, id=_mint())
        for key, value in changes.items():
            if isinstance(value, bool):
                value = "yes" if value else "no"
            text = _set(text, key, value)
        tmp = item["path"] + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, item["path"])
    finally:
        if lock and ws_writer is not None:
            ws_writer.release(lock)
    fresh = read(item["path"])
    item.update(fresh)
    return item


def apply(m, root, req, who):
    """The stream's `subprocess` writer: one transition from stdin, per the contract."""
    target = (req.get("item") or {}).get("group") or req.get("target") or ""
    name = (req.get("item") or {}).get("name") or ""
    to = req.get("to")
    if to not in (m.get("states") or {}):
        return {"ok": False, "error": "this stream has no state %r" % to}
    if not name or "/" in name or not name.endswith(".md"):
        return {"ok": False, "error": "bad item reference"}
    path = os.path.join(folder(m, root, target), name)
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such item"}
    changes = {"state": to, "owner": req.get("owner") or "me"}
    if "seen" in req:
        changes["seen"] = bool(req["seen"])
    if "resolution" in req:
        changes["resolution"] = req.get("resolution") or ""
    if req.get("reason"):
        changes["feedback"] = " ".join(req["reason"].split())[:500]
    if to == "ready":
        changes["needs_you"] = ""
    try:
        item = write(read(path), changes, lock_path(m, root), who)
    except QueueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "id": item["id"], "state": to}
