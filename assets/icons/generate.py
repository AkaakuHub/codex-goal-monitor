from pathlib import Path
import struct
import subprocess

directory = Path(__file__).resolve().parent
source = directory / "app.svg"


def render(*arguments: str) -> bytes:
    return subprocess.run(
        ["magick", "-background", "none", str(source), *arguments],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


(directory / "app.png").write_bytes(render("png32:-"))
(directory / "tray.rgba").write_bytes(render("-resize", "32x32", "-depth", "8", "rgba:-"))
images = [render("-resize", f"{size}x{size}", "png32:-") for size in [16, 32, 48, 64, 128, 256]]
offset = 6 + 16 * len(images)
entries = []
for size, data in zip([16, 32, 48, 64, 128, 256], images):
    entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
(directory / "app.ico").write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(images))
chunks = []
for kind, size in [(b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)]:
    data = render("-resize", f"{size}x{size}", "png32:-")
    chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
body = b"".join(chunks)
(directory / "app.icns").write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
