#!/usr/bin/env python3
"""plugin-line: an Enginehost plugin line is compose(upstream commit, plugin-core commit, line id).

The owner's rule: plugin-core is authoritative. A line branch (plugin/<id>) is a cache of a
composition and nothing is authored on it. compose is deterministic and runs on git objects
only (a private index, no checkout):

  1. the tree of the upstream commit;
  2. plugin-core's whole tree written over it;
  3. plugin-core's enginehost/lines/<id>/root/** written over the repository root
     (the files that legitimately differ per line, such as bundle-metadata.json);
  4. plugin-core's patch series (enginehost/patches/series) for the line's upstream version;
  5. enginehost/line.json, the pin: line id, upstream commit and version, plugin-core commit.

Commands (run inside a clone of the plugin repository):
  compose <id> [--pc REV] [--upstream SHA] [--version V] [--commit] [--branch REF]
  check   [--line REV] [--core REF]      the CI check: recompose the line from its pin, compare
  walk    <id> --workflow FILE [--core REF] [--max N] [--dry-run]
                                         newest-to-oldest plugin-core commits until one builds
  diff    <id> [--line REV]              explain how an existing line differs from compose
  status  [--core REF]                   every declared line composes at plugin-core's tip; pins
Any command takes --fetch REMOTE: missing commits are fetched shallow and blob-less (CI clones).

Line declaration in plugin-core, enginehost/lines/<id>/line.json:
  {"upstream": {"repo": "owner/name", "ref": "<tag or branch>", "commit": "<sha>"},
   "version": "<dotted upstream version, used for patch ranges>"}
Patch series, enginehost/patches/series: one patch per line, "<range> <file>" where range is
"*" or space-free comparisons joined by ",": ">=8.0,<8.6". Lines starting with # are comments.
"""
import argparse, json, os, re, subprocess, sys, tempfile

LINE_FILE = "enginehost/line.json"
LINES_DIR = "enginehost/lines"
SERIES = "enginehost/patches/series"


def git(*args, env=None, input=None, check=True):
    p = subprocess.run(["git", *args], capture_output=True, text=True, env=env, input=input)
    if check and p.returncode:
        sys.exit(f"git {' '.join(args)} failed:\n{p.stderr.strip()}")
    return p.stdout


def rev(r):
    return git("rev-parse", "--verify", "--quiet", f"{r}^{{commit}}", check=False).strip()


def show(r, path, required=False):
    p = subprocess.run(["git", "show", f"{r}:{path}"], capture_output=True)
    if p.returncode:
        if required:
            sys.exit(f"{path} is missing in {r}")
        return None
    return p.stdout


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def in_range(version, spec):
    if spec.strip() == "*":
        return True
    v = vtuple(version)
    for term in spec.split(","):
        m = re.fullmatch(r"(>=|<=|==|>|<)([\d.]+)", term.strip())
        if not m:
            sys.exit(f"bad range term {term!r} in {SERIES}")
        op, w = m.group(1), vtuple(m.group(2))
        n = max(len(v), len(w))
        a, b = v + (0,) * (n - len(v)), w + (0,) * (n - len(w))
        if not {">=": a >= b, "<=": a <= b, "==": a == b, ">": a > b, "<": a < b}[op]:
            return False
    return True


def declaration(pc, line_id):
    raw = show(pc, f"{LINES_DIR}/{line_id}/line.json")
    return json.loads(raw) if raw else None


