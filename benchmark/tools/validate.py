#!/usr/bin/env python3
"""Check the benchmark case files against the format in benchmark/README.md.

    python3 benchmark/tools/validate.py            format, ids and duplicates
    python3 benchmark/tools/validate.py --remote   also checks every commit and subdir on GitHub (needs `gh`)
    python3 benchmark/tools/validate.py FILE ...   only these case files (duplicates still checked against all)
"""
import argparse
import collections
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
ROOT = os.path.dirname(BENCH)

KINDS = {"git", "image", "upload"}
SOURCES = {"framework-example", "framework-template", "platform-sample", "awesome-compose", "awesome-selfhosted",
           "popular-github", "official-image", "linuxserver-image", "published-image"}
WEB_PACKAGING = {"static", "static-generator", "buildpack", "dockerfile", "compose", "image"}
REFUSE_PACKAGING = {"library", "cli", "desktop", "mobile", "docs", "empty"}
FACTS = {"port", "start_command", "build_command", "static_source", "primary_service", "dockerfile_path",
         "deployable_project", "build_args", "slots", "answers", "build_method"}
ID = re.compile(r"^bm-[a-z0-9-]{1,45}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
GH = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_KB = 150000


def load(path):
    try:
        with open(path) as f:
            cases = json.load(f)
    except (OSError, ValueError) as e:
        return None, [f"{path}: not readable JSON: {e}"]
    if not isinstance(cases, list):
        return None, [f"{path}: must hold a JSON array of cases"]
    return cases, []


def check_case(c, where):
    p = []
    if not isinstance(c, dict):
        return [f"{where}: a case must be an object"]
    cid = c.get("id", "")
    at = f"{where} {cid or '(no id)'}"
    if not ID.match(cid or ""):
        p.append(f"{at}: id must be `bm-` then lowercase letters, digits and `-`, at most 48 characters")
    kind = c.get("kind")
    if kind not in KINDS:
        p.append(f"{at}: kind must be one of {sorted(KINDS)}")
    if c.get("source") not in SOURCES:
        p.append(f"{at}: source must be one of {sorted(SOURCES)}")
    for f in ("framework", "language"):
        if not isinstance(c.get(f), str) or not c[f] or c[f] != c[f].lower():
            p.append(f"{at}: {f} is required, lowercase")
    expect = c.get("expect")
    pk = c.get("packaging")
    if expect == "web" and pk not in WEB_PACKAGING:
        p.append(f"{at}: packaging for a web case must be one of {sorted(WEB_PACKAGING)}")
    elif expect == "refuse" and pk not in REFUSE_PACKAGING | WEB_PACKAGING:
        p.append(f"{at}: packaging for a refusal must be one of {sorted(REFUSE_PACKAGING)}")
    elif expect not in ("web", "refuse"):
        p.append(f"{at}: expect must be `web` or `refuse`")
    if not isinstance(c.get("http_path"), str) or not c["http_path"].startswith("/"):
        p.append(f"{at}: http_path must start with /")
    if "expect_text" not in c or not (c["expect_text"] is None or isinstance(c["expect_text"], str)):
        p.append(f"{at}: expect_text must be a string or null")
    facts = c.get("facts")
    if not isinstance(facts, dict):
        p.append(f"{at}: facts must be an object")
    else:
        extra = set(facts) - FACTS
        if extra:
            p.append(f"{at}: unknown facts {sorted(extra)}; put other answers under facts.answers")
        if "port" in facts and not (isinstance(facts["port"], int) and 0 < facts["port"] < 65536):
            p.append(f"{at}: facts.port must be a number")
    if kind == "git":
        if not GH.match(c.get("url") or ""):
            p.append(f"{at}: url must be https://github.com/OWNER/REPO with no trailing slash or .git")
        if not SHA.match(c.get("commit") or ""):
            p.append(f"{at}: commit must be the full 40-character SHA")
        if not isinstance(c.get("ref"), str) or not c["ref"]:
            p.append(f"{at}: ref must name the branch the commit came from")
        if not isinstance(c.get("subdir"), str) or c["subdir"].startswith("/") or c["subdir"].endswith("/"):
            p.append(f"{at}: subdir must be a relative path without leading or trailing /, or \"\"")
        if not isinstance(c.get("size_kb"), int) or c["size_kb"] > MAX_KB:
            p.append(f"{at}: size_kb must be GitHub's size, at most {MAX_KB}; copy the example into apps/ instead")
    elif kind == "image":
        img = c.get("image") or ""
        if ":" not in img.rsplit("/", 1)[-1] and "@" not in img:
            p.append(f"{at}: image needs a tag")
    elif kind == "upload":
        if c.get("path") != f"benchmark/apps/{cid}":
            p.append(f"{at}: path must be benchmark/apps/{cid}")
        elif not os.path.isdir(os.path.join(ROOT, c["path"])):
            p.append(f"{at}: {c['path']} does not exist")
        o = c.get("origin") or {}
        if not (GH.match(o.get("url") or "") and SHA.match(o.get("commit") or "") and o.get("license")):
            p.append(f"{at}: origin needs url, a full commit and license")
    return p


def key_of(c):
    if c.get("kind") == "git":
        return "git:" + (c.get("url") or "").lower().rstrip("/") + "#" + (c.get("subdir") or "")
    if c.get("kind") == "image":
        return "image:" + (c.get("image") or "").split(":")[0].split("@")[0]
    if c.get("kind") == "upload":
        o = c.get("origin") or {}
        return "git:" + (o.get("url") or "").lower().rstrip("/") + "#" + (o.get("subdir") or "")
    return None


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return r.returncode == 0, r.stdout


def remote_check(c):
    if c.get("kind") != "git":
        return []
    repo = c["url"].split("github.com/", 1)[1]
    at = c["id"]
    ok, _ = gh(f"repos/{repo}/commits/{c['commit']}")
    if not ok:
        return [f"{at}: commit {c['commit'][:10]} is not in {repo}"]
    if c.get("subdir"):
        ok, _ = gh(f"repos/{repo}/contents/{c['subdir']}?ref={c['commit']}")
        if not ok:
            return [f"{at}: {c['subdir']} does not exist at {c['commit'][:10]}"]
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--remote", action="store_true")
    a = ap.parse_args()
    all_files = sorted(glob.glob(os.path.join(BENCH, "cases", "*.json")))
    chosen = {os.path.abspath(f) for f in a.files} or set(all_files)
    problems, cases = [], []
    for f in all_files:
        cs, p = load(f)
        problems += p
        for c in cs or []:
            cases.append((f, c))
    seen_ids = collections.Counter()
    seen_keys = collections.defaultdict(list)
    for f in ("generated.json", "public-repos.json", "images.json"):
        cs, _ = load(os.path.join(ROOT, "cases", f))
        for c in cs or []:
            seen_ids[c["id"]] += 1
            k = key_of(c) if c.get("kind") != "upload" else None
            if k:
                seen_keys[k].append(c["id"] + " (deploy QA)")
    for f, c in cases:
        if not isinstance(c, dict):
            continue
        seen_ids[c.get("id")] += 1
        k = key_of(c)
        if k:
            seen_keys[k].append(c.get("id"))
    for f, c in cases:
        if os.path.abspath(f) not in chosen:
            continue
        where = os.path.relpath(f, ROOT)
        own = check_case(c, where)
        problems += own
        if isinstance(c, dict):
            if seen_ids[c.get("id")] > 1:
                problems.append(f"{where} {c.get('id')}: id is used more than once")
            k = key_of(c)
            if k and len(seen_keys[k]) > 1 and seen_keys[k][0] != c.get("id"):
                problems.append(f"{where} {c.get('id')}: same app as {seen_keys[k][0]}")
            if a.remote and not own:
                problems += remote_check(c)
    by_fw = collections.Counter(c.get("framework") for _, c in cases if isinstance(c, dict))
    total = len(cases)
    print(f"{total} benchmark cases, plus the deploy QA cases")
    for fw, n in by_fw.most_common(8):
        flag = "  (over 8%)" if total >= 200 and fw != "none" and n > 0.08 * total else ""
        print(f"  {fw}: {n}{flag}")
    for p in problems:
        print("PROBLEM:", p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
