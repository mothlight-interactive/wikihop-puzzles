"""Checks a wikihop-puzzles checkout (phase 4): schemas, numbering, consistency and unchanged published files.

Standalone on purpose (Python 3.12 standard library + jsonschema): `wikihop_gen publish` copies it into the
puzzles repo as tools/validate.py, where validate.yml, deploy.yml and watcher.yml run it.

    python tools/validate.py [--base origin/main] [--today YYYY-MM-DD]   exit 1 on errors
    python tools/validate.py --days-left 365                            exit 3 when a language runs short
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

KINDS = [
    (re.compile(r"^languages\.json$"), "languages"),
    (re.compile(r"^[a-z]+/latest\.json$"), "latest"),
    (re.compile(r"^[a-z]+/daily/\d{4}-\d{2}-\d{2}\.json$"), "daily"),
    (re.compile(r"^[a-z]+/solutions/\d{4}-\d{2}-\d{2}\.json$"), "solution"),
    (re.compile(r"^[a-z]+/random/index\.json$"), "index"),
    (re.compile(r"^[a-z]+/random/retired\.json$"), "retired"),
    (re.compile(r"^[a-z]+/random/pool-\d{4}\.json$"), "pool"),
]


def kind_of(rel: str) -> str | None:
    return next((kind for pattern, kind in KINDS if pattern.match(rel)), None)


def load(root: Path, schema_path: Path) -> tuple[dict[str, tuple[str, dict]], list[str]]:
    """Every file under v1/ with its kind, plus schema errors."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validators = {kind: Draft202012Validator({**schema, "$ref": f"#/$defs/{kind}"}) for _, kind in KINDS}
    files, errors = {}, []
    v1 = root / "v1"
    for path in sorted(p for p in v1.rglob("*") if p.is_file()) if v1.exists() else []:
        rel = path.relative_to(v1).as_posix()
        kind = kind_of(rel)
        if kind is None:
            errors.append(f"{rel}: unexpected file")
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"{rel}: not JSON ({e})")
            continue
        for error in validators[kind].iter_errors(doc):
            errors.append(f"{rel}: {error.message} at /{'/'.join(map(str, error.absolute_path))}")
        files[rel] = (kind, doc)
    return files, errors


def check_language(lang: str, files: dict[str, tuple[str, dict]], today: date) -> list[str]:
    own = {rel: doc for rel, (_, doc) in files.items() if rel.startswith(f"{lang}/")}
    errors = [f"{rel}: lang is {doc.get('lang')}" for rel, doc in own.items() if doc.get("lang") != lang]
    by_kind = {}
    for rel, doc in own.items():
        by_kind.setdefault(files[rel][0], {})[rel] = doc
    daily = {Path(rel).stem: doc for rel, doc in by_kind.get("daily", {}).items()}
    solution = {Path(rel).stem: doc for rel, doc in by_kind.get("solution", {}).items()}
    for day in sorted(set(daily) ^ set(solution)):
        errors.append(f"{lang}: {day} has a daily file or a solution, not both")
    latest = own.get(f"{lang}/latest.json")
    if daily and latest is None:
        errors.append(f"{lang}: latest.json missing")
    first = date.fromisoformat(latest["first"]) if latest else None
    for day, doc in sorted(daily.items()):
        if doc["date"] != day:
            errors.append(f"{lang}/daily/{day}.json: date is {doc['date']}")
        if first and doc["number"] != (date.fromisoformat(day) - first).days + 1:
            errors.append(f"{lang}/daily/{day}.json: number {doc['number']} does not fit the first date {first}")
        sol = solution.get(day)
        if sol:
            if (sol["id"], sol["number"], sol["par"]) != (doc["id"], doc["number"], doc["par"]):
                errors.append(f"{lang}/solutions/{day}.json: id, number or par differ from the daily file")
            if len(sol["route"]) != sol["par"] + 1 or sol["route"][0] != doc["start"]["title"] \
                    or sol["route"][-1] != doc["target"]["title"]:
                errors.append(f"{lang}/solutions/{day}.json: route does not lead from start to target in par clicks")
    if latest and daily and (latest["first"], latest["latest"]) != (min(daily), max(daily)):
        errors.append(f"{lang}/latest.json: first/latest are not {min(daily)}/{max(daily)}")
    ids = [doc["id"] for doc in daily.values()]
    errors += [f"{lang}: pair {i} is the daily puzzle of two dates" for i in sorted({i for i in ids if ids.count(i) > 1})]

    pools = by_kind.get("pool", {})
    index = own.get(f"{lang}/random/index.json")
    if pools and (index is None or sorted(index["pools"]) != sorted(Path(rel).name for rel in pools)):
        errors.append(f"{lang}/random/index.json: does not list exactly the pool files")
    seen, future = {}, {doc["id"] for day, doc in daily.items() if date.fromisoformat(day) > today}
    for rel, doc in sorted(pools.items()):
        if doc["pool"] != int(Path(rel).stem.split("-")[1]):
            errors.append(f"{rel}: pool number is {doc['pool']}")
        for pair in doc["pairs"]:
            if pair["id"] in seen:
                errors.append(f"{rel}: pair {pair['id']} is also in {seen[pair['id']]}")
            seen[pair["id"]] = rel
            if pair["id"] in future:
                errors.append(f"{rel}: pair {pair['id']} is a daily puzzle that is still to come")
            if len(pair["route"]) != pair["par"] + 1 or pair["route"][0] != pair["start"]["title"] \
                    or pair["route"][-1] != pair["target"]["title"]:
                errors.append(f"{rel}: route of {pair['id']} does not lead from start to target in par clicks")
    return errors


