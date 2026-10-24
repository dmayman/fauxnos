#!/usr/bin/env python3
"""
Library

The server-wide music library behind the Library source. Audio files live
in one folder (default ~/fauxnos-library; subfolders fine), served to each
room's MPD at /library/<path>. This module adds what the UI needs on top:

- An index of tracks with tags (title, artist, album, duration) and cover
  art, read with mutagen. It's cached in <root>/.fauxnos/index.json, keyed
  by path + size + mtime, so a rescan only reads new or changed files.
  Without mutagen, titles fall back to file names.
- Playlists, in <root>/.fauxnos/playlists.json, as ordered track ids.
- Uploads (MP3 and M4A), deletes, and edits to title/artist/album, which
  are written into the file's own tags.
- YouTube import: yt-dlp pulls the audio as M4A (no transcoding on the Pi)
  in a background job, then tags it and keeps the thumbnail as cover art.
- Spotify links: the song's public details (title, artist, duration, cover)
  come from Spotify's embed page; the audio is the closest-length match from
  a YouTube search, imported the same way and tagged with Spotify's details.
  Spotify's own audio is DRM-protected and never touched.

A track's id is a hash of its path, so it's stable across rescans and
restarts, and changes only if the file is renamed or moved.

`on_change` (if given) is called whenever the songs or playlists change, so
the server can republish the index on MQTT for Home Assistant.
"""

import hashlib
import importlib.util
import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Optional

try:
    import mutagen
    from mutagen.mp4 import MP4
    from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB
except ImportError:  # optional: titles fall back to file names
    mutagen = None

PLAYABLE_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
UPLOAD_EXTENSIONS = {".mp3", ".m4a"}
ART_EXTENSIONS = (".jpg", ".png", ".webp")

logger = logging.getLogger(__name__)


def track_id(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:12]


def safe_filename(name: str) -> str:
    """A file name with no path parts or awkward characters."""
    name = Path(name).name
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .")
    return name or "track"


