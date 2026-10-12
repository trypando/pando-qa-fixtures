#!/usr/bin/env python3
"""List every image the corpus pulls, and where each can be pulled from without
using Docker Hub's pull limit.

    python3 benchmark/tools/images.py [--extra IMAGE ...]

Reads each case at its pinned commit: published images, the FROM lines of its
Dockerfiles (with ARG defaults applied), and the `image:` and `build:` entries
of its compose file. `--extra` adds images the deployer itself pulls (Pando's
Traefik, BuildKit, database images and so on). Writes benchmark/images.json:

    {"image": "node:20-alpine", "registry": "docker.io", "via": "mirror.gcr.io", "cases": [...]}

`via` is where the benchmark should pull it from: `mirror.gcr.io` or
`public.ecr.aws` when either mirror serves that exact tag, the registry itself
when it is not Docker Hub, and `docker.io` when only Docker Hub has it. Only the
last kind counts against Docker Hub's limit. Checks use HEAD requests, which
Docker Hub does not count.
"""
import argparse
import collections
import concurrent.futures
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
ROOT = os.path.dirname(BENCH)
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")


def http(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read() if method == "GET" else b""
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def raw(url, commit, path):
    repo = url.split("github.com/", 1)[1]
    code, body = http(f"https://raw.githubusercontent.com/{repo}/{commit}/{path}")
    return body.decode("utf-8", "replace") if code == 200 else None


def local(path):
    try:
        with open(os.path.join(ROOT, path)) as f:
            return f.read()
    except OSError:
        return None


def interpolate(s, env):
    def sub(m):
        name, default = m.group(1), m.group(3)
        return env.get(name) or default or ""
    return re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(:?-([^}]*))?\}?", sub, s)


def dockerfile_images(text):
    """Base images named by FROM, skipping earlier stages and scratch."""
    args, stages, out = {}, set(), []
    for line in re.sub(r"\\\n", " ", text).splitlines():
        line = line.strip()
        m = re.match(r"(?i)^ARG\s+([A-Za-z_][A-Za-z0-9_]*)(?:=(\S+))?", line)
        if m and m.group(2):
            args.setdefault(m.group(1), m.group(2).strip("\"'"))
            continue
        m = re.match(r"(?i)^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line)
        if m:
            img = interpolate(m.group(1), args)
            if img and img.lower() != "scratch" and img.lower() not in stages and "$" not in img:
                out.append(img)
            if m.group(2):
                stages.add(m.group(2).lower())
    return out


def compose_entries(text):
    """Pulled images, and (context, dockerfile) for each build, per service.
    A service with both `image:` and `build:` names what it builds; nothing is
    pulled for it."""
    images, builds = [], []
    for block in service_blocks(text):
        imgs, blds = block_entries(block)
        builds += blds
        if not blds:
            images += imgs
    return images, builds


def service_blocks(text):
    """The lines of each service under the top-level `services:` key."""
    lines = text.splitlines()
    blocks, cur, inside, child = [], None, False, None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind = len(line) - len(line.lstrip())
        if ind == 0:
            inside = line.startswith("services:")
            continue
        if not inside:
            continue
        if child is None:
            child = ind
        if ind == child:
            cur = []
            blocks.append(cur)
        elif cur is not None:
            cur.append(line)
    return blocks


def block_entries(lines):
    images, builds = [], []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)image:\s*[\"']?([^\"'#\s]+)", line)
        if m:
            images.append(interpolate(m.group(2), {}))
            continue
        m = re.match(r"^(\s*)build:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2).strip().strip("\"'")
        if rest and not rest.startswith("#"):
            builds.append((rest, "Dockerfile"))
            continue
        ctx, df = ".", "Dockerfile"
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            k = re.match(r"^\s*(context|dockerfile):\s*[\"']?([^\"'#\s]+)", nxt)
            if k:
                if k.group(1) == "context":
                    ctx = k.group(2)
                else:
                    df = k.group(2)
        builds.append((ctx, df))
    return images, builds


def join(*parts):
    p = os.path.normpath("/".join(x for x in parts if x and x != "."))
    return "" if p == "." else p


