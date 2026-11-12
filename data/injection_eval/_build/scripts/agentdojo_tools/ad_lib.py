"""Re-implementation (no AgentDojo code imported/executed) of:
  - TaskSuite.load_and_inject_default_environment  (task_suite/task_suite.py, yaml_loader.py)
      env_text = yaml.dump(yaml.load(environment.yaml, ImportLoader), default_flow_style=False)  [str double-quoted]
      env = yaml.safe_load(env_text.format(**{defaults, **injections}))
  - pydantic model_dump of Email / CalendarEvent / CloudDriveFile / Transaction / Message (default_suites/v1/tools/*.py)
  - tool_result_to_str (agent_pipeline/tool_execution.py): yaml.safe_dump(model_dump).strip(), str() otherwise
"""
import datetime
import os
import re

import yaml


# ---------------------------------------------------------------- yaml loader / dumper replicas
class IncLoader(yaml.SafeLoader):
    def __init__(self, stream):
        try:
            self._root = os.path.split(stream.name)[0]
        except AttributeError:
            self._root = os.path.curdir
        super().__init__(stream)


def _construct_include(loader, node):
    fn = os.path.abspath(os.path.join(loader._root, str(loader.construct_scalar(node))))
    with open(fn, encoding="utf-8") as f:
        return yaml.load(f, IncLoader)


IncLoader.add_constructor("!include", _construct_include)


class QDumper(yaml.Dumper):  # yaml.add_representer(str, quoted_presenter) in agentdojo/yaml_loader.py
    pass


QDumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style='"'))


def read_suite_file(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f, IncLoader)
    return yaml.dump(data, Dumper=QDumper, default_flow_style=False)


class Suite:
    def __init__(self, repo, name):
        self.name = name
        d = os.path.join(repo, "src", "agentdojo", "data", "suites", name)
        self.env_text = read_suite_file(os.path.join(d, "environment.yaml"))
        vec = yaml.safe_load(read_suite_file(os.path.join(d, "injection_vectors.yaml")))
        self.defaults = {k: v["default"] for k, v in vec.items()}
        self.descriptions = {k: v.get("description", "") for k, v in vec.items()}

    def load_env(self, injections=None, fast=False):
        inj = dict(self.defaults)
        inj.update(injections or {})
        txt = self.env_text.format(**inj)
        if fast:  # libyaml, only for candidate screening; final items are re-built with yaml.safe_load
            return yaml.load(txt, Loader=yaml.CSafeLoader)
        return yaml.safe_load(txt)


# ---------------------------------------------------------------- pydantic model_dump replicas
def to_dt(v):
    if isinstance(v, datetime.datetime):
        return v
    if isinstance(v, datetime.date):
        return datetime.datetime(v.year, v.month, v.day)
    return datetime.datetime.fromisoformat(str(v))


def event_dump(e):
    return {
        "id_": e["id_"], "title": e["title"], "description": e["description"],
        "start_time": to_dt(e["start_time"]), "end_time": to_dt(e["end_time"]),
        "location": e.get("location"), "participants": list(e["participants"]),
        "all_day": bool(e.get("all_day", False)), "status": str(e.get("status", "confirmed")),
    }


def email_dump(e):
    att = []
    for a in e.get("attachments", []) or []:
        att.append(event_dump(a) if isinstance(a, dict) else a)
    return {
        "id_": e["id_"], "sender": e["sender"], "recipients": list(e["recipients"]),
        "cc": list(e.get("cc", []) or []), "bcc": list(e.get("bcc", []) or []),
        "subject": e["subject"], "body": e["body"], "status": str(e.get("status", "sent")),
        "read": bool(e.get("read", False)), "timestamp": to_dt(e["timestamp"]), "attachments": att,
    }


def file_dump(f):
    return {
        "id_": f["id_"], "filename": f["filename"], "content": f["content"], "owner": f["owner"],
        "last_modified": to_dt(f["last_modified"]),
        "shared_with": {k: str(v) for k, v in (f.get("shared_with") or {}).items()},
        "size": len(f["content"]),
    }


