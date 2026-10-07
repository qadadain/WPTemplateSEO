#!/usr/bin/env python3
"""Compare les versions declarees dans .env et build/plugins.txt aux dernieres
versions publiees, ecrit un rapport markdown, et peut appliquer les mises a
jour avec --fix."""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STABLE_API = "https://api.wordpress.org/core/stable-check/1.0/"
PLUGIN_API = (
    "https://api.wordpress.org/plugins/info/1.2/"
    "?action=plugin_information&request[slug]={}"
)
UA = {"User-Agent": "version-check (incident response tooling)"}

# Extensions commerciales versionnees dans le depot dont la version gratuite
# au catalogue suit la meme numerotation.
VENDORED_SLUGS = {
    "advanced-custom-fields-pro": "advanced-custom-fields",
}

# Extensions commerciales dont la derniere version se lit dans un changelog
# public, faute d'API. Le motif cible le titre de section de chaque version.
VENDORED_CHANGELOG = {
    "ameliabooking": (
        "https://wpamelia.com/documentation/changelog/",
        r"<h2[^>]*>\s*Version\s+([0-9][0-9.]*)\s*\(",
    ),
}

ENV_PATH = Path(".env")
PLUGINS_PATH = Path("build/plugins.txt")
VENDORED_ROOT = Path("code/plugins")


def get_text(url):
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def check_changelog(url, pattern):
    try:
        found = re.findall(pattern, get_text(url))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None
    return max(found, key=to_tuple) if found else None


def get_json(url):
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def to_tuple(version):
    return tuple(
        int(part) if part.isdigit() else 0
        for part in re.split(r"[.\-+]", version)
    )


def is_older(current, latest):
    a, b = to_tuple(current), to_tuple(latest)
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) < b + (0,) * (size - len(b))


def is_major_jump(current, latest):
    return to_tuple(current)[0] != to_tuple(latest)[0]


def read_core_version():
    if not ENV_PATH.exists():
        return None
    match = re.search(
        r"WORDPRESS_DOWNLOAD_URL=.*?wordpress-([0-9][0-9.]*)\.tar\.gz",
        ENV_PATH.read_text(),
    )
    return match.group(1) if match else None


def read_plugins_txt():
    entries = []
    if not PLUGINS_PATH.exists():
        return entries
    for line in PLUGINS_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        filename = stripped.rsplit("/", 1)[-1]
        match = re.match(r"^(.+?)\.(\d[\d.]*)\.zip$", filename)
        entries.append(
            (match.group(1), match.group(2)) if match else (filename, None)
        )
    return entries


def read_vendored_plugins():
    vendored = []
    if not VENDORED_ROOT.is_dir():
        return vendored
    for directory in sorted(p for p in VENDORED_ROOT.iterdir() if p.is_dir()):
        version = None
        for php_file in sorted(directory.glob("*.php")):
            header = php_file.read_text(errors="ignore")[:4000]
            match = re.search(r"^\s*\*?\s*Version:\s*(\S+)", header, re.M | re.I)
            if match:
                version = match.group(1)
                break
        vendored.append((directory.name, version))
    return vendored


def resolve_served_version(declared, stable):
    if declared is None or len(to_tuple(declared)) >= 3:
        return declared
    candidates = [
        v for v in stable if v == declared or v.startswith(declared + ".")
    ]
    return max(candidates, key=to_tuple) if candidates else declared


def check_core(declared):
    stable = get_json(STABLE_API)
    latest = next((v for v, s in stable.items() if s == "latest"), None)
    served = resolve_served_version(declared, stable)
    return served, latest, stable.get(served, "inconnue")


def check_plugin(slug, current):
    try:
        return get_json(PLUGIN_API.format(urllib.parse.quote(slug)))["version"]
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, TypeError):
        return None


def apply_core_bump(declared, latest):
    target = ".".join(latest.split(".")[:2]) if len(to_tuple(declared)) <= 2 else latest
    ENV_PATH.write_text(
        ENV_PATH.read_text()
        .replace(
            "wordpress-{}.tar.gz".format(declared),
            "wordpress-{}.tar.gz".format(target),
        )
        .replace("/core/{}/".format(declared), "/core/{}/".format(target))
    )
    return target


