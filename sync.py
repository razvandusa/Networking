#!/usr/bin/env python3
"""Rebuild README.md and images/ from the Networking notes in the Obsidian vault.

Usage: python3 sync.py
"""

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

VAULT = Path.home() / "Documents/Obsidian/Razvan"
INDEX = VAULT / "4 - Indexes/Networking.md"
REPO = Path(__file__).resolve().parent
MAX_IMAGE_SIZE = 1600  # px, longest side - keeps the page light on a phone

# Notes are listed in the order of the vault index; this only decides the grouping.
# A note added to the index but not listed here ends up under "More".
GROUPS = {
    "Fundamentals": ["Network Topologies and Types", "OSI Model"],
    "Network devices & services": ["Network Devices, Applications, & Functions", "Proxy", "CDN"],
    "Cloud & virtualization": ["Virtualization", "VPC", "Cloud"],
    "Ports & protocols": ["Ports, Protocols, Services & Traffic Types"],
    "Cabling & transmission": ["Transmission media & Transceivers"],
    "IP addressing": ["IPv4 Addressing", "Subnet Mask", "IPv6 Addressing"],
    "Modern networks": ["Modern Network Environments"],
    "VLANs & switching": ["VLANS & Switch Technologies", "Spanning Tree Protocol"],
    "Routing": ["Routing Technologies"],
    "Wireless": ["Wireless Devices & Technologies"],
    "Physical installations": ["Factors of Physical Installations"],
    "Processes & procedures": ["Purpose Of Organizational Processes & Procedures"],
    "Network monitoring": ["Network Monitoring Technologies"],
    "Disaster recovery": ["Disaster Recovery"],
    "DHCP & DNS": ["DHCP", "DNS, DNS Records & Protocols"],
    "VPN & remote access": ["VPN & Connection Methods"],
    "Security": ["Network Security Concepts", "Types Of Attacks"],
    "Performance": ["Common Performance Issues"],
}

CALLOUTS = {
    "note": "NOTE", "info": "NOTE", "abstract": "NOTE", "summary": "NOTE", "quote": "NOTE",
    "tip": "TIP", "hint": "TIP", "example": "TIP", "success": "TIP",
    "important": "IMPORTANT", "question": "IMPORTANT",
    "warning": "WARNING", "caution": "WARNING", "attention": "WARNING",
    "danger": "CAUTION", "error": "CAUTION", "bug": "CAUTION", "failure": "CAUTION",
}

