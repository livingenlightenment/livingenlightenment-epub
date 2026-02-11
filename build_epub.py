#!/usr/bin/env python3
"""
Build script to generate a valid EPUB 3 from the Living Enlightenment source.

Usage:
    python3 build_epub.py

1. Discovers chapter XHTML files (ch*.xhtml) in OEBPS/Text/
2. Reads each file to extract title and level (from epub:type) for the TOC
3. Generates OEBPS/toc.xhtml (navigation) and OEBPS/content.opf (manifest)
4. Packages the full directory structure into a .epub (zip) file

Source: XHTML chapter files in this directory (OEBPS/Text/). Static files
(mimetype, META-INF/, Styles/, Images/, cover.xhtml, title-page.xhtml) are
maintained on disk.
"""

import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone

# --- Configuration -----------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_EPUB = os.path.join(
    SCRIPT_DIR,
    "Living Enlightenment - Unabridged - 7th Edition.epub",
)

OEBPS_DIR = os.path.join(SCRIPT_DIR, "OEBPS")
TEXT_DIR = os.path.join(OEBPS_DIR, "Text")

BOOK_TITLE = "Living Enlightenment, Unabridged, 7th Edition"
BOOK_AUTHOR = "KAILASA\u2019s SPH JGM HDH Bhagavan Sri Nithyananda Paramashivam"
BOOK_LANGUAGE = "en"
BOOK_UUID = "b1a4e7c2-3f8d-4a2e-9c1b-5d6e7f8a9b0c"

# Major sections for TOC: (title, list of part chapter_ids). Only the first
# two parts are under a major section; other parts appear as parts with no
# section heading above them.
MAJOR_SECTIONS = [
    (
        "I. YOU ARE YOUR EMOTIONS",
        [
            "flow-in-love",
            "there-is-nothing-to-worry",
            "excel-without-stress",
            "face-your-fears-and-be-free",
        ],
    ),
]

# --- Chapter discovery from OEBPS/Text ---------------------------------------