def compose_tree(pc, upstream, version, line_id):
    """Return (tree sha, list of patches applied)."""
    fd, index = tempfile.mkstemp(prefix="plugin-line-index-")
    os.close(fd)
    os.unlink(index)
    env = dict(os.environ, GIT_INDEX_FILE=index)
    try:
        git("read-tree", upstream, env=env)
        entries = git("ls-tree", "-r", "--full-tree", pc).splitlines()
        info = [e for e in entries]  # "<mode> <type> <sha>\t<path>"
        root = f"{LINES_DIR}/{line_id}/root/"
        info += [e.split("\t", 1)[0] + "\t" + e.split("\t", 1)[1][len(root):]
                 for e in entries if e.split("\t", 1)[1].startswith(root)]
        # update-index --index-info wants "<mode> <sha>\t<path>" (type is accepted too).
        git("update-index", "--index-info", env=env, input="\n".join(info) + "\n")
        applied = []
        series = show(pc, SERIES)
        if series:
            for raw in series.decode().splitlines():
                raw = raw.strip()
                if not raw or raw.startswith("#"):
                    continue
                spec, name = raw.split(None, 1)
                if not in_range(version, spec):
                    continue
                body = show(pc, f"enginehost/patches/{name}", required=True)
                with tempfile.NamedTemporaryFile(suffix=".patch", delete=False) as f:
                    f.write(body)
                p = subprocess.run(["git", "apply", "--cached", "--whitespace=nowarn", f.name],
                                   capture_output=True, text=True, env=env)
                os.unlink(f.name)
                if p.returncode:
                    sys.exit(f"patch {name} ({spec}) does not apply to {upstream[:10]} "
                             f"(version {version}):\n{p.stderr.strip()}")
                applied.append(name)
        pin = json.dumps({"line": line_id, "upstream": upstream, "upstreamVersion": version,
                          "pluginCore": pc}, indent=2) + "\n"
        blob = git("hash-object", "-w", "--stdin", input=pin).strip()
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{LINE_FILE}", env=env)
        return git("write-tree", env=env).strip(), applied
    finally:
        if os.path.exists(index):
            os.unlink(index)


FETCH = None  # remote to fetch missing commits from (shallow, blob-less), set by --fetch


def ensure(c):
    """Make commit c available, fetching it shallow and blob-less from FETCH when allowed."""
    if c and not rev(c) and FETCH:
        git("fetch", "-q", "--filter=blob:none", "--depth=1", FETCH, c, check=False)
    return rev(c)


def resolve(line_id, pc, upstream=None, version=None):
    decl = declaration(pc, line_id)
    if decl:
        upstream = upstream or decl["upstream"]["commit"]
        version = version or decl["version"]
    if not upstream or not version:
        sys.exit(f"plugin-core {pc[:10]} declares no line {line_id!r} "
                 f"({LINES_DIR}/{line_id}/line.json); pass --upstream and --version")
    return rev(upstream) or sys.exit(f"upstream commit {upstream} is not in this clone"), version


def describe(c):
    return git("describe", "--tags", "--always", c, check=False).strip() or c[:10]


def make_commit(tree, parents, line_id, upstream, pc, applied):
    msg = (f"Compose plugin/{line_id}: upstream {describe(upstream)} + plugin-core {pc[:10]}\n\n"
           f"Generated by plugin-line compose; nothing on this branch is authored by hand.\n"
           f"Upstream: {upstream}\nplugin-core: {pc}\n"
           + (f"Patches: {', '.join(applied)}\n" if applied else ""))
    args = ["commit-tree", tree]
    seen = []
    for p in parents:
        if p and p not in seen:
            seen.append(p)
            args += ["-p", p]
    return git(*args, "-m", msg).strip()


def cmd_compose(a):
    pc = rev(a.pc) or sys.exit(f"no plugin-core at {a.pc}")
    upstream, version = resolve(a.id, pc, a.upstream, a.version)
    tree, applied = compose_tree(pc, upstream, version, a.id)
    print(f"tree {tree}  upstream {describe(upstream)}  plugin-core {pc[:10]}  patches {applied or '-'}")
    if a.commit or a.branch:
        branch = a.branch or f"plugin/{a.id}"
        prev = rev(branch)
        if prev and git("rev-parse", f"{prev}^{{tree}}").strip() == tree:
            print(f"{branch} already has this tree ({prev[:10]})")
            return
        c = make_commit(tree, [prev, upstream, pc], a.id, upstream, pc, applied)
        git("update-ref", f"refs/heads/{branch}", c)
        print(f"commit {c} -> refs/heads/{branch}")


