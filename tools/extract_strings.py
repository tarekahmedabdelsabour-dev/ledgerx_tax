"""Lists every English string that needs an Arabic translation -> stdout as JSON list."""
import glob
import importlib.util
import json
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
out = set()


def load(path):
	spec = importlib.util.spec_from_file_location("m", path)
	m = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(m)
	return m


g = load(os.path.join(ROOT, "tools", "gen_doctypes.py"))
for name, d in g.DT.items():
	out.add(name)
	for f in d["fields"]:
		for k in ("label", "description"):
			if f.get(k):
				out.add(f[k])
		if f["fieldtype"] == "Select":
			out.update(x for x in f["options"].split("\n") if x)

src = open(os.path.join(ROOT, "tools", "gen_workspace.py"), encoding="utf-8").read().split("def write(path")[0]
ns = {}
exec(src.replace("BASE = os.path.join(os.path.dirname(__file__)", "BASE = os.path.join('.'"), ns)
for c in ns["CARDS"]:
	out.add(c[0])
for c in ns["CHARTS"]:
	out.add(c[0])
for title, _i, _c, items in ns["GROUPS"]:
	out.add(title)
	for label, *_r in items:
		out.add(label)
out.update({"Home", "E-Invoicing", "Setup"})

SKIP_DIRS = (os.sep + "tests" + os.sep, os.sep + "engine" + os.sep, os.sep + "tools" + os.sep)
pkg = os.path.join(ROOT, "ledgerx_tax")
for p in glob.glob(os.path.join(pkg, "**", "*.py"), recursive=True) + glob.glob(os.path.join(pkg, "**", "*.js"), recursive=True):
	if any(d in p for d in SKIP_DIRS) or "jsbarcode" in p:
		continue
	t = open(p, encoding="utf-8").read()
	for m in re.finditer(r"""\b_{1,2}\(\s*(["'])((?:\\.|(?!\1).)+)\1""", t):
		out.add(m.group(2).replace('\\"', '"'))
print(json.dumps(sorted(out), ensure_ascii=False, indent=0))
