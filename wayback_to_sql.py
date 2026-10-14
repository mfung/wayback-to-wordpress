#!/usr/bin/env python3
"""Turn Wayback Machine captures of a WordPress site into SQL inserts.

Written to rebuild mengfung.com. Set SITE and the other settings below for
your own site.

Usage: python3 wayback_to_sql.py wayback/*.html wayback/crawl/*.html > import.sql

Reads two layouts: the Writr theme (<article id="post-N">, 2014-2022) and the
original theme (<div class="post" id="post-N">, 2007-2012). Only the post
content is kept; theme markup, share buttons and syntax highlighter markup are
dropped so the posts work with any new theme.

The site was moved around 2012 and post IDs changed, so captures are matched
on title and month rather than ID. Posts from the Writr era keep their IDs;
posts only seen on the original site get a new ID when inserted.
"""
import html as htmllib
import os
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher

SITE = "mengfung.com"  # the domain the captures are of, without www
PREFIX = "wp_"
AUTHOR_ID = 1
SKIP_AFTER = "2023"  # captures from 2024 on are a fresh reinstall ("Hello world!")

# Writr-era category term IDs from the sidebar widget (cat-item-N).
KNOWN_CATEGORIES = {
    "uncategorized": 1, "homemade": 3, "programming": 4, "devops": 7,
    "rants": 9, "diy": 19, "data-science": 20,
}
NEW_TERM_START = 100

ENTITIES = {
    "&#8216;": "'", "&#8217;": "'", "&#8220;": '"', "&#8221;": '"', "&#8242;": "'", "&#8243;": '"',
    "&#8211;": "-", "&#8212;": "--", "&#8230;": "...", "&#038;": "&", "&#91;": "[", "&#93;": "]",
    "&#215;": "x", "&#123;": "{", "&#125;": "}", "&#40;": "(", "&#41;": ")",
}

WAYBACK_RE = re.compile(r'(?<![/\w])(?:https?:)?//web\.archive\.org/web/\d+(?:[a-z]{2}_)?/')
DATE_RE = re.compile(
    r'(?:[A-Z][a-z]+day, )?([A-Z][a-z]+ \d{1,2}, \d{4})(?:,? (?:at )?(\d{1,2}:\d{2} ?[ap]m))?', re.I)


def element(page, start):
    """Return (inner_html, end) of the element whose opening tag starts at `start`."""
    tag = re.match(r"<(\w+)", page[start:]).group(1)
    open_end = page.index(">", start) + 1
    depth, pos = 1, open_end
    pattern = re.compile(rf"<(/?){tag}\b[^>]*>", re.I)
    while depth:
        m = pattern.search(page, pos)
        if not m:
            return page[open_end:], len(page)
        depth += -1 if m.group(1) else 1
        pos = m.end()
    return page[open_end:m.start()], pos


def find_element(page, opening_re, start=0):
    m = re.compile(opening_re, re.I | re.S).search(page, start)
    if not m:
        return None, None
    return element(page, m.start())[0], m


def replace_elements(html, opening_re, fn):
    out, pos = [], 0
    rx = re.compile(opening_re, re.I | re.S)
    while True:
        m = rx.search(html, pos)
        if not m:
            out.append(html[pos:])
            return "".join(out)
        inner, end = element(html, m.start())
        out.append(html[pos:m.start()])
        out.append(fn(inner))
        pos = end


def text_of(fragment):
    return re.sub(r"<[^>]+>", "", fragment)


def code_block(code):
    code = code.replace("&nbsp;", " ").replace("\r", "").strip("\n")
    return f'<pre class="wp-block-code"><code>{code}</code></pre>'


def crayon(inner):
    m = re.search(r'<textarea[^>]*class="crayon-plain[^"]*"[^>]*>(.*?)</textarea>', inner, re.S)
    if m:
        return code_block(m.group(1))
    lines = re.findall(r'<div class="crayon-line[^"]*"[^>]*>(.*?)</div>', inner, re.S)
    return code_block("\n".join(text_of(l) for l in lines))


def wp_syntax(inner):
    code, _ = find_element(inner, r'<td class="code"')
    pres = re.findall(r"<pre[^>]*>(.*?)</pre>", code or inner, re.S)
    return code_block(text_of(pres[-1])) if pres else inner