def tx_dump(t):
    return {"id": int(t["id"]), "sender": t["sender"], "recipient": t["recipient"], "amount": float(t["amount"]),
            "subject": t["subject"], "date": str(t["date"]), "recurring": bool(t["recurring"])}


def msg_dump(m):
    return {"sender": m["sender"], "recipient": m["recipient"], "body": m["body"]}


def ydump(obj):  # tool_result_to_str
    return yaml.safe_dump(obj).strip()


def review_str(entity):  # get_rating_reviews_for_{hotels,restaurants,car_rental}
    return "Rating: " + str(float(entity["rating"])) + "\n" + "Reviews: " + "\n".join(entity["reviews"])


# ---------------------------------------------------------------- items (one tool output each)
def items(suite, env):
    """yield (item_key, tool_name, doc_kind, text, field_getter) for every tool-output item of a suite."""
    out = []
    if suite == "workspace":
        for e in env["inbox"]["initial_emails"]:
            out.append((("email", e["id_"]), "search_emails", "email", ydump([email_dump(e)])))
        for e in env["calendar"]["initial_events"]:
            out.append((("calendar", e["id_"]), "search_calendar_events", "calendar", ydump([event_dump(e)])))
        for f in env["cloud_drive"]["initial_files"]:
            out.append((("drive", f["id_"]), "get_file_by_id", "drive", ydump(file_dump(f))))
    elif suite == "travel":
        for kind, key, tool in [("hotel", ("hotels", "hotel_list"), "get_rating_reviews_for_hotels"),
                                ("restaurant", ("restaurants", "restaurant_list"), "get_rating_reviews_for_restaurants"),
                                ("car", ("car_rental", "company_list"), "get_rating_reviews_for_car_rental")]:
            for ent in env[key[0]][key[1]]:
                out.append(((kind, ent["name"]), tool, "review", str({ent["name"]: review_str(ent)})))
    elif suite == "banking":
        for name, content in env["filesystem"]["files"].items():
            out.append((("file", name), "read_file", "file", content))
        out.append((("transactions", "all"), "get_most_recent_transactions", "transactions",
                    ydump([tx_dump(t) for t in env["bank_account"]["transactions"]])))
        out.append((("scheduled", "all"), "get_scheduled_transactions", "transactions",
                    ydump([tx_dump(t) for t in env["bank_account"]["scheduled_transactions"]])))
    elif suite == "slack":
        out.append((("channels", "all"), "get_channels", "channels", ydump(list(env["slack"]["channels"]))))
        for ch, msgs in env["slack"]["channel_inbox"].items():
            out.append((("channel_inbox", ch), "read_channel_messages", "chat", ydump([msg_dump(m) for m in msgs])))
        for u, msgs in env["slack"]["user_inbox"].items():
            out.append((("user_inbox", u), "read_inbox", "chat", ydump([msg_dump(m) for m in msgs])))
    return out


# ---------------------------------------------------------------- locate the injected block in rendered text
def _tok_re(tok):
    parts = []
    for c in tok:
        if c == "'":
            parts.append(r"(?:''|\\'|')")
        elif c == '"':
            parts.append(r'(?:\\"|")')
        elif c == "\\":
            parts.append(r"(?:\\\\|\\)")
        elif ord(c) > 126:
            parts.append("(?:%s|\\\\x%02X|\\\\u%04X|\\\\x%02x|\\\\u%04x)" % (re.escape(c), ord(c), ord(c), ord(c), ord(c)) if ord(c) < 256
                         else "(?:%s|\\\\u%04X|\\\\u%04x)" % (re.escape(c), ord(c), ord(c)))
        else:
            parts.append(re.escape(c))
    return "".join(parts)


SEP = r"(?:[ \t\r\n]|\\n|\\t|\\ |\\(?=\r?\n))+"


def locate(text, block):
    toks = block.split()
    pat = SEP.join(_tok_re(t) for t in toks)
    ms = list(re.finditer(pat, text))
    if len(ms) != 1:
        return None
    return ms[0].start(), ms[0].end()
