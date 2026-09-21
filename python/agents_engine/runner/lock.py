"""One run at a time per target.

A directory rather than a file, because `mkdir` either creates it or fails in one
step, and a `pid` file inside naming the process that holds it. The process ID
is asked about before the age of the directory: a laptop shut mid-run suspends
the holder rather than killing it, so an old lock with a live holder is a run
that is still going, and a young lock with a dead holder is a crash. Age is only
the fallback for a lock that names nobody, which is what the to-dos planning
agent learnt between 6 and 8 Sep 2026.
"""

import os
import shutil
import time

STALE_AFTER = 2 * 60 * 60


def _pid(path):
    try:
        with open(os.path.join(path, "pid"), encoding="utf-8") as fh:
            return int(fh.read().strip() or 0) or None
    except (OSError, ValueError):
        return None


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def acquire(path):
    """Take the lock. Returns (taken, note): note says why not, or what was cleared."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    note = None
    try:
        os.mkdir(path)
    except FileExistsError:
        holder = _pid(path)
        if holder and _alive(holder):
            return False, "a run is already going (pid %d)" % holder
        if not holder:
            try:
                age = time.time() - os.path.getmtime(path)
            except OSError:
                age = STALE_AFTER
            if age < STALE_AFTER:
                return False, "a run is already going (no pid recorded, lock is fresh)"
        note = "cleared a stale lock (holder %s is gone)" % (holder or "unknown")
        shutil.rmtree(path, ignore_errors=True)
        try:
            os.mkdir(path)
        except FileExistsError:
            return False, "another wake took the lock first"
    with open(os.path.join(path, "pid"), "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    return True, note


def release(path):
    if _pid(path) == os.getpid():
        shutil.rmtree(path, ignore_errors=True)


def holder(path):
    """The live process holding it, or None."""
    pid = _pid(path)
    return pid if pid and _alive(pid) else None