def check_unchanged(root: Path, base: str, today: date) -> list[str]:
    """Published files of past dates and pool files must never change or disappear."""
    diff = subprocess.run(["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD", "--", "v1"], cwd=root,
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout
    errors = []
    for line in diff.splitlines():
        status, path = line.split("\t", 1)
        rel = path.removeprefix("v1/")
        kind = kind_of(rel)
        if status == "A" or kind not in ("daily", "solution", "pool"):
            continue
        if kind == "pool" or date.fromisoformat(Path(rel).stem) <= today:
            errors.append(f"{rel}: published file {'deleted' if status == 'D' else 'changed'}")
    return errors


def validate(root: Path, schema_path: Path, today: date, base: str | None = None) -> list[str]:
    files, errors = load(root, schema_path)
    langs = sorted({rel.split("/")[0] for rel in files if "/" in rel})
    for lang in langs:
        errors += check_language(lang, files, today)
    listed = files.get("languages.json", (None, {"languages": []}))[1]["languages"]
    with_latest = {rel.split("/")[0]: doc for rel, (kind, doc) in files.items() if kind == "latest"}
    if sorted(entry["code"] for entry in listed) != sorted(with_latest):
        errors.append("languages.json: does not list exactly the languages with a latest.json")
    for entry in listed:
        if entry["code"] in with_latest and entry["first"] != with_latest[entry["code"]]["first"]:
            errors.append(f"languages.json: first date of {entry['code']} differs from its latest.json")
    if base:
        errors += check_unchanged(root, base, today)
    return errors


def days_left(root: Path, today: date) -> dict[str, int]:
    """Daily puzzles after today, per language that has any."""
    v1 = root / "v1"
    return {p.parent.name: sum(date.fromisoformat(d.stem) > today for d in (p.parent / "daily").glob("*.json"))
            for p in sorted(v1.glob("*/latest.json"))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="puzzles checkout (default: current folder)")
    parser.add_argument("--schema", type=Path, help="default: <root>/schemas/v1.schema.json")
    parser.add_argument("--base", help="git ref to compare with, e.g. origin/main (PR check)")
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--days-left", type=int, help="only report languages with fewer daily puzzles left")
    args = parser.parse_args(argv)
    if args.days_left is not None:
        left = days_left(args.root, args.today)
        short = {lang: n for lang, n in left.items() if n < args.days_left}
        for lang, n in left.items():
            print(f"{lang}: {n} daily puzzles after {args.today}" + (" (short)" if lang in short else ""))
        return 3 if short or not left else 0
    errors = validate(args.root, args.schema or args.root / "schemas" / "v1.schema.json", args.today, args.base)
    for error in errors:
        print(error)
    print(f"{len(errors)} errors" if errors else "ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