def clean_content(html, rewritten):
    html = re.sub(r'<span class="rt-reading-time".*?</span></span>\s*', "", html, flags=re.S)
    truncated = "more-link" in html
    html = re.sub(r'\s*<span class="more-link-wrapper">.*?</span>\s*', "\n\n<!--more-->", html, flags=re.S)
    html = re.sub(r'\s*<a href="[^"]*#more-\d+" class="more-link">.*?</a>', "\n\n<!--more-->", html, flags=re.S)
    html = re.sub(r'<span id="more-\d+"></span>', "<!--more-->", html)
    html = replace_elements(html, r'<div[^>]*class="crayon-syntax', crayon)
    html = replace_elements(html, r'<div class="wp_syntax"', wp_syntax)
    html = replace_elements(html, r'<div class="(?:sociable|postmetadata)', lambda _: "")
    html = re.sub(r"<span class=[\"']bm_keywordlink[\"']>(.*?)</span>", lambda m: text_of(m.group(1)), html, flags=re.S)
    html = re.sub(r'<p>(?:\s|&nbsp;)*</p>\s*', "", html)
    html = re.sub(r"<!--(?!more|noteaser).*?-->", "", html, flags=re.S)
    if rewritten:
        html = WAYBACK_RE.sub("", html)
    html = re.sub(rf"(?:https?:)?//(?:www\.)?{re.escape(SITE)}/wp-content/uploads/", f"https://{SITE}/wp-content/uploads/", html)
    return detexturize(html).strip(), truncated


def detexturize(text):
    for entity, char in ENTITIES.items():
        text = text.replace(entity, char)
    return text


def clean_text(fragment):
    return htmllib.unescape(detexturize(text_of(fragment))).strip()


def terms_from_links(meta, rel, rewritten):
    found = []
    for href, name in re.findall(rf'<a href="([^"]*)"[^>]*rel="{rel}"[^>]*>(.*?)</a>', meta, re.S):
        if rewritten:
            href = WAYBACK_RE.sub("", href)
        path = [p for p in re.sub(r"^https?://[^/]+", "", href).split("/") if p and p not in ("category", "tag")]
        if path:
            found.append({"slug": path[-1], "name": clean_text(name), "parent": path[-2] if len(path) > 1 else None})
    return found


def slug_from_url(url):
    return url.rstrip("/").rsplit("/", 1)[-1] if url else ""


def parse(path, source_url):
    with open(path, encoding="utf-8", errors="replace") as f:
        page = f.read()
    # Rewritten captures prefix even the site's own links; raw (id_) captures don't.
    rewritten = bool(re.search(rf"web\.archive\.org/web/\d+(?:[a-z]{{2}}_)?/https?://(?:www\.)?{re.escape(SITE)}", page))
    pos = 0
    opening = re.compile(r'<(article|div)\b[^>]*\bid="post-(\d+)"[^>]*>', re.I)
    while True:
        m = opening.search(page, pos)
        if not m:
            break
        body, pos = element(page, m.start())
        post = parse_post(m.group(0), int(m.group(2)), body, rewritten, source_url)
        if post:
            post["source"] = path
            if post["date"] is None:
                # Pages show no date; use the capture date so they sort somewhere sensible.
                ts = re.search(r"-(\d{8})\d*\.html$", path)
                post["date"] = datetime.strptime(ts.group(1), "%Y%m%d") if ts else datetime(2000, 1, 1)
            yield post


def parse_post(opening, post_id, body, rewritten, source_url):
    classes = (re.search(r'class="([^"]*)"', opening) or [None, ""])[1]
    writr = opening.lower().startswith("<article")
    if "type-attachment" in classes:
        return None

    if writr:
        content, _ = find_element(body, r'<div class="entry-content')
        title_m = re.search(r'<h1 class="entry-title">(.*?)</h1>', body, re.S)
        meta = body[body.find("entry-meta"):] if "entry-meta" in body else body
        cats = [{"slug": s, "name": None, "parent": None} for s in re.findall(r"\bcategory-([\w-]+)", classes)]
        tags = terms_from_links(meta, "tag", rewritten) or [
            {"slug": s, "name": None, "parent": None} for s in re.findall(r"\btag-([\w-]+)", classes)]
        post_type = "page" if "type-page" in classes else "post"
    else:
        content, _ = find_element(body, r'<div class="entry"')
        title_m = re.search(r"<h[123][^>]*>(.*?)</h[123]>", body, re.S)
        meta, _ = find_element(body, r'<div class="postmetadata"')
        meta = meta or ""
        cats = terms_from_links(meta, "category tag", rewritten)
        tags = terms_from_links(body, "tag", rewritten)
        post_type = "post" if cats or DATE_RE.search(text_of(meta)) else "page"
    if content is None or not title_m:
        return None

    link = re.search(r'<a href="([^"]*)"', title_m.group(1))
    url = link.group(1) if link else ""
    if not url and writr:
        dm = re.search(r'<a href="([^"]*)" rel="bookmark" title="\d', body)
        url = dm.group(1) if dm else ""
    url = WAYBACK_RE.sub("", url) if url else source_url or ""

    date = None
    dm = re.search(r'rel="bookmark" title="(\d{1,2}:\d{2} ?[ap]m)">([A-Z][a-z]+ \d{1,2}, \d{4})</a>', meta, re.I) if writr else None
    if dm:
        date = datetime.strptime(f"{dm.group(2)} {dm.group(1).upper().replace(' ', '')}", "%B %d, %Y %I:%M%p")
    else:
        dm = DATE_RE.search(text_of(meta)) if not writr else None
        if dm:
            t = (dm.group(2) or "12:00pm").upper().replace(" ", "")
            date = datetime.strptime(f"{dm.group(1)} {t}", "%B %d, %Y %I:%M%p")
    if date is None and post_type == "post":
        return None

    content, truncated = clean_content(content, rewritten)
    title = clean_text(title_m.group(1))
    # Nothing worth importing: password prompts, contact forms, the default privacy page.
    if "wp-pass.php" in content or 'class="wpcf7' in content or title == "Privacy Policy":
        return None
    return {
        "id": post_id, "writr": writr, "type": post_type,
        "title": title, "slug": slug_from_url(url), "url": url,
        "date": date, "content": content, "truncated": truncated,
        "categories": cats, "tags": tags,
    }


