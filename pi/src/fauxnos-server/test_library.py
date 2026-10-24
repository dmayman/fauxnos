#!/usr/bin/env python3
"""
Test the Library: uploads (MP3/M4A only, no overwrites, no path tricks),
tags and cover art from ID3, playlists, and deleting a track also removes
it from playlists.

Run: python3 test_library.py   (needs mutagen for the tag checks)
"""

import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.library import Library, safe_filename, mutagen

# One silent MPEG-1 Layer III frame (128 kbps, 44.1 kHz), repeated: ~10 s.
FRAME = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)
MP3 = FRAME * 383


def tagged_mp3(title, artist, album):
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC
    buf = io.BytesIO(MP3)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.add(TALB(encoding=3, text=album))
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, data=b"\xff\xd8fakejpeg"))
    tags.save(buf)
    buf.seek(0)
    return buf


def demo():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename('a:b*?.mp3') == "a_b__.mp3"

    with tempfile.TemporaryDirectory() as d:
        lib = Library(Path(d) / "lib")
        assert lib.tracks() == []

        t1 = lib.save_upload("song.mp3", io.BytesIO(MP3))
        t2 = lib.save_upload("song.mp3", io.BytesIO(MP3))  # same name: no overwrite
        assert t1["path"] == "song.mp3" and t2["path"] == "song (2).mp3", (t1, t2)
        try:
            lib.save_upload("evil.exe", io.BytesIO(b"x"))
            raise AssertionError("non-audio upload must be rejected")
        except ValueError:
            pass
        assert not (Path(d) / "lib" / "evil.exe").exists()

        if mutagen is not None:
            t3 = lib.save_upload("x.mp3", tagged_mp3("Twinkle", "Mom", "Lullabies"))
            assert (t3["title"], t3["artist"], t3["album"]) == ("Twinkle", "Mom", "Lullabies"), t3
            assert t3["art"] == f"{t3['id']}.jpg" and lib.art_file(t3["id"]).is_file()
            assert 9000 < t3["duration_ms"] < 11000, t3["duration_ms"]
            t3 = lib.update_track(t3["id"], {"title": "Twinkle Little Star", "album": ""})
            assert (t3["title"], t3["artist"], t3["album"]) == ("Twinkle Little Star", "Mom", None), t3
            plain = lib.update_track(t1["id"], {"artist": "Dad"})  # MP3 with no tags yet
            assert plain["artist"] == "Dad" and plain["id"] == t1["id"], plain
            print("ok: tags, duration and cover art are read from ID3, and edits are written back")

        p = lib.create_playlist("Bedtime", [t1["id"]])
        lib.update_playlist(p["id"], add=[t2["id"], t1["id"]], name="Sleep")
        assert lib.playlists()[0]["track_ids"] == [t1["id"], t2["id"]]
        assert lib.playlists()[0]["name"] == "Sleep"

        assert lib.delete_track(t1["id"])
        assert lib.playlists()[0]["track_ids"] == [t2["id"]], "delete must leave playlists"
        assert not (Path(d) / "lib" / "song.mp3").exists()
        assert not lib.delete_track(t1["id"])
        assert lib.delete_playlist(p["id"]) and lib.playlists() == []

        # Files under .fauxnos (index, art) are never listed as tracks.
        assert all(not t["path"].startswith(".") for t in lib.tracks())
        print("ok: uploads, playlists and deletes behave")


if __name__ == "__main__":
    demo()
