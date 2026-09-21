"""Each target's switch, hours and limits, in the agent's own `state/settings.json`.

The runner is the only thing that writes this file, and it only does so through
`apply`, so the dashboard stays an editor that asks rather than a second writer.

A target the file has never heard of is off. Defaulting it to on would have an
agent start spending against a new target the night it appeared.
"""

import json
import os

BASE = [
    {"key": "budget", "label": "Ceiling a night", "type": "number",
     "default": 6.0, "min": 0, "max": 100, "step": 0.5},
    {"key": "max_items", "label": "Items a night (0 is no cap)", "type": "number",
     "default": 0, "min": 0, "max": 50, "step": 1},
]


def fields(hooks):
    return BASE + list(getattr(hooks, "FIELDS", []) or [])


def defaults(hooks):
    out = {"on": False, "hours": []}
    for f in fields(hooks):
        out[f["key"]] = f.get("default")
    return out


def path(state_dir):
    return os.path.join(state_dir, "settings.json")


def _read(state_dir):
    try:
        with open(path(state_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(state_dir, hooks, target_id):
    """An agent that already keeps its settings elsewhere names `load_settings`
    and `save_settings` in its hooks, and the runner reads and writes through them."""
    out = defaults(hooks)
    if hasattr(hooks, "load_settings"):
        row = hooks.load_settings(target_id)
    else:
        row = _read(state_dir).get(target_id)
    if isinstance(row, dict):
        out.update({k: v for k, v in row.items() if k in out})
    return out


def check(hooks, changes):
    """The changes cleaned, or an error saying what is wrong with them."""
    clean = {}
    known = {f["key"]: f for f in fields(hooks)}
    for key, value in (changes or {}).items():
        if key == "on":
            if not isinstance(value, bool):
                return None, "on must be true or false"
            clean["on"] = value
        elif key == "hours":
            if not isinstance(value, list) or any(
                    not isinstance(h, int) or isinstance(h, bool) or h < 0 or h > 23 for h in value):
                return None, "hours must be a list of whole hours from 0 to 23"
            clean["hours"] = sorted(set(value))
        elif key in known:
            f = known[key]
            if f.get("type") == "number":
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    return None, "%s must be a number" % f["label"]
                if "min" in f and num < f["min"]:
                    return None, "%s cannot be below %s" % (f["label"], f["min"])
                if "max" in f and num > f["max"]:
                    return None, "%s cannot be above %s" % (f["label"], f["max"])
                clean[key] = int(num) if float(f.get("step", 1)).is_integer() and num.is_integer() else num
            elif f.get("type") == "lines":
                if not isinstance(value, list):
                    return None, "%s must be a list of lines" % f["label"]
                clean[key] = [str(v) for v in value if str(v).strip()]
            else:
                clean[key] = str(value)
        else:
            return None, "there is no setting called %r" % key
    return clean, None


def save(state_dir, hooks, target_id, changes):
    clean, err = check(hooks, changes)
    if err:
        return err
    if hasattr(hooks, "save_settings"):
        return hooks.save_settings(target_id, clean)
    data = _read(state_dir)
    row = data.get(target_id) if isinstance(data.get(target_id), dict) else {}
    row.update(clean)
    data[target_id] = row
    os.makedirs(state_dir, exist_ok=True)
    tmp = path(state_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path(state_dir))
    return None