def _find_key(obj, key):
    """The first dict anywhere in nested JSON that has `key`, or None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for child in children:
        found = _find_key(child, key)
        if found is not None:
            return found
    return None


def _first(tags, *keys) -> Optional[str]:
    for key in keys:
        value = tags.get(key)
        if value:
            value = value[0] if isinstance(value, list) else value
            text = str(value).strip()
            if text:
                return text
    return None


class Library:
    def __init__(self, root: Path, on_change=None):
        self.root = Path(root).expanduser()
        self.on_change = on_change
        self.meta_dir = self.root / ".fauxnos"
        self.art_dir = self.meta_dir / "art"
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict] = {}

    # ── Index ────────────────────────────────────────────────────────────

    def _read_json(self, name: str, default):
        try:
            return json.loads((self.meta_dir / name).read_text())
        except (FileNotFoundError, ValueError):
            return default

    def _write_json(self, name: str, data):
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_dir / f"{name}.tmp"
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.meta_dir / name)

    def _files(self) -> List[Path]:
        if not self.root.is_dir():
            return []
        return sorted(
            p for p in self.root.rglob("*")
            if p.is_file()
            and p.suffix.lower() in PLAYABLE_EXTENSIONS
            and not any(part.startswith(".") for part in p.relative_to(self.root).parts)
        )

    def _read_tags(self, path: Path, tid: str) -> Dict:
        meta = {"title": path.stem, "artist": None, "album": None, "duration_ms": None}
        if mutagen is None:
            return meta
        try:
            audio = mutagen.File(path)
        except Exception as e:
            logger.warning(f"Library: can't read tags from {path.name}: {e}")
            return meta
        if audio is None:
            return meta
        if getattr(audio, "info", None) and getattr(audio.info, "length", None):
            meta["duration_ms"] = int(audio.info.length * 1000)
        tags = audio.tags or {}
        if isinstance(audio, MP4):
            meta["title"] = _first(tags, "\xa9nam") or meta["title"]
            meta["artist"] = _first(tags, "\xa9ART", "aART")
            meta["album"] = _first(tags, "\xa9alb")
            covers = tags.get("covr")
            if covers:
                ext = ".png" if covers[0].imageformat == covers[0].FORMAT_PNG else ".jpg"
                self._save_art(tid, bytes(covers[0]), ext)
        else:  # ID3 (MP3)
            meta["title"] = _first(tags, "TIT2") or meta["title"]
            meta["artist"] = _first(tags, "TPE1", "TPE2")
            meta["album"] = _first(tags, "TALB")
            for key in tags.keys():
                if key.startswith("APIC"):
                    pic = tags[key]
                    ext = ".png" if "png" in (pic.mime or "") else ".jpg"
                    self._save_art(tid, pic.data, ext)
                    break
        return meta

    def _save_art(self, tid: str, data: bytes, ext: str):
        self.art_dir.mkdir(parents=True, exist_ok=True)
        (self.art_dir / f"{tid}{ext}").write_bytes(data)

    def art_file(self, tid: str) -> Optional[Path]:
        for ext in ART_EXTENSIONS:
            p = self.art_dir / f"{tid}{ext}"
            if p.is_file():
                return p
        return None

    def tracks(self) -> List[Dict]:
        """Every playable file, with tags. Rescans only what changed."""
        with self._lock:
            cache = self._read_json("index.json", {})
            fresh, out = {}, []
            for path in self._files():
                rel = path.relative_to(self.root).as_posix()
                st = path.stat()
                key = f"{st.st_size}:{int(st.st_mtime)}"
                tid = track_id(rel)
                entry = cache.get(rel)
                if not entry or entry.get("key") != key:
                    entry = {"key": key, **self._read_tags(path, tid)}
                fresh[rel] = entry
                art = self.art_file(tid)
                out.append({
                    "id": tid,
                    "path": rel,
                    "title": entry["title"],
                    "artist": entry["artist"],
                    "album": entry["album"],
                    "duration_ms": entry["duration_ms"],
                    "size": st.st_size,
                    "art": f"{tid}{art.suffix}" if art else None,
                })
            if fresh != cache:
                self._write_json("index.json", fresh)
                changed = True
            else:
                changed = False
            out.sort(key=lambda t: ((t["artist"] or "~").lower(), (t["album"] or "").lower(), t["title"].lower()))
        if changed:
            self._changed()
        return out

    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception as e:
                logger.warning(f"Library on_change failed: {e}")

    # ── Lookup (for MQTT / Home Assistant) ───────────────────────────────

    def resolve_tracks(self, refs: List[str]) -> List[Dict]:
        """Songs by id, path, or title (case-insensitive), in the order given.
        Unknown references are skipped."""
        tracks = self.tracks()
        by_id = {t["id"]: t for t in tracks}
        by_path = {t["path"]: t for t in tracks}
        by_title = {}
        for t in tracks:
            by_title.setdefault(t["title"].casefold(), t)
        out = []
        for ref in refs or []:
            ref = str(ref).strip()
            t = by_id.get(ref) or by_path.get(ref) or by_title.get(ref.casefold())
            if t:
                out.append(t)
        return out

    def resolve_playlist(self, ref: str) -> Optional[Dict]:
        """A playlist by id or name (case-insensitive)."""
        ref = str(ref or "").strip()
        for p in self.playlists():
            if p["id"] == ref or p["name"].casefold() == ref.casefold():
                return p
        return None

    def path_of(self, tid: str) -> Optional[str]:
        for t in self.tracks():
            if t["id"] == tid:
                return t["path"]
        return None

    def storage(self) -> Dict:
        target = self.root if self.root.is_dir() else self.root.parent
        usage = shutil.disk_usage(target)
        return {"total": usage.total, "used": usage.used, "free": usage.free}

    # ── Files ────────────────────────────────────────────────────────────

    def save_upload(self, filename: str, stream) -> Dict:
        """Store an uploaded MP3/M4A without overwriting. Returns the track."""
        name = safe_filename(filename)
        if Path(name).suffix.lower() not in UPLOAD_EXTENSIONS:
            raise ValueError("Only MP3 and M4A files can be uploaded")
        self.root.mkdir(parents=True, exist_ok=True)
        dest = self.root / name
        n = 2
        while dest.exists():
            dest = self.root / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        with open(dest, "wb") as f:
            shutil.copyfileobj(stream, f)
        rel = dest.relative_to(self.root).as_posix()
        return next(t for t in self.tracks() if t["path"] == rel)

    def delete_track(self, tid: str) -> bool:
        with self._lock:
            rel = self.path_of(tid)
            if rel is None:
                return False
            (self.root / rel).unlink(missing_ok=True)
            art = self.art_file(tid)
            if art:
                art.unlink(missing_ok=True)
            playlists = self.playlists()
            for p in playlists:
                p["track_ids"] = [t for t in p["track_ids"] if t != tid]
            self._write_json("playlists.json", playlists)
            self.tracks()  # drop it from the index
            return True

    def update_track(self, tid: str, changes: Dict) -> Optional[Dict]:
        """Write title/artist/album into the file's tags. An empty string
        clears that tag. Returns the updated track, or None if not found."""
        if mutagen is None:
            raise RuntimeError("mutagen isn't installed on the server")
        with self._lock:
            rel = self.path_of(tid)
            if rel is None:
                return None
            path = self.root / rel
            fields = {k: (changes[k] or "").strip() for k in ("title", "artist", "album") if k in changes}
            if path.suffix.lower() == ".m4a":
                keys = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb"}
                tags = MP4(path)
                for field, value in fields.items():
                    if value:
                        tags[keys[field]] = value
                    else:
                        tags.pop(keys[field], None)
                tags.save()
            elif path.suffix.lower() == ".mp3":
                frames = {"title": TIT2, "artist": TPE1, "album": TALB}
                try:
                    tags = ID3(path)
                except ID3NoHeaderError:
                    tags = ID3()
                for field, value in fields.items():
                    frame = frames[field]
                    tags.delall(frame.__name__)
                    if value:
                        tags.add(frame(encoding=3, text=value))
                tags.save(path)
            else:
                raise ValueError("Only MP3 and M4A tags can be edited")
            # A tag write can keep the size and land in the same second as
            # the last scan, so drop the cached entry rather than trust it.
            cache = self._read_json("index.json", {})
            cache.pop(rel, None)
            self._write_json("index.json", cache)
            return next((t for t in self.tracks() if t["id"] == tid), None)

    # ── Playlists ────────────────────────────────────────────────────────

    def playlists(self) -> List[Dict]:
        return self._read_json("playlists.json", [])

    def create_playlist(self, name: str, track_ids: Optional[List[str]] = None) -> Dict:
        with self._lock:
            playlists = self.playlists()
            playlist = {"id": uuid.uuid4().hex[:12], "name": name.strip() or "Playlist",
                        "track_ids": list(track_ids or [])}
            playlists.append(playlist)
            self._write_json("playlists.json", playlists)
        self._changed()
        return playlist

    def update_playlist(self, pid: str, name: Optional[str] = None,
                        track_ids: Optional[List[str]] = None,
                        add: Optional[List[str]] = None,
                        remove: Optional[List[str]] = None) -> Optional[Dict]:
        with self._lock:
            playlists = self.playlists()
            playlist = next((p for p in playlists if p["id"] == pid), None)
            if playlist is None:
                return None
            if name is not None and name.strip():
                playlist["name"] = name.strip()
            if track_ids is not None:
                playlist["track_ids"] = list(track_ids)
            if add:
                playlist["track_ids"] += [t for t in add if t not in playlist["track_ids"]]
            if remove:
                playlist["track_ids"] = [t for t in playlist["track_ids"] if t not in remove]
            self._write_json("playlists.json", playlists)
        self._changed()
        return playlist

    def delete_playlist(self, pid: str) -> bool:
        with self._lock:
            playlists = self.playlists()
            kept = [p for p in playlists if p["id"] != pid]
            if len(kept) == len(playlists):
                return False
            self._write_json("playlists.json", kept)
        self._changed()
        return True

    # ── YouTube import ───────────────────────────────────────────────────

    @staticmethod
    def youtube_available() -> bool:
        return importlib.util.find_spec("yt_dlp") is not None

    @staticmethod
    def _ytdlp(*args: str) -> List[str]:
        """A yt-dlp command line. YouTube makes yt-dlp run some JavaScript for
        most videos ("This video is not available" without it), and yt-dlp
        only looks for Deno on PATH, which the systemd service's PATH lacks,
        so point it at Deno's install location explicitly."""
        cmd = [sys.executable, "-m", "yt_dlp"]
        deno = shutil.which("deno") or str(Path.home() / ".deno" / "bin" / "deno")
        if Path(deno).is_file():
            cmd += ["--js-runtimes", f"deno:{deno}"]
        return cmd + list(args)

    def jobs(self) -> List[Dict]:
        # ponytail: jobs live in memory, so a server restart forgets them
        # (finished files stay in the library either way).
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j["started_at"], reverse=True)

    def youtube_preview(self, url: str) -> Dict:
        """Title, channel and thumbnail of a video — what the UI shows before
        Import. Uses YouTube's oEmbed endpoint (well under a second), not
        yt-dlp's full extraction, which takes ~20 s on a Pi 3B+ because it
        runs YouTube's JavaScript challenge. Falls back to yt-dlp for links
        oEmbed can't read. The import reads full details and checks the
        audio itself."""
        if not self.youtube_available():
            raise RuntimeError("yt-dlp isn't installed on the server")
        if not re.match(r"^https?://", url or ""):
            raise ValueError("Paste a full YouTube link")
        try:
            q = urllib.parse.urlencode({"url": url, "format": "json"})
            with urllib.request.urlopen(f"https://www.youtube.com/oembed?{q}", timeout=8) as resp:
                info = json.load(resp)
            return {
                "url": url,
                "title": info.get("title"),
                "artist": re.sub(r" - Topic$", "", info.get("author_name") or "") or None,
                "album": None,
                "duration_ms": None,
                "thumbnail": info.get("thumbnail_url"),
                "importable": True,
            }
        except Exception as e:
            logger.info(f"oEmbed couldn't read {url} ({e}); asking yt-dlp")
        return self._youtube_preview_ytdlp(url)

    def spotify_preview(self, url: str) -> Dict:
        """A Spotify song's details, plus the YouTube video whose audio would
        be imported (`match`, or None if nothing close was found)."""
        if not self.youtube_available():
            raise RuntimeError("yt-dlp isn't installed on the server")
        m = re.search(r"(?:open\.spotify\.com/(?:intl-[\w-]+/)?track/|spotify:track:)([A-Za-z0-9]+)", url or "")
        if not m:
            raise ValueError("Paste a Spotify song link")
        req = urllib.request.Request(f"https://open.spotify.com/embed/track/{m.group(1)}",
                                     headers={"User-Agent": "fauxnos-library/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", "replace")
            data = json.loads(re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S).group(1))
            entity = _find_key(data, "entity")["entity"]
        except Exception as e:
            logger.warning(f"Spotify details failed for {url}: {e}")
            raise ValueError("Couldn't read that Spotify song")
        title = entity.get("name") or entity.get("title")
        artist = ", ".join(a["name"] for a in entity.get("artists") or [] if a.get("name")) or None
        images = (entity.get("visualIdentity") or {}).get("image") or []
        cover = max(images, key=lambda i: i.get("maxWidth") or 0)["url"] if images else None
        duration_ms = entity.get("duration")
        return {
            "url": url,
            "title": title,
            "artist": artist,
            "album": None,
            "duration_ms": duration_ms,
            "thumbnail": cover,
            "match": self._youtube_match(f"{artist or ''} {title}".strip(), title, duration_ms),
        }

    def _youtube_match(self, query: str, title: str, duration_ms: Optional[int]) -> Optional[Dict]:
        """The YouTube search result most likely to be this song: closest in
        length, avoiding live/cover/remix/sped-up versions the title doesn't
        ask for. A flat search, so no JavaScript challenge (a few seconds)."""
        r = subprocess.run(
            self._ytdlp("--flat-playlist", "--dump-json", "--no-warnings", f"ytsearch6:{query}"),
            capture_output=True, text=True, timeout=60,
        )
        wanted = (title or "").casefold()
        best, best_score = None, None
        for line in r.stdout.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not e.get("id"):
                continue
            name = (e.get("title") or "").casefold()
            score = 0.0
            if duration_ms and e.get("duration"):
                score += abs(e["duration"] * 1000 - duration_ms) / 1000  # seconds off
            elif duration_ms:
                score += 30  # unknown length: possible, not preferred
            for word in ("live", "cover", "remix", "sped up", "slowed", "karaoke", "instrumental", "8d"):
                if word in name and word not in wanted:
                    score += 60
            if best_score is None or score < best_score:
                best, best_score = e, score
        if best is None or best_score > 45:
            return None
        return {
            "url": f"https://www.youtube.com/watch?v={best['id']}",
            "title": best.get("title"),
            "channel": best.get("channel") or best.get("uploader"),
            "duration_ms": int(best["duration"] * 1000) if best.get("duration") else None,
        }

    def _youtube_preview_ytdlp(self, url: str) -> Dict:
        r = subprocess.run(
            self._ytdlp("--no-playlist", "--skip-download", "--dump-json", "--no-warnings", url),
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            last = (r.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
            raise ValueError(last.replace("ERROR: ", ""))
        info = json.loads(r.stdout.strip().splitlines()[-1])
        has_m4a = any(f.get("ext") == "m4a" and f.get("vcodec") in (None, "none")
                      for f in info.get("formats") or [])
        return {
            "url": url,
            "title": info.get("track") or info.get("title"),
            "artist": info.get("artist") or re.sub(r" - Topic$", "", info.get("uploader") or "") or None,
            "album": info.get("album"),
            "duration_ms": int(info["duration"] * 1000) if info.get("duration") else None,
            "thumbnail": info.get("thumbnail"),
            "importable": has_m4a,
        }

    def start_youtube_import(self, url: str, title: Optional[str] = None,
                             artist: Optional[str] = None, thumbnail: Optional[str] = None,
                             tags: Optional[Dict] = None, art_url: Optional[str] = None) -> Dict:
        """Import a video's audio in the background. `tags` (title/artist/
        album) override what YouTube says, and `art_url` replaces the video
        thumbnail as cover art — both used for Spotify imports."""
        if not self.youtube_available():
            raise RuntimeError("yt-dlp isn't installed on the server")
        if not re.match(r"^https?://", url or ""):
            raise ValueError("Paste a full YouTube link")
        # title/artist/thumbnail (from the preview) show the job in the list
        # until the download finishes and the real song replaces it.
        job = {"id": uuid.uuid4().hex[:12], "url": url, "status": "running",
               "title": title or None, "artist": artist or None, "thumbnail": thumbnail or None,
               "tags": {k: v for k, v in (tags or {}).items() if k in ("title", "artist", "album") and v},
               "art_url": art_url or None, "error": None, "track_id": None, "started_at": time.time()}
        with self._lock:
            self._jobs[job["id"]] = job
        threading.Thread(target=self._run_youtube, args=(job,), daemon=True).start()
        return dict(job)

    def _run_youtube(self, job: Dict):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_dir / "incoming" / job["id"]
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            # M4A audio only, so nothing is transcoded on the Pi.
            cmd = self._ytdlp("--no-playlist", "-f", "bestaudio[ext=m4a]", "--write-thumbnail",
                              "--print-json", "--no-progress",
                              "-o", str(tmp / "audio.%(ext)s"), job["url"])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                last = (r.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
                raise RuntimeError(last.replace("ERROR: ", ""))
            info = json.loads(r.stdout.strip().splitlines()[-1])
            audio = tmp / "audio.m4a"
            if not audio.is_file():
                raise RuntimeError("No M4A audio was available for this video")

            override = job.get("tags") or {}
            title = override.get("title") or info.get("track") or info.get("title") or "YouTube audio"
            artist = override.get("artist") or info.get("artist") or re.sub(r" - Topic$", "", info.get("uploader") or "") or None
            album = override.get("album") or info.get("album")
            job["title"] = title
            if mutagen is not None:
                tags = MP4(audio)
                tags["\xa9nam"] = title
                if artist:
                    tags["\xa9ART"] = artist
                if album:
                    tags["\xa9alb"] = album
                tags.save()

            base = safe_filename(f"{artist} - {title}" if artist else title)
            dest = self.root / f"{base}.m4a"
            n = 2
            while dest.exists():
                dest = self.root / f"{base} ({n}).m4a"
                n += 1
            shutil.move(str(audio), dest)
            tid = track_id(dest.relative_to(self.root).as_posix())
            thumb = next((p for p in tmp.iterdir() if p.suffix.lower() in ART_EXTENSIONS), None)
            if job.get("art_url"):
                try:
                    with urllib.request.urlopen(job["art_url"], timeout=15) as resp:
                        cover = tmp / "cover.jpg"
                        cover.write_bytes(resp.read())
                    thumb = cover
                except Exception as e:
                    logger.warning(f"Cover download failed ({e}); using the video thumbnail")
            if thumb:
                self.art_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(thumb), self.art_dir / f"{tid}{thumb.suffix.lower()}")
            self.tracks()
            job.update(status="done", track_id=tid)
        except Exception as e:
            logger.error(f"YouTube import failed for {job['url']}: {e}")
            job.update(status="failed", error=str(e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