def cmd_check(a):
    line = rev(a.line) or sys.exit(f"no line at {a.line}")
    raw = show(line, LINE_FILE)
    if raw is None:
        sys.exit(f"FAIL: {LINE_FILE} is missing, so nobody can rebuild this line from upstream + "
                 f"plugin-core. Compose it with plugin-line (droidtop-platforms tools/plugin-line).")
    pin = json.loads(raw)
    pc, upstream, version, line_id = pin["pluginCore"], pin["upstream"], pin["upstreamVersion"], pin["line"]
    for what, c in (("plugin-core", pc), ("upstream", upstream)):
        if not ensure(c):
            sys.exit(f"FAIL: pinned {what} commit {c} is not reachable; it must be pushed")
    problems = []
    core = rev(a.core)
    if core and subprocess.run(["git", "merge-base", "--is-ancestor", pc, core]).returncode:
        problems.append(f"pinned plugin-core {pc[:10]} is not on {a.core}")
    decl = declaration(pc, line_id)
    if decl and decl["upstream"]["commit"] != upstream and ensure(decl["upstream"]["commit"]) != upstream:
        problems.append(f"line.json upstream {upstream[:10]} differs from plugin-core's declaration "
                        f"{decl['upstream']['commit'][:10]} for line {line_id}")
    tree, _ = compose_tree(pc, upstream, version, line_id)
    actual = git("rev-parse", f"{line}^{{tree}}").strip()
    if tree != actual:
        diff = git("diff-tree", "-r", "--name-status", tree, actual).strip()
        problems.append("the line differs from upstream + plugin-core (status is line vs compose):\n"
                        + "\n".join("  " + l for l in diff.splitlines()))
    behind = ""
    if core and core != pc:
        n = git("rev-list", "--count", f"{pc}..{core}").strip()
        behind = f"; pinned {n} commit(s) below plugin-core's tip (compat debt)"
    if problems:
        print(f"FAIL plugin/{line_id}:\n- " + "\n- ".join(problems))
        print("Wrapper changes belong on plugin-core; recompose the line with plugin-line compose.")
        sys.exit(1)
    print(f"OK plugin/{line_id} = {describe(upstream)} + plugin-core {pc[:10]}{behind}")


def cmd_status(a):
    """Every line plugin-core declares must compose at its tip; report each line branch's pin."""
    core = rev(a.core) or sys.exit(f"no {a.core}")
    ids = [p.rsplit("/", 1)[1] for p in git("ls-tree", "--name-only", core, f"{LINES_DIR}/").split()]
    branches = {r.rsplit("/plugin/", 1)[1]: r for r in
                git("for-each-ref", "--format=%(refname)", f"refs/remotes/{a.remote}/plugin/").split()}
    failed = []
    print(f"plugin-core {core[:10]}: {len(ids)} declared line(s)")
    print("| line | upstream | composes at tip | line branch pin |")
    print("| --- | --- | --- | --- |")
    for i in ids:
        decl = declaration(core, i)
        up = ensure(decl["upstream"]["commit"])
        try:
            if not up:
                raise SystemExit(f"upstream {decl['upstream']['commit'][:10]} not reachable")
            compose_tree(core, up, decl["version"], i)
            ok = "yes"
        except SystemExit as e:
            ok = f"NO: {str(e).splitlines()[0]}"
            failed.append(i)
        pin = "no branch"
        if i in branches:
            raw = show(branches[i], LINE_FILE)
            if raw is None:
                pin = "not composed (no line.json)"
            else:
                pc = json.loads(raw)["pluginCore"]
                pin = "tip" if pc == core else f"{pc[:10]} (behind the tip: compat debt)"
        print(f"| {i} | {decl['upstream'].get('ref', '')} {decl['upstream']['commit'][:10]} | {ok} | {pin} |")
    for b in sorted(set(branches) - set(ids)):
        print(f"| {b} | - | undeclared in plugin-core | - |")
    if failed:
        sys.exit(f"{len(failed)} declared line(s) do not compose at plugin-core's tip: {', '.join(failed)}")


def gh(*args, check=True):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and p.returncode:
        sys.exit(f"gh {' '.join(args)} failed:\n{p.stderr.strip()}")
    return p


