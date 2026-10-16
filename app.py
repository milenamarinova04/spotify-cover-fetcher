import io
import re
from pathlib import Path
import streamlit as st
import requests
import spotipy
from PIL import Image
from spotipy.oauth2 import SpotifyClientCredentials

TARGET = 3000
URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z]{2}/)?|spotify:)(track|album)[/:]([A-Za-z0-9]{22})"
)

st.set_page_config(page_title="Spotify Cover Fetcher 3000x3000", page_icon="🎵", layout="centered")

st.title("🎵 Spotify Cover Fetcher (3000x3000)")
st.write("Въведи своите Spotify API данни и линк към албум или песен, за да изтеглиш обложката в пълна резолюция.")

# Странична лента за ключовете в браузъра
with st.sidebar:
    st.header("🔑 Spotify API Credentials")
    client_id = st.text_input("Client ID", type="default")
    client_secret = st.text_input("Client Secret", type="password")
    st.markdown("[Вземи своите ключове от тук](https://developer.spotify.com/dashboard)")

link_input = st.text_input("🔗 Spotify track / album URL or URI")

def parse_spotify_link(link: str):
    m = URL_RE.search(link.strip())
    if not m:
        raise ValueError("Невалиден Spotify линк или URI.")
    return m.group(1), m.group(2)

def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .") or "untitled"

def itunes_cover(artist: str, album_name: str):
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": f"{artist} {album_name}", "entity": "album", "limit": 10},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception:
        return None

    if not results:
        return None
    
    url = results[0].get("artworkUrl100", "").replace("100x100bb", f"{TARGET}x{TARGET}bb")
    if not url:
        return None
    try:
        img_r = requests.get(url, timeout=30)
        img_r.raise_for_status()
        return Image.open(io.BytesIO(img_r.content)).convert("RGB")
    except Exception:
        return None

def spotify_cover(album: dict):
    images = album.get("images") or []
    if not images:
        raise ValueError("Този албум няма обложка в Spotify.")
    biggest = max(images, key=lambda i: i.get("width") or 0)
    r = requests.get(biggest["url"], timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")

if st.button("Изтегли обложката", type="primary"):
    if not client_id or not client_secret:
        st.error("Моля, въведи Client ID и Client Secret в страничната лента вляво.")
    elif not link_input:
        st.error("Моля, въведи Spotify линк.")
    else:
        try:
            with st.spinner("Свързване със Spotify и обработка..."):
                kind, sid = parse_spotify_link(link_input)
                sp = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=client_id, client_secret=client_secret
                    ),
                    requests_timeout=15
                )
                
                if kind == "track":
                    track = sp.track(sid)
                    album = sp.album(track["album"]["id"])
                else:
                    album = sp.album(sid)

                artist = album["artists"][0]["name"]
                name = album["name"]
                
                st.success(f"Намерено: **{artist} - {name}**")

                # Търсене на обложка
                img = itunes_cover(artist, name)
                source = "iTunes (3000x3000 истинска резолюция)"
                if img is None:
                    img = spotify_cover(album)
                    source = "Spotify (мащабирана до 3000x3000)"

                if img.size != (TARGET, TARGET):
                    if img.size[0] != img.size[1]:
                        side = min(img.size)
                        l, t = (img.size[0] - side) // 2, (img.size[1] - side) // 2
                        img = img.crop((l, t, l + side, t + side))
                    img = img.resize((TARGET, TARGET), Image.LANCZOS)

                # Показване в браузъра
                st.write(f"Източник на обложката: *{source}*")
                st.image(img, caption=f"{artist} - {name}", use_column_width=True)

                # Бутон за сваляне на самите байтове на картинката
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                byte_im = buf.getvalue()

                st.download_button(
                    label="💾 Свали обложката (JPG, 3000x3000)",
                    data=byte_im,
                    file_name=f"{safe_name(artist)} - {safe_name(name)}_cover_3000x3000.jpg",
                    mime="image/jpeg"
                )

        except Exception as e:
            st.error(f"Възникна грешка: {e}")