def discover_chapters() -> list[dict]:
    """
    Find all ch*.xhtml files in OEBPS/Text/, sort them, and read title + level
    from each file. Returns a list of dicts: filename, id, title, level.
    """
    chapters = []
    filenames = sorted(
        f for f in os.listdir(TEXT_DIR)
        if f.startswith("ch") and f.endswith(".xhtml")
    )
    for filename in filenames:
        # ch000-preface.xhtml -> id = "preface"
        stem = filename[:-6]  # drop .xhtml
        parts = stem.split("-", 1)
        chapter_id = parts[1] if len(parts) > 1 else stem

        filepath = os.path.join(TEXT_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        title_match = re.search(r"<title>(.*?)</title>", content, re.DOTALL)
        title = title_match.group(1).strip() if title_match else chapter_id
        title = re.sub(r"<[^>]+>", "", title)
        title = (
            title.replace("&rsquo;", "\u2019")
            .replace("&lsquo;", "\u2018")
            .replace("&rdquo;", "\u201d")
            .replace("&ldquo;", "\u201c")
            .replace("&amp;", "&")
        )

        # level 2 = part (section), level 3 = chapter
        type_match = re.search(
            r'<section[^>]*\bepub:type="([^"]+)"', content
        )
        epub_type = type_match.group(1) if type_match else "chapter"
        level = 2 if epub_type == "part" else 3

        chapters.append({
            "filename": filename,
            "id": chapter_id,
            "title": title,
            "level": level,
        })
    return chapters


def chapter_item_id(filename: str) -> str:
    """ch000-preface.xhtml -> ch000 (for manifest idref)."""
    return filename.split("-", 1)[0]


# --- content.opf ------------------------------------------------------------


def build_content_opf(chapters: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest_items = [
        '    <item id="cover-image" href="Images/cover.jpg" media-type="image/jpeg" properties="cover-image" />',
        '    <item id="style" href="Styles/style.css" media-type="text/css" />',
        '    <item id="nav" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav" />',
        '    <item id="cover" href="Text/cover.xhtml" media-type="application/xhtml+xml" />',
        '    <item id="title-page" href="Text/title-page.xhtml" media-type="application/xhtml+xml" />',
    ]
    spine_items = [
        '    <itemref idref="cover" />',
        '    <itemref idref="title-page" />',
        '    <itemref idref="nav" />',
    ]

    for ch in chapters:
        item_id = chapter_item_id(ch["filename"])
        fname = ch["filename"]
        manifest_items.append(
            f'    <item id="{item_id}" href="Text/{fname}" media-type="application/xhtml+xml" />'
        )
        spine_items.append(f'    <itemref idref="{item_id}" />')

    return f"""\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">urn:uuid:{BOOK_UUID}</dc:identifier>
    <dc:title>{BOOK_TITLE}</dc:title>
    <dc:creator>{BOOK_AUTHOR}</dc:creator>
    <dc:language>{BOOK_LANGUAGE}</dc:language>
    <meta property="dcterms:modified">{now}</meta>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine>
{chr(10).join(spine_items)}
  </spine>
</package>
"""


# --- toc.xhtml --------------------------------------------------------------
# Structure: Contents (h1) → front matter (Preface, Introduction) → for each
# major section: h2 section title → ol of parts (bullet) → each part: a + ol of
# chapters (no bullet, indented).


def build_toc_xhtml(chapters: list[dict]) -> str:
    # Split into front matter (until first part) and part tree
    front_items = []  # list of {title, href}
    parts_by_id = {}  # part_id -> {title, href, children: [{title, href}, ...]}
    current_part_id = None

    for ch in chapters:
        href = f"Text/{ch['filename']}"
        entry = {"title": ch["title"], "href": href}

        if ch["level"] == 2:
            current_part_id = ch["id"]
            parts_by_id[ch["id"]] = {"title": ch["title"], "href": href, "children": []}
        else:
            if current_part_id is not None:
                parts_by_id[current_part_id]["children"].append(entry)
            else:
                front_items.append(entry)

    # Build HTML: front list, then for each major section: h2 + ol(part li with ol(children))
    part_ids_used = set()
    lines = []

    # Front matter (Preface, Introduction) in its own list
    lines.append('    <ol class="toc-front-matter">')
    for e in front_items:
        lines.append(f'      <li class="toc-front"><a href="{e["href"]}">{e["title"]}</a></li>')
    lines.append('    </ol>')

    # Major sections
    for section_title, part_ids in MAJOR_SECTIONS:
        lines.append(f'    <h2 class="toc-section">{section_title}</h2>')
        lines.append('    <ol class="toc-parts">')
        for pid in part_ids:
            if pid not in parts_by_id:
                continue
            part_ids_used.add(pid)
            part = parts_by_id[pid]
            lines.append(f'      <li class="toc-part">')
            lines.append(f'        <a href="{part["href"]}">{part["title"]}</a>')
            if part["children"]:
                lines.append('        <ol class="toc-chapters">')
                for c in part["children"]:
                    lines.append(f'          <li><a href="{c["href"]}">{c["title"]}</a></li>')
                lines.append('        </ol>')
            lines.append('      </li>')
        lines.append('    </ol>')

    # Any part not in MAJOR_SECTIONS (e.g. if config is incomplete)
    orphan_parts = [(pid, parts_by_id[pid]) for pid in parts_by_id if pid not in part_ids_used]
    if orphan_parts:
        lines.append('    <ol class="toc-parts">')
        for _pid, part in orphan_parts:
            lines.append('      <li class="toc-part">')
            lines.append(f'        <a href="{part["href"]}">{part["title"]}</a>')
            if part["children"]:
                lines.append('        <ol class="toc-chapters">')
                for c in part["children"]:
                    lines.append(f'          <li><a href="{c["href"]}">{c["title"]}</a></li>')
                lines.append('        </ol>')
            lines.append('      </li>')
        lines.append('    </ol>')

    toc_body = "\n".join(lines)

    return f"""\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head>
  <meta charset="utf-8" />
  <title>Table of Contents</title>
  <link href="Styles/style.css" rel="stylesheet" type="text/css" />
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1 class="toc-title">Contents</h1>
{toc_body}
  </nav>
</body>
</html>
"""


# --- Build -------------------------------------------------------------------


def build_epub():
    print(f"Source: {TEXT_DIR}")
    print("Discovering chapters...")
    chapters = discover_chapters()
    print(f"  Found {len(chapters)} chapters")
    for i, ch in enumerate(chapters):
        print(f"  {i:3d}. [{ch['level']}] {ch['filename']}")

    # --- Step 1: Write toc.xhtml ---
    toc_path = os.path.join(OEBPS_DIR, "toc.xhtml")
    with open(toc_path, "w", encoding="utf-8") as f:
        f.write(build_toc_xhtml(chapters))
    print(f"  Wrote toc.xhtml")

    # --- Step 2: Write content.opf ---
    opf_path = os.path.join(OEBPS_DIR, "content.opf")
    with open(opf_path, "w", encoding="utf-8") as f:
        f.write(build_content_opf(chapters))
    print(f"  Wrote content.opf")

    # --- Step 3: Format generated files with Prettier ---
    print("\nFormatting with Prettier...")
    generated_files = [toc_path] + [
        os.path.join(TEXT_DIR, ch["filename"]) for ch in chapters
    ]
    try:
        subprocess.run(
            ["npx", "prettier", "--write", "--parser", "html",
             "--prose-wrap", "always", "--print-width", "80", "--tab-width", "2"]
            + generated_files,
            capture_output=True, text=True, check=True,
        )
        print(f"  Formatted {len(generated_files)} files")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  Prettier not available, skipping formatting")

    # --- Step 4: Package into .epub ---
    print(f"\nPackaging: {OUTPUT_EPUB}")
    if os.path.exists(OUTPUT_EPUB):
        os.remove(OUTPUT_EPUB)

    with zipfile.ZipFile(OUTPUT_EPUB, "w", zipfile.ZIP_DEFLATED) as epub:
        # mimetype MUST be first and stored uncompressed
        mimetype_path = os.path.join(SCRIPT_DIR, "mimetype")
        epub.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)

        # Walk the directory tree and add all EPUB files
        for dirpath, dirnames, filenames in os.walk(SCRIPT_DIR):
            # Skip hidden dirs, the script itself, and the output epub
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "__pycache__"
            ]

            for filename in sorted(filenames):
                full_path = os.path.join(dirpath, filename)
                arcname = os.path.relpath(full_path, SCRIPT_DIR)

                # Skip: mimetype (already added), build script, epub output, non-epub files
                if arcname == "mimetype":
                    continue
                if filename.endswith((".py", ".epub", ".DS_Store")):
                    continue

                epub.write(full_path, arcname, compress_type=zipfile.ZIP_DEFLATED)

    file_size = os.path.getsize(OUTPUT_EPUB)
    print(f"\nDone! {OUTPUT_EPUB}")
    print(f"  Size: {file_size / 1024:.1f} KB")
    print(f"  Chapters: {len(chapters)}")


if __name__ == "__main__":
    build_epub()
