#!/usr/bin/env python3
"""
Spotify cover fetcher: takes a Spotify track/album URL or URI and saves the
album artwork at 3000x3000 plus a tracklist file, in a structured folder
(optionally zipped).

Artwork sources, in order:
  1. iTunes Search API (true 3000x3000 for most commercial releases)
  2. Spotify's own image (max 640x640), Lanczos-upscaled to 3000x3000 and flagged

Setup:
  pip install spotipy requests pillow
  export SPOTIPY_CLIENT_ID=...       # from https://developer.spotify.com/dashboard
  export SPOTIPY_CLIENT_SECRET=...

Usage:
  python spotify_cover_fetcher.py "https://open.spotify.com/album/..." [-o out] [--zip]
"""
import argparse
import difflib
import io
import re
import shutil
import sys
from pathlib import Path

import requests
import spotipy
from PIL import Image
from spotipy.oauth2 import SpotifyClientCredentials

TARGET = 3000
URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z]{2}/)?|spotify:)(track|album)[/:]([A-Za-z0-9]{22})"
)


class FetchError(Exception):
    pass


def parse_spotify_link(link: str):
    m = URL_RE.search(link.strip())
    if not m:
        raise FetchError(
            "Not a valid Spotify track/album link or URI. "
            "Expected e.g. https://open.spotify.com/album/<id> or spotify:track:<id>."
        )
    return m.group(1), m.group(2)


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .") or "untitled"


def get_album(sp, kind: str, spotify_id: str):
    try:
        if kind == "track":
            track = sp.track(spotify_id)
            album = sp.album(track["album"]["id"])
        else:
            album = sp.album(spotify_id)
    except spotipy.SpotifyException as e:
        raise FetchError(f"Spotify could not find that {kind} ({e.http_status}).") from e
    except requests.RequestException as e:
        raise FetchError(f"Network error talking to Spotify: {e}") from e
    return album


def itunes_cover(artist: str, album_name: str):
    """Try to find a 3000x3000 cover via the iTunes Search API."""
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": f"{artist} {album_name}", "entity": "album", "limit": 10},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except (requests.RequestException, ValueError):
        return None

    def score(item):
        a = difflib.SequenceMatcher(
            None, album_name.lower(), item.get("collectionName", "").lower()
        ).ratio()
        b = difflib.SequenceMatcher(
            None, artist.lower(), item.get("artistName", "").lower()
        ).ratio()
        return (a + b) / 2

    if not results:
        return None
    best = max(results, key=score)
    if score(best) < 0.75:  # avoid grabbing the wrong release
        return None
    url = best.get("artworkUrl100", "").replace("100x100bb", f"{TARGET}x{TARGET}bb")
    if not url:
        return None
    try:
        img_r = requests.get(url, timeout=30)
        img_r.raise_for_status()
        img = Image.open(io.BytesIO(img_r.content)).convert("RGB")
        return img
    except (requests.RequestException, OSError):
        return None


def spotify_cover(album: dict):
    images = album.get("images") or []
    if not images:
        raise FetchError("This release has no artwork on Spotify.")
    biggest = max(images, key=lambda i: i.get("width") or 0)
    try:
        r = requests.get(biggest["url"], timeout=30)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except (requests.RequestException, OSError) as e:
        raise FetchError(f"Could not download Spotify artwork: {e}") from e


def run(link: str, outdir: Path, make_zip: bool) -> Path:
    kind, sid = parse_spotify_link(link)
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(), requests_timeout=15, retries=3
    )
    album = get_album(sp, kind, sid)

    artist = album["artists"][0]["name"]
    name = album["name"]
    folder = outdir / safe_name(f"{artist} - {name}")
    folder.mkdir(parents=True, exist_ok=True)
    print(f"Release: {artist} - {name}")

    img = itunes_cover(artist, name)
    source = "iTunes (native resolution)"
    upscaled = False
    if img is None:
        img = spotify_cover(album)
        source = "Spotify (max 640px)"
    if img.size != (TARGET, TARGET):
        if img.size[0] != img.size[1]:
            side = min(img.size)  # center-crop to square
            l, t = (img.size[0] - side) // 2, (img.size[1] - side) // 2
            img = img.crop((l, t, l + side, t + side))
        if img.size[0] < TARGET:
            upscaled = True
        img = img.resize((TARGET, TARGET), Image.LANCZOS)

    cover_path = folder / "cover_3000x3000.jpg"
    img.save(cover_path, "JPEG", quality=95, subsampling=0)
    print(f"Cover saved: {cover_path}  [source: {source}]")
    if upscaled:
        print("  Note: no high-res match found; this is an upscale of a small image.")

    # Tracklist
    lines = []
    tracks = album["tracks"]["items"]
    for t in tracks:
        lines.append(f"{t['track_number']:02d}. {t['name']} ({t['external_urls']['spotify']})")
    (folder / "tracklist.txt").write_text(
        f"{artist} - {name}\n\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )

    if make_zip:
        z = shutil.make_archive(str(folder), "zip", folder)
        print(f"ZIP created: {z}")
        return Path(z)
    return folder


def main():
    ap = argparse.ArgumentParser(description="Fetch 3000x3000 cover art from a Spotify link.")
    ap.add_argument("link", help="Spotify track/album URL or URI")
    ap.add_argument("-o", "--out", default="downloads", help="Output directory")
    ap.add_argument("--zip", action="store_true", help="Also create a ZIP archive")
    args = ap.parse_args()
    try:
        run(args.link, Path(args.out), args.zip)
    except FetchError as e:
        sys.exit(f"Error: {e}")
    except spotipy.SpotifyOauthError:
        sys.exit("Error: set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET (see header of this file).")


if __name__ == "__main__":
    main()
