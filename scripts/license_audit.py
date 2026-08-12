from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
from pathlib import Path


ALLOWED_MARKERS = {
    "0bsd",
    "apache",
    "bsd",
    "cc0",
    "isc",
    "lgpl",
    "mit",
    "mozilla public license",
    "mpl",
    "psf",
    "python software foundation",
    "the unlicense",
    "unlicense",
}
DENIED_PATTERN = re.compile(r"\b(?:agpl|gpl|sspl)(?:\b|-)")


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def acceptable(license_text: str) -> bool:
    value = normalized(license_text)
    allowed = any(marker in value for marker in ALLOWED_MARKERS)
    denied = bool(DENIED_PATTERN.search(value))
    return allowed and not (denied and not any(token in value for token in (" or mit", "mit or", "or apache")))


def python_license(distribution: importlib.metadata.Distribution) -> str:
    metadata = distribution.metadata
    declared = str(metadata.get("License-Expression") or metadata.get("License") or "").strip()
    if declared and declared.upper() != "UNKNOWN":
        return declared
    classifiers = metadata.get_all("Classifier") or []
    values = [item.split(" :: ")[-1] for item in classifiers if item.startswith("License ::")]
    return " OR ".join(values)


def audit_python() -> list[str]:
    failures: list[str] = []
    checked: set[tuple[str, str]] = set()
    skipped = {"pip", "setuptools", "wheel"}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "unknown")
        version = distribution.version
        key = (name.casefold(), version)
        if key in checked or name.casefold() in skipped:
            continue
        checked.add(key)
        license_text = python_license(distribution)
        if not acceptable(license_text):
            failures.append(f"python:{name}@{version}: {license_text or 'missing license metadata'}")
    print(f"Python license audit checked {len(checked)} distributions.")
    return failures


def audit_node(node_modules: Path) -> list[str]:
    failures: list[str] = []
    checked: set[tuple[str, str]] = set()
    for package_json in node_modules.rglob("package.json"):
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Packages such as nanoid expose subpath metadata files that are not
        # standalone dependencies and intentionally omit a version/license.
        if not package.get("version"):
            continue
        name = str(package.get("name") or package_json.parent.name)
        version = str(package["version"])
        key = (name.casefold(), version)
        if key in checked:
            continue
        checked.add(key)
        declared = package.get("license") or package.get("licenses") or ""
        if isinstance(declared, list):
            license_text = " OR ".join(str(item.get("type", "")) if isinstance(item, dict) else str(item) for item in declared)
        elif isinstance(declared, dict):
            license_text = str(declared.get("type", ""))
        else:
            license_text = str(declared)
        if not acceptable(license_text):
            failures.append(f"node:{name}@{version}: {license_text or 'missing license metadata'}")
    print(f"Node license audit checked {len(checked)} packages.")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit installed dependency license metadata.")
    parser.add_argument("--python", action="store_true", help="Audit the current Python environment")
    parser.add_argument("--node", type=Path, help="Path to a node_modules directory")
    args = parser.parse_args()
    if not args.python and args.node is None:
        parser.error("select --python and/or --node")

    failures: list[str] = []
    if args.python:
        failures.extend(audit_python())
    if args.node is not None:
        failures.extend(audit_node(args.node))
    if failures:
        print("Dependency license audit requires review:")
        for failure in sorted(failures):
            print(f"- {failure}")
        raise SystemExit(1)
    print("Dependency license audit passed.")


if __name__ == "__main__":
    main()