def cmd_walk(a):
    core = rev(a.core) or sys.exit(f"no {a.core}")
    cands = git("rev-list", "--first-parent", f"--max-count={a.max}", core).split()
    for pc in cands:
        decl = declaration(pc, a.id)
        upstream = a.upstream or (decl and decl["upstream"]["commit"])
        version = a.version or (decl and decl["version"])
        if not upstream or not version:
            print(f"{pc[:10]}: declares no line {a.id}; pass --upstream/--version to go further back")
            continue
        try:
            tree, applied = compose_tree(pc, rev(upstream), version, a.id)
        except SystemExit as e:
            print(f"{pc[:10]}: does not compose: {e}")
            continue
        if a.dry_run:
            print(f"{pc[:10]}: composes (tree {tree[:10]}, patches {applied or '-'})")
            continue
        commit = make_commit(tree, [rev(upstream), pc], a.id, rev(upstream), pc, applied)
        branch = f"ci/pcwalk-{a.id}-{pc[:8]}"
        git("push", "-f", a.remote, f"{commit}:refs/heads/{branch}")
        try:
            gh("workflow", "run", a.workflow, "--ref", branch)
            run_id = None
            for _ in range(30):
                out = gh("run", "list", "--workflow", a.workflow, "--branch", branch, "--limit", "1",
                         "--json", "databaseId,headSha", "--jq", ".[0].databaseId", check=False).stdout.strip()
                if out:
                    run_id = out
                    break
                subprocess.run(["sleep", "10"])
            if not run_id:
                print(f"{pc[:10]}: no run appeared for {branch}")
                continue
            ok = subprocess.run(["gh", "run", "watch", run_id, "--exit-status", "--interval", "60"],
                                capture_output=True).returncode == 0
            print(f"{pc[:10]}: run {run_id} {'GREEN' if ok else 'red'}")
            if ok:
                print(f"PIN {a.id}: upstream {upstream} plugin-core {pc}"
                      + ("" if pc == core else f"  (compat debt: {cands.index(pc)} commit(s) below the tip)"))
                return
        finally:
            git("push", a.remote, f":refs/heads/{branch}", check=False)
    sys.exit(f"no plugin-core commit among the last {len(cands)} builds line {a.id}")


def cmd_diff(a):
    line = rev(a.line or f"plugin/{a.id}")
    raw = show(line, LINE_FILE)
    pin = json.loads(raw) if raw else {}
    pc = rev(a.pc or pin.get("pluginCore") or "plugin-core")
    upstream, version = resolve(a.id, pc, a.upstream or pin.get("upstream"), a.version or pin.get("upstreamVersion"))
    tree, applied = compose_tree(pc, upstream, version, a.id)
    up_tree = git("rev-parse", f"{upstream}^{{tree}}").strip()
    pc_paths = set(git("ls-tree", "-r", "--name-only", "--full-tree", pc).split("\n"))
    for line_ in git("diff-tree", "-r", "--name-status", tree, line).splitlines():
        status, path = line_.split("\t", 1)
        kind = "plugin-core file differs" if path in pc_paths else (
            "line-only, not upstream" if not git("ls-tree", up_tree, "--", path).strip() else "upstream file edited on the line")
        print(f"{status}\t{kind:32}\t{path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compose"); c.add_argument("id"); c.add_argument("--pc", default="plugin-core")
    c.add_argument("--upstream"); c.add_argument("--version"); c.add_argument("--commit", action="store_true")
    c.add_argument("--branch"); c.set_defaults(f=cmd_compose)
    k = sub.add_parser("check"); k.add_argument("--line", default="HEAD"); k.add_argument("--core", default="origin/plugin-core")
    k.set_defaults(f=cmd_check)
    w = sub.add_parser("walk"); w.add_argument("id"); w.add_argument("--workflow", required=True)
    w.add_argument("--core", default="origin/plugin-core"); w.add_argument("--max", type=int, default=50)
    w.add_argument("--upstream"); w.add_argument("--version"); w.add_argument("--remote", default="origin")
    w.add_argument("--dry-run", action="store_true"); w.set_defaults(f=cmd_walk)
    d = sub.add_parser("diff"); d.add_argument("id"); d.add_argument("--line"); d.add_argument("--pc")
    d.add_argument("--upstream"); d.add_argument("--version"); d.set_defaults(f=cmd_diff)
    s = sub.add_parser("status"); s.add_argument("--core", default="origin/plugin-core")
    s.add_argument("--remote", default="origin"); s.set_defaults(f=cmd_status)
    for p in (c, k, w, d, s):
        p.add_argument("--fetch", metavar="REMOTE", help="fetch missing commits shallow from REMOTE")
    a = ap.parse_args()
    global FETCH
    FETCH = a.fetch
    a.f(a)


if __name__ == "__main__":
    main()
