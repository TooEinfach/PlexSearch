#!/usr/bin/env python3
"""
plex_check.py
CLI to search Plex for a movie or show with exact and fuzzy matching.
Requires: plexapi, rapidfuzz, python-dotenv
"""

from dotenv import load_dotenv
import os
import sys
import time
import json
import argparse
import logging
from pathlib import Path
from plexapi.server import PlexServer
from rapidfuzz import fuzz

# ---- Configuration ----
load_dotenv()  # loads .env from current directory

PLEX_BASE = os.environ.get("PLEX_BASE", "http://10.0.0.208:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN")
if not PLEX_TOKEN:
    sys.exit("PLEX_TOKEN not set. Put it in .env or export it in your environment.")

CACHE_FILE = Path.home() / ".plex_cache.json"
CACHE_TTL = 60 * 60 * 6  # 6 hours
LOG_LEVEL = os.environ.get("PLEX_CHECK_LOG", "INFO").upper()

# ---- Logging ----
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("plex_check")

# ---- Connect to Plex ----
try:
    plex = PlexServer(PLEX_BASE, PLEX_TOKEN)
except Exception as e:
    log.error("Failed to connect to Plex at %s: %s", PLEX_BASE, e)
    sys.exit(1)

# ---- Cache helpers ----
def load_cache():
    if not CACHE_FILE.exists():
        return {"updated": 0, "libraries": {}}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to read cache file: %s. Recreating cache.", e)
        return {"updated": 0, "libraries": {}}

def save_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception as e:
        log.warning("Failed to write cache file: %s", e)

def refresh_cache(force=False):
    cache = load_cache()
    now = time.time()
    if not force and (now - cache.get("updated", 0) < CACHE_TTL):
        return cache
    log.info("Refreshing library cache from Plex...")
    libraries = {}
    try:
        sections = plex.library.sections()
    except Exception as e:
        log.error("Failed to list library sections: %s", e)
        return cache
    for section in sections:
        try:
            items = []
            # iterate section.all() can be slow for very large libraries; this is cached
            for item in section.all():
                items.append({
                    "title": getattr(item, "title", None),
                    "year": getattr(item, "year", None),
                    "type": getattr(item, "type", None),
                    "ratingKey": getattr(item, "ratingKey", None)
                })
            libraries[str(section.key)] = {
                "title": section.title,
                "type": section.type,
                "items": items
            }
        except Exception as e:
            log.warning("Failed to read section %s: %s", getattr(section, "title", section.key), e)
            continue
    cache = {"updated": now, "libraries": libraries}
    save_cache(cache)
    return cache

# ---- Search helpers ----
def search_exact(title, section_id=None):
    title_norm = title.strip().lower()
    try:
        if section_id is not None:
            section = plex.library.sectionByID(section_id)
            results = section.search(title)
        else:
            results = plex.search(title, mediatype="movie")
    except Exception:
        # fallback to server-wide search if section lookup fails
        try:
            results = plex.search(title)
        except Exception as e:
            log.error("Search failed: %s", e)
            return []
    matches = []
    for r in results:
        if getattr(r, "title", "").strip().lower() == title_norm:
            matches.append({
                "title": r.title,
                "year": getattr(r, "year", None),
                "type": getattr(r, "type", None),
                "ratingKey": getattr(r, "ratingKey", None),
                "library": getattr(r, "librarySectionTitle", None)
            })
    return matches

def search_fuzzy(title, threshold=80, section_id=None, cache=None):
    title_norm = title.strip().lower()
    if cache is None:
        cache = refresh_cache()
    items = []
    if section_id is not None:
        lib = cache["libraries"].get(str(section_id))
        if lib:
            items = lib["items"]
    else:
        for lib in cache["libraries"].values():
            items.extend(lib["items"])
    found = []
    for it in items:
        if not it.get("title"):
            continue
        score = fuzz.token_sort_ratio(title_norm, it["title"].strip().lower())
        if score >= threshold:
            found.append({
                "title": it["title"],
                "year": it.get("year"),
                "score": score,
                "type": it.get("type"),
                "ratingKey": it.get("ratingKey")
            })
    return sorted(found, key=lambda x: x["score"], reverse=True)

# ---- Output helper (safe printing for mixed object types) ----
def print_search_results_from_server(results, limit=20):
    if not results:
        print("No results from server search.")
        return
    for r in results[:limit]:
        title_val = getattr(r, "title", None) or getattr(r, "name", None) or getattr(r, "tag", None) or "<unknown>"
        rtype = getattr(r, "type", type(r).__name__)
        year = getattr(r, "year", "n/a")
        library = getattr(r, "librarySectionTitle", "n/a")
        ratingKey = getattr(r, "ratingKey", "n/a")
        print(f"- {title_val} ({year}) — {rtype} — {library} — ratingKey {ratingKey}")

# ---- Main search runner used by interactive loop and non-interactive mode ----
def run_search(title, args, cache):
    # Exact first
    exact = search_exact(title, section_id=args.section)
    if exact:
        print(f"\nExact match found ({len(exact)}):")
        for m in exact:
            print(f"- {m['title']} ({m['year']}) — {m['library']} — ratingKey {m['ratingKey']}")
        return

    # Fuzzy if requested
    if args.fuzzy:
        fuzzy_matches = search_fuzzy(title, threshold=args.threshold, section_id=args.section, cache=cache)
        if fuzzy_matches:
            print(f"\nFuzzy matches (threshold {args.threshold}):")
            for m in fuzzy_matches[:20]:
                print(f"- {m['title']} ({m.get('year')}) — score {m['score']} — ratingKey {m['ratingKey']}")
            return
        else:
            print("\nNo fuzzy matches found.")
            return

    # Server search fallback (safe printing)
    print("\nNo exact match found. Showing server search results:")
    try:
        results = plex.search(title)
    except Exception as e:
        print(f"Search failed: {e}")
        return
    print_search_results_from_server(results)

# ---- CLI entrypoint ----
def main():
    parser = argparse.ArgumentParser(description="Check Plex for a movie or show")
    parser.add_argument("--section", type=int, help="Library section ID to limit search", default=None)
    parser.add_argument("--fuzzy", action="store_true", help="Use fuzzy matching")
    parser.add_argument("--threshold", type=int, default=85, help="Fuzzy match threshold 0-100")
    parser.add_argument("--refresh", action="store_true", help="Force refresh cache")
    parser.add_argument("--title", type=str, help="Title to search (non-interactive)", default=None)
    parser.add_argument("--loop", action="store_true", help="Keep prompting until exit/quit (interactive)")
    args = parser.parse_args()

    if args.refresh:
        log.info("Forcing cache refresh...")
        refresh_cache(force=True)

    cache = refresh_cache()

    # Non-interactive mode: run once and exit
    if args.title:
        run_search(args.title.strip(), args, cache)
        return

    # Interactive loop
    print("Type a movie/show name to search. Type 'exit' or 'quit' to stop.")
    try:
        while True:
            q = input("> ").strip()
            if not q:
                continue
            if q.lower() in ("exit", "quit"):
                print("Goodbye.")
                return
            run_search(q, args, cache)
            # Optionally refresh cache periodically if desired (not automatic here)
            if not args.loop:
                # if --loop not provided, run once per invocation (but still allow exit)
                print("\n(Use --loop to keep the program running continuously.)")
    except KeyboardInterrupt:
        print("\nAborted by user.")
        return

if __name__ == "__main__":
    main()