def apply_plugin_bump(slug, current, latest):
    PLUGINS_PATH.write_text(
        PLUGINS_PATH.read_text().replace(
            "{}.{}.zip".format(slug, current), "{}.{}.zip".format(slug, latest)
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="rapport.md")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    sections = []
    fixable = []
    manual = []

    declared = read_core_version()
    served, latest, status = check_core(declared)
    etats = {
        "insecure": "**FAILLE CONNUE, MISE A JOUR OBLIGATOIRE**",
        "outdated": "depassee, sans faille connue",
        "latest": "a jour",
    }
    critical = status == "insecure"
    if status != "latest" and declared and latest:
        fixable.append(("WordPress", declared, latest))

    sections += [
        "## WordPress",
        "",
        "| Declaree | Servie | Derniere | Etat wordpress.org |",
        "|---|---|---|---|",
        "| `{}` | `{}` | `{}` | {} |".format(
            declared or "introuvable", served or "?", latest or "?",
            etats.get(status, status),
        ),
        "",
        "Etat fourni par `api.wordpress.org/core/stable-check`, qui marque "
        "chaque version publiee comme `insecure`, `outdated` ou `latest`.",
        "",
    ]

    rows = []
    for slug, current in read_plugins_txt():
        latest_plugin = check_plugin(slug, current)
        if latest_plugin is None:
            state = "introuvable sur wordpress.org"
        elif current and is_older(current, latest_plugin):
            state = "**A METTRE A JOUR**"
            if is_major_jump(current, latest_plugin):
                state += ", version majeure"
            fixable.append((slug, current, latest_plugin))
        else:
            state = "a jour"
        rows.append("| `{}` | `{}` | `{}` | {} |".format(
            slug, current or "?", latest_plugin or "?", state
        ))

    if rows:
        sections += [
            "## Extensions du catalogue",
            "",
            "| Extension | Declaree | Derniere | Etat |",
            "|---|---|---|---|",
            *rows,
            "",
        ]

    vendored_rows = []
    for name, current in read_vendored_plugins():
        slug = VENDORED_SLUGS.get(name)
        changelog = VENDORED_CHANGELOG.get(name)
        if slug:
            latest_vendored = check_plugin(slug, current)
            reference = "version gratuite `{}`".format(slug)
        elif changelog:
            latest_vendored = check_changelog(*changelog)
            reference = "[changelog]({})".format(changelog[0])
        else:
            latest_vendored, reference = None, "-"

        if latest_vendored is None:
            state = "verification manuelle"
        elif current and is_older(current, latest_vendored):
            state = "**A METTRE A JOUR**"
            manual.append((name, current, latest_vendored))
        else:
            state = "a jour"
        vendored_rows.append("| `{}` | `{}` | `{}` | {} | {} |".format(
            name, current or "inconnue", latest_vendored or "?", state, reference
        ))

    if vendored_rows:
        sections += [
            "## Extensions commerciales versionnees dans le depot",
            "",
            "Le code est dans le depot, la mise a jour se fait a la main.",
            "",
            "| Extension | En place | Derniere | Etat | Reference |",
            "|---|---|---|---|---|",
            *vendored_rows,
            "",
        ]

    applied = []
    if args.fix:
        for name, current, target in fixable:
            if name == "WordPress":
                applied.append(("WordPress", current, apply_core_bump(current, target)))
            else:
                apply_plugin_bump(name, current, target)
                applied.append((name, current, target))

    if applied:
        sections = [
            "## Mises a jour appliquees",
            "",
            *["- `{}` : `{}` vers `{}`".format(*c) for c in applied],
            "",
        ] + sections

    if manual:
        sections += [
            "## A faire a la main",
            "",
            "Ces extensions sont versionnees dans le depot, cette PR ne les "
            "touche pas.",
            "",
            *["- `{}` : `{}` vers `{}`".format(*c) for c in manual],
            "",
        ]

    titre = ("# FAILLE CONNUE : mise a jour urgente" if critical
             else "# Mises a jour disponibles")
    report = "\n".join([titre, ""] + sections) + "\n"
    Path(args.output).write_text(report)
    print(report)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as handle:
            handle.write("outdated={}\n".format("true" if fixable or manual else "false"))
            handle.write("fixable={}\n".format("true" if fixable else "false"))
            handle.write("critical={}\n".format("true" if critical else "false"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
