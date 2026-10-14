#!/usr/bin/env bash
# Download the newest good Wayback Machine capture of every HTML page on a site.
#
# Usage: ./fetch.sh example.com [out_dir]
#
# Writes one file per page plus manifest.tsv (file name -> original URL), which
# wayback_to_sql.py uses to fill in slugs. The archive rate limits, so this is
# slow on purpose: a few seconds between pages, longer backoff on failure.
set -euo pipefail

site="${1:?usage: ./fetch.sh example.com [out_dir]}"
out="${2:-wayback/crawl}"
mkdir -p "$out"

cdx="https://web.archive.org/cdx/search/cdx?url=${site}/*&output=json&fl=timestamp,original,urlkey&filter=statuscode:200&filter=mimetype:text/html&limit=20000"
list="$(mktemp)"
curl -sS "$cdx" | python3 -c '
import json, re, sys
rows = json.load(sys.stdin)[1:]
latest = {}
for ts, orig, key in rows:
    # Skip feeds, admin, tag and comment pages; keep posts, pages and listings.
    if re.search(r"wp-|feed|xmlrpc|replytocom|comment-page|/tag/|\?|\.(css|js|xml|txt)$", orig):
        continue
    if key not in latest or ts > latest[key][0]:
        latest[key] = (ts, orig)
for ts, orig in sorted(latest.values()):
    print(ts, orig)
' > "$list"
echo "$(wc -l < "$list" | tr -d ' ') pages to fetch" >&2

: > "$out/manifest.tsv"
while read -r ts url; do
  name=$(echo "$url" | sed -E "s#^https?://(www\.)?${site//./\\.}(:80)?/##; s#/\$##; s#[/:]#_#g")
  [ -z "$name" ] && name=home
  file="${name}-${ts}.html"
  printf '%s\t%s\n' "$file" "$url" >> "$out/manifest.tsv"
  [ -s "$out/$file" ] && continue

  code=000
  for attempt in 1 2 3 4 5; do
    # id_ returns the page as archived, without the toolbar or rewritten links.
    code=$(curl -sSL -o "$out/$file" -w '%{http_code}' "https://web.archive.org/web/${ts}id_/${url}" 2>/dev/null || true)
    # A 404 is not always final: under load the archive returns them for good captures.
    [ "$code" = 200 ] && break
    [ "$code" = 404 ] && [ "$attempt" -ge 3 ] && break
    sleep $((attempt * 20))
  done
  [ "$code" = 200 ] || rm -f "$out/$file"
  echo "$code $file" >&2
  sleep 4
done < "$list"
rm -f "$list"
