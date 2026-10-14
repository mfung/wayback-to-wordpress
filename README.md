# wayback-to-wordpress

Rebuild a WordPress blog from its Wayback Machine captures. It downloads the
archived pages, pulls the post content out of the theme HTML, and writes SQL
inserts for a fresh WordPress install.

I wrote it to get [mengfung.com](https://mengfung.com) back: 101 posts from
2007 to 2021, across two themes and a host move that renumbered every post.
The story is in [Rebuilding my blog from the Wayback Machine](https://mengfung.com/2026/10/rebuilding-my-blog-from-the-wayback-machine/).

It is a script for one site that tries to be easy to point at another, not a
general tool. Expect to read the code and adjust it for your theme.

## Use

Python 3 standard library and curl. Nothing to install.

```sh
# 1. Download the newest good capture of every page (slow; the archive rate limits)
./fetch.sh example.com wayback/crawl

# 2. Set SITE and the other settings at the top of wayback_to_sql.py, then
python3 wayback_to_sql.py wayback/crawl/*.html > import.sql
```

Back up your database, then import `import.sql` with phpMyAdmin or
`mysql < import.sql`. It runs in one transaction.

You can also pass pages you saved by hand. Any mix of captures works: the
script merges copies of the same post and keeps the most complete one.

## What it handles

- **Two layouts.** `<article id="post-N">` themes (Writr and most themes
  since about 2013) and the older `<div class="post" id="post-N">`. Another
  theme means adding its selectors to `parse_post()`.
- **Post IDs that changed in a migration.** Captures are matched on title and
  date, and on similar text when a post was retitled, not on ID. Posts from the
  newest layout keep their IDs; the rest get new ones above them.
- **Excerpts.** Home and archive pages cut posts at "Continue reading". The
  full capture wins, and posts using `<!--noteaser-->` get their teaser
  stitched back from a listing page.
- **Wayback rewriting.** Archive prefixes are stripped from links, but your
  own deliberate links to the Wayback Machine are kept.
- **Cleanup.** Crayon and WP-Syntax highlighter markup becomes plain
  `<pre><code>`; share buttons, reading-time labels and keyword-link plugins
  are removed; wptexturize entities go back to plain characters.
- **Categories and tags**, including nested categories, with the archive
  links as the source of names.

## Settings

At the top of `wayback_to_sql.py`:

| Setting | What it is |
| --- | --- |
| `SITE` | Domain the captures are of, without `www` |
| `PREFIX` | WordPress table prefix |
| `AUTHOR_ID` | User ID to attribute posts to |
| `SKIP_AFTER` | Ignore captures after this year, e.g. a later reinstall |
| `KNOWN_CATEGORIES` | Category slug to term ID, from your category widget's `cat-item-N` classes. Leave empty to number them from `NEW_TERM_START` |

Check the IDs it writes against your database first: if a fresh install already
uses some of them, the import fails or links posts to the wrong terms.

## Not handled

Comments, images (they are referenced at their original URLs; download them
separately), and themes other than the two above without a code change.

## License

MIT