def images_for(case):
    """The images one case pulls, as far as its files say."""
    kind = case.get("kind")
    if kind == "image":
        return [case["image"]]
    if kind == "git":
        # Deploy QA's repositories are pinned to a branch, not a commit.
        read = lambda p: raw(case["url"], case.get("commit") or case.get("ref") or "HEAD", p)
        base = case.get("subdir") or ""
    elif kind == "upload":
        read = local
        base = case.get("path") or ""
    else:
        return []
    facts = case.get("facts") or {}
    found = []
    for name in COMPOSE_NAMES:
        text = read(join(base, name))
        if text is None:
            continue
        imgs, builds = compose_entries(text)
        found += imgs
        for ctx, df in builds:
            t = read(join(base, ctx, df))
            if t:
                found += dockerfile_images(t)
        return found
    text = read(join(base, facts.get("dockerfile_path") or "Dockerfile"))
    if text:
        found += dockerfile_images(text)
    return found


def normalize(img):
    """(registry, repository, tag) with Docker Hub's defaults filled in."""
    img = img.split("@")[0]
    first = img.split("/")[0]
    if "/" in img and ("." in first or ":" in first or first == "localhost"):
        registry, rest = first, img.split("/", 1)[1]
    else:
        registry, rest = "docker.io", img
    if registry == "docker.io" and "/" not in rest:
        rest = "library/" + rest
    if ":" in rest.rsplit("/", 1)[-1]:
        repo, tag = rest.rsplit(":", 1)
    else:
        repo, tag = rest, "latest"
    return registry, repo, tag


def head(url, token=None):
    h = {"Accept": ACCEPT}
    if token:
        h["Authorization"] = "Bearer " + token
    code, _ = http(url, method="HEAD", headers=h)
    return code


def ecr_token():
    code, body = http("https://public.ecr.aws/token/")
    return json.loads(body)["token"] if code == 200 else None


def docker_hub_token(repo):
    code, body = http(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull")
    return json.loads(body)["token"] if code == 200 else None


def route(img, ecr):
    registry, repo, tag = normalize(img)
    if registry != "docker.io":
        return registry, registry
    if head(f"https://mirror.gcr.io/v2/{repo}/manifests/{tag}") == 200:
        return registry, "mirror.gcr.io"
    if repo.startswith("library/") and ecr and \
            head(f"https://public.ecr.aws/v2/docker/{repo}/manifests/{tag}", ecr) == 200:
        return registry, "public.ecr.aws"
    if head(f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}", docker_hub_token(repo)) == 200:
        return registry, "docker.io"
    return registry, "missing"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extra", nargs="*", default=[], help="images the deployer itself pulls")
    a = ap.parse_args()
    cases = []
    files = sorted(glob.glob(os.path.join(BENCH, "cases", "*.json")))
    files += [os.path.join(ROOT, "cases", f) for f in ("generated.json", "public-repos.json", "images.json")]
    for f in files:
        with open(f) as fh:
            cases += json.load(fh)
    uses = collections.defaultdict(list)
    for img in a.extra:
        uses[img].append("(deployer)")
    with concurrent.futures.ThreadPoolExecutor(16) as ex:
        for c, imgs in zip(cases, ex.map(images_for, cases)):
            for img in imgs:
                uses[img].append(c["id"])
    ecr = ecr_token()
    names = sorted(uses)
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        routes = list(ex.map(lambda i: route(i, ecr), names))
    rows = [{"image": i, "registry": r, "via": v, "cases": sorted(set(uses[i]))} for i, (r, v) in zip(names, routes)]
    with open(os.path.join(BENCH, "images.json"), "w") as f:
        json.dump(rows, f, indent=1)
        f.write("\n")
    by = collections.Counter(r["via"] for r in rows)
    print(f"{len(rows)} distinct images across {len(cases)} cases")
    for via, n in by.most_common():
        print(f"  {via}: {n}")
    hub = [r["image"] for r in rows if r["via"] == "docker.io"]
    if hub:
        print(f"{len(hub)} only on Docker Hub; each is one pull when a shared cache fetches it once.")
    for r in rows:
        if r["via"] == "missing":
            print(f"MISSING: {r['image']} (used by {', '.join(r['cases'][:5])})")


if __name__ == "__main__":
    sys.exit(main())
