"""Create a realistic, reproducible home folder for screenshots and demos.

    python3 tools/demo_home.py /tmp/demo-home

Writes Desktop, Documents, Downloads, Pictures, Music, Videos and a projects folder, with
small files of many kinds (real PNG images, text, source code...). Only the standard library.
"""
import os
import struct
import sys
import time
import zlib


def png(path, w, h, top, bottom, accent):
    """A gradient PNG with a soft circle, so thumbnails look like photos at a glance."""
    rows = []
    cx, cy, r = w * 0.68, h * 0.38, min(w, h) * 0.22
    for y in range(h):
        t = y / (h - 1)
        base = [round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)]
        row = bytearray([0])
        for x in range(w):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            k = max(0.0, min(1.0, (r - d) / 6 + 0.5))
            hill = 1 if y > h * 0.62 + 18 * __import__("math").sin(x / w * 6.3) else 0
            px = [round(base[i] * (1 - k) + accent[i] * k) for i in range(3)]
            if hill:
                px = [round(c * 0.55) for c in px]
            row += bytes(px)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def write(path, content=b"", size=None, age_days=0.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode()
    with open(path, "wb") as f:
        f.write(data)
        if size and len(data) < size:
            f.truncate(size)  # sparse: realistic sizes, almost nothing on disk
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))


def main(root):
    root = os.path.abspath(root)
    photos = [("Lake at dawn.png", (255, 190, 140), (90, 110, 170), (255, 240, 200)),
              ("Mountains.png", (140, 190, 255), (40, 70, 120), (255, 255, 255)),
              ("Sunset beach.png", (255, 120, 90), (120, 40, 110), (255, 220, 120)),
              ("Forest trail.png", (170, 220, 170), (30, 80, 60), (250, 250, 210)),
              ("Night sky.png", (30, 30, 70), (5, 5, 20), (240, 240, 255)),
              ("Desert.png", (250, 210, 150), (190, 110, 60), (255, 250, 230))]
    for i, (name, a, b, c) in enumerate(photos):
        p = os.path.join(root, "Pictures", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        png(p, 160, 120, a, b, c)
        os.utime(p, (time.time() - i * 86400 * 9, time.time() - i * 86400 * 9))
    write(os.path.join(root, "Pictures", "Screenshots", "screen-01.png"), size=10)
    os.remove(os.path.join(root, "Pictures", "Screenshots", "screen-01.png"))
    png(os.path.join(root, "Pictures", "Screenshots", "Screenshot 2026-10-28.png"), 160, 100, (230, 232, 240),
        (200, 205, 220), (99, 102, 241))
    docs = {
        "Quarterly report.pdf": (b"%PDF-1.7\n", 2_400_000, 2), "Budget 2026.xlsx": (b"PK", 184_000, 5),
        "Product roadmap.pptx": (b"PK", 5_300_000, 12), "Meeting notes.md": ("# Meeting notes\n\n- Ship 0.2\n- "
                                                                           "Windows file browser\n- Screenshots\n", 0, 0.2),
        "Contract draft.docx": (b"PK", 96_000, 30), "Invoices.csv": ("date,client,amount\n2026-10-01,Acme,1200\n", 0, 3),
        "Resume.pdf": (b"%PDF-1.7\n", 310_000, 80), "Archive 2025.zip": (b"PK", 48_000_000, 300),
    }
    for name, (content, size, age) in docs.items():
        write(os.path.join(root, "Documents", name), content, size, age)
    for sub in ("Taxes", "Travel", "Work"):
        write(os.path.join(root, "Documents", sub, "readme.txt"), "notes\n", age_days=40)
    project = os.path.join(root, "Documents", "Projects", "zepygui-app")
    write(os.path.join(project, "app.py"), "from zepygui import App, ui\n\napp = App('Demo')\n", age_days=1)
    write(os.path.join(project, "README.md"), "# Demo app\n", age_days=1)
    write(os.path.join(project, "pyproject.toml"), "[project]\nname = 'demo'\n", age_days=1)
    write(os.path.join(project, ".gitignore"), "__pycache__/\n", age_days=1)
    downloads = {"python-3.13.1-amd64.exe": 27_000_000, "zepygui-0.2.0.tar.gz": 96_000, "Inter-4.1.zip": 11_200_000,
                 "podcast-episode-42.mp3": 54_000_000, "holiday-video.mp4": 380_000_000, "font-JetBrainsMono.ttf": 270_000,
                 "data-export.json": 1_200_000, "setup-notes.txt": 2_000}
    for i, (name, size) in enumerate(downloads.items()):
        write(os.path.join(root, "Downloads", name), size=size, age_days=i * 1.7)
    for name in ("Track 01 - Intro.flac", "Track 02 - Daylight.flac", "Ambient mix.mp3"):
        write(os.path.join(root, "Music", name), size=4000, age_days=60)
    for name in ("Birthday.mp4", "Drone flight.mov"):
        write(os.path.join(root, "Videos", name), size=4000, age_days=20)
    write(os.path.join(root, "Desktop", "Todo.txt"), "- write the README\n", age_days=0.05)
    write(os.path.join(root, "Desktop", "Design mockup.png"), size=0)
    png(os.path.join(root, "Desktop", "Design mockup.png"), 160, 120, (245, 245, 250), (225, 228, 240), (43, 111, 242))
    write(os.path.join(root, ".config", "user-dirs.dirs"), "\n".join(
        f'XDG_{k}_DIR="$HOME/{v}"' for k, v in (("DESKTOP", "Desktop"), ("DOCUMENTS", "Documents"),
                                                ("DOWNLOAD", "Downloads"), ("PICTURES", "Pictures"),
                                                ("MUSIC", "Music"), ("VIDEOS", "Videos"))) + "\n")
    print(root)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo-home")