def q(value):
    """Quote a string literal for MySQL (default sql_mode, backslash escapes on)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\0", "\\0") + "'"


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def same_post(a, b):
    """Captures of one post: same type, and same title or (same day and similar text)."""
    if a["type"] != b["type"]:
        return False
    if norm(a["title"]) == norm(b["title"]):
        return a["type"] == "page" or abs((a["date"] - b["date"]).days) <= 31
    if a["type"] == "page" or a["date"].date() != b["date"].date():
        return False
    ta, tb = norm(text_of(a["content"]))[:400], norm(text_of(b["content"]))[:400]
    titles = SequenceMatcher(None, norm(a["title"]), norm(b["title"])).ratio()
    return titles > 0.85 or (ta and tb and SequenceMatcher(None, ta, tb).ratio() > 0.9)


def load_manifest(paths):
    urls = {}
    for d in {os.path.dirname(p) for p in paths}:
        mf = os.path.join(d, "manifest.tsv")
        if os.path.exists(mf):
            for line in open(mf):
                name, url = line.rstrip("\n").split("\t")
                urls[os.path.join(d, name)] = url
    return urls


def capture_year(path):
    m = re.search(r"-(\d{4})\d*\.html$", path)
    return m.group(1) if m else "0000"


def main(paths):
    urls = load_manifest(paths)
    groups = []
    for path in paths:
        if capture_year(path) > SKIP_AFTER:
            continue
        for post in parse(path, urls.get(path)):
            group = next((g for g in groups if any(same_post(post, p) for p in g)), None)
            if group is None:
                groups.append([post])
            else:
                group.append(post)

    posts = []
    for found in groups:
        best = max(found, key=lambda p: (not p["truncated"], p["writr"], len(p["content"])))
        post = dict(best)
        # With <!--noteaser-->, the single post page omits everything above the
        # more tag, so borrow that teaser from a listing page capture.
        if post["content"].startswith("<!--more-->"):
            teasers = [p["content"].split("<!--more-->")[0].strip() for p in found if p["truncated"]]
            teasers = [t for t in teasers if t]
            if teasers:
                post["content"] = max(teasers, key=len) + "\n" + post["content"]
            else:
                print(f"missing teaser: {post['title']}", file=sys.stderr)
        # Writr-era posts keep their ID; original-site IDs were reassigned in the move.
        writr_ids = {p["id"] for p in found if p["writr"]}
        post["keep_id"] = min(writr_ids) if writr_ids else None
        if post["type"] == "page":
            post["date"] = min(p["date"] for p in found)
        post["slug"] = post["slug"] or next((p["slug"] for p in found if p["slug"]), "")
        # Prefer the newest era's categories (they were reorganised), fall back to old ones.
        writr_cats = [p["categories"] for p in found if p["writr"] and p["categories"]]
        old_cats = [p["categories"] for p in found if not p["writr"] and p["categories"]]
        post["categories"] = writr_cats[0] if writr_cats else (old_cats[0] if old_cats else [])
        tags = {}
        for p in found:
            for t in p["tags"]:
                if t["slug"] not in tags or t["name"]:
                    tags[t["slug"]] = t
        post["tags"] = list(tags.values())
        posts.append(post)

    posts.sort(key=lambda p: (p["date"], p["title"]))
    used_ids = {p["keep_id"] for p in posts if p["keep_id"]}
    dupes = [i for i in used_ids if sum(p["keep_id"] == i for p in posts) > 1]
    for i in dupes:
        print(f"duplicate post ID {i}; later copies get a new ID", file=sys.stderr)
        for p in [p for p in posts if p["keep_id"] == i][1:]:
            p["keep_id"] = None

    # Terms: known Writr-era categories keep their IDs, everything else counts up from NEW_TERM_START.
    term_ids, next_id, term_rows = {}, NEW_TERM_START, []
    def term_id(taxonomy, term):
        nonlocal next_id
        key = (taxonomy, term["slug"])
        if key in term_ids:
            return term_ids[key]
        parent = 0
        if taxonomy == "category" and term.get("parent"):
            parent = term_id("category", {"slug": term["parent"], "name": None, "parent": None})
        if taxonomy == "category" and term["slug"] in KNOWN_CATEGORIES:
            tid = KNOWN_CATEGORIES[term["slug"]]
        else:
            tid, next_id = next_id, next_id + 1
        name = term.get("name") or term["slug"].replace("-", " ").title().replace("Devops", "DevOps")
        term_ids[key] = tid
        term_rows.append((tid, name, term["slug"], taxonomy, parent))
        return tid

    for p in posts:
        p["term_ids"] = [term_id("category", c) for c in p["categories"]] + [term_id("post_tag", t) for t in p["tags"]]
    # Names from old-site links beat names guessed from slugs.
    names = {}
    for p in posts:
        for tax, terms in (("category", p["categories"]), ("post_tag", p["tags"])):
            for t in terms:
                if t["name"]:
                    names[(tax, t["slug"])] = t["name"]
    names.setdefault(("category", "diy"), "DIY")
    names.setdefault(("category", "data-science"), "Data Science")

    out = [f"-- Generated from Wayback Machine captures of {SITE}",
           "SET NAMES utf8mb4;", "START TRANSACTION;", "", "-- Categories and tags (term_taxonomy_id = term_id)"]
    for tid, name, slug, tax, parent in sorted(term_rows):
        name = names.get((tax, slug), name)
        out.append(f"INSERT IGNORE INTO {PREFIX}terms (term_id, name, slug, term_group) VALUES ({tid}, {q(name)}, {q(slug)}, 0);")
        out.append(f"INSERT IGNORE INTO {PREFIX}term_taxonomy (term_taxonomy_id, term_id, taxonomy, description, parent, count) "
                   f"VALUES ({tid}, {tid}, '{tax}', '', {parent}, 0);")
    out.append("")

    # Original-site posts get IDs above every kept ID, so nothing collides.
    next_post_id = max(used_ids, default=0) + 1
    for p in sorted(posts, key=lambda p: p["keep_id"] is None):
        pid = p["keep_id"]
        if not pid:
            pid, next_post_id = next_post_id, next_post_id + 1
        d = p["date"].strftime("%Y-%m-%d %H:%M:%S")
        notes = []
        if p["truncated"]:
            notes.append("EXCERPT ONLY")
        if not p["keep_id"]:
            notes.append("original site only, new ID")
        out.append(f"-- {pid}: {p['date']:%Y-%m-%d} {p['title']}" + (f"  ({'; '.join(notes)})" if notes else ""))
        out.append(
            f"INSERT INTO {PREFIX}posts (ID, post_author, post_date, post_date_gmt, post_content, post_title, "
            "post_excerpt, post_status, comment_status, ping_status, post_password, post_name, to_ping, pinged, "
            "post_modified, post_modified_gmt, post_content_filtered, post_parent, guid, menu_order, post_type, "
            "post_mime_type, comment_count) VALUES (\n"
            f"  {pid}, {AUTHOR_ID}, '{d}', '{d}',\n  {q(p['content'])},\n  {q(p['title'])}, '', 'publish', 'open', 'open', '', "
            f"{q(p['slug'])}, '', '',\n  '{d}', '{d}', '', 0, 'https://{SITE}/?p={pid}', 0, {q(p['type'])}, '', 0);"
        )
        for tid in dict.fromkeys(p["term_ids"]):
            out.append(f"INSERT INTO {PREFIX}term_relationships (object_id, term_taxonomy_id, term_order) VALUES ({pid}, {tid}, 0);")
        out.append("")

    out.append("-- Recount term usage")
    out.append(f"UPDATE {PREFIX}term_taxonomy tt SET count = (SELECT COUNT(*) FROM {PREFIX}term_relationships tr "
               f"JOIN {PREFIX}posts p ON p.ID = tr.object_id AND p.post_status = 'publish' "
               f"WHERE tr.term_taxonomy_id = tt.term_taxonomy_id);")
    out.append("")
    out.append("COMMIT;")
    print("\n".join(out))

    for p in posts:
        if p["truncated"]:
            print(f"excerpt only: {p['date']:%Y-%m-%d} {p['title']}", file=sys.stderr)
    print(f"{sum(p['type'] == 'post' for p in posts)} posts, {sum(p['type'] == 'page' for p in posts)} pages written",
          file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