WIKILINK = re.compile(r"(!?)\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]*))?\]\]")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def anchor(text):
    text = re.sub(r"[*`]", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def file_slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class Anchors:
    """GitHub suffixes repeated heading anchors with -1, -2, ..."""

    def __init__(self):
        self.seen = Counter()

    def add(self, text):
        base = anchor(text)
        n = self.seen[base]
        self.seen[base] += 1
        return base if n == 0 else f"{base}-{n}"


def vault_files():
    files = {}
    for p in VAULT.rglob("*"):
        if p.is_file() and not any(part in (".trash", ".obsidian") for part in p.relative_to(VAULT).parts):
            files.setdefault(p.name, p)
            if p.suffix == ".md":
                files.setdefault(p.stem, p)
    return files


def copy_image(src, dest):
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return
    shutil.copy2(src, dest)
    if src.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        subprocess.run(["sips", "-Z", str(MAX_IMAGE_SIZE), str(dest)], check=True, capture_output=True)


def parse_note(path):
    """Return (title, body lines, reference urls) with the Obsidian header and References stripped."""
    lines = path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# "))
    title = lines[start][2:].strip()
    body, refs = [], []
    in_refs = False
    for line in lines[start + 1:]:
        if re.match(r"#{1,2} References\s*$", line):
            in_refs = True
            continue
        if in_refs:
            refs += re.findall(r"\((https?://[^)]+)\)", line)
        else:
            body.append(line)
    while body and body[-1].strip() in ("", "---"):
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    return title, body, refs


def convert(title, body, notes, files, anchors, used_images, used_html):
    out, subheadings = [], []
    heading = title
    in_code = False
    for line in body:
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if in_code:
            out.append(line)
            continue

        m = re.match(r"(#{1,6}) (.*)", line)
        if m:
            text = m.group(2).strip()
            if text == title and not any(o.strip() for o in out):
                continue  # redundant repeat of the note title
            heading = text
            level = min(len(m.group(1)) + 2, 6)
            a = anchors.add(text)
            if len(m.group(1)) == 2:
                subheadings.append((text, a))
            out.append(f"{'#' * level} {text}")
            continue

        m = re.match(r"(\s*)> \[!(\w+)\][+-]?\s*(.*)", line)
        if m:
            indent, kind, callout_title = m.groups()
            out.append(f"{indent}> [!{CALLOUTS.get(kind.lower(), 'NOTE')}]")
            if callout_title or kind.lower() == "example":
                out += [f"{indent}> **{callout_title or kind.capitalize()}**", f"{indent}>"]
            continue

        def link(m):
            embed, target, section, alias = m.groups()
            target = target.strip()
            label = alias or target
            if target in notes:
                return f"[{label}](#{notes[target]})"
            src = files.get(target)
            if src is None:
                return label
            if src.suffix.lower() in IMAGE_EXTS:
                # Unnamed images ("Pasted image ...", "image 1.jpg") are named after their section
                if src.name.startswith("Pasted image") or re.fullmatch(r"image[\d\s()]*", src.stem):
                    base = file_slug(re.sub(r"[*`]", "", heading))
                else:
                    base = file_slug(src.stem)
                name, n = f"{base}{src.suffix.lower()}", 2
                while name in used_images and used_images[name] != src:
                    name, n = f"{base}_{n}{src.suffix.lower()}", n + 1
                used_images[name] = src
                return f"![{'' if embed else label}](images/{name})"
            if src.suffix == ".html":
                name = f"{file_slug(src.stem)}.html"
                used_html[name] = src
                return f"[{label}](html/{name})"
            return label

        line = WIKILINK.sub(link, line)
        line = re.sub(r"!\[\]\((https?://[^)]+)\)", r"[\1](\1)", line)
        line = re.sub(r"<(/?)u>", r"<\1ins>", line)  # GitHub strips <u>
        out.append(line)
    return out, subheadings


def main():
    index = INDEX.read_text()
    order = [n.strip() for n in re.findall(r"\[\[([^\]|#]+)", index)]
    course = re.search(r"^## (.+)$", index, re.M)
    files = vault_files()
    grouped = {n for names in GROUPS.values() for n in names}
    groups = [(g, [n for n in order if n in names]) for g, names in GROUPS.items()]
    groups.append(("More", [n for n in order if n not in grouped]))
    groups = [(g, names) for g, names in groups if names]

    anchors = Anchors()
    anchors.add("Networking")
    notes = {}
    for g, names in groups:
        anchors.add(g)
        for n in names:
            notes[n] = anchors.add(n)

    sections, toc, refs = [], [], Counter()
    used_images, used_html = {}, {}
    for g, names in groups:
        toc.append(f"\n**{g}**")
        sections.append(f"## {g}\n")
        for i, n in enumerate(names):
            title, body, note_refs = parse_note(files[n])
            refs.update(re.sub(r"[&?]t=\d+s?", "", r) for r in note_refs)
            lines, subs = convert(title, body, notes, files, anchors, used_images, used_html)
            toc.append(f"- [{n}](#{notes[n]})")
            toc += [f"  - [{re.sub(r'[*`]', '', t)}](#{a})" for t, a in subs]
            sections.append(f"### {n}\n")
            sections.append("\n".join(lines))
            sections.append("\n[↑ Back to top](#networking)\n")
            if i < len(names) - 1:
                sections.append("---\n")

    intro = "My networking notes."
    if course and refs:
        intro = f"My notes from the [{course.group(1).strip()}]({refs.most_common(1)[0][0]})."
    elif course:
        intro = f"My notes from the {course.group(1).strip()}."

    readme = "\n".join(["# Networking\n", intro, "\n## Contents", *toc, "", *sections])
    (REPO / "README.md").write_text(readme.rstrip() + "\n")

    for folder, used, copy in (("images", used_images, copy_image), ("html", used_html, shutil.copy2)):
        d = REPO / folder
        if not used:
            shutil.rmtree(d, ignore_errors=True)
            continue
        d.mkdir(exist_ok=True)
        for stale in set(p.name for p in d.iterdir()) - set(used):
            (d / stale).unlink()
        for name, src in used.items():
            copy(src, d / name)

    print(f"{len(notes)} notes, {len(used_images)} images, {len(used_html)} html files")


if __name__ == "__main__":
    main()
