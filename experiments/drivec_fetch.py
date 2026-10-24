"""Fetch selected members of DRIVE-C (CC BY 4.0, zenodo.org/records/19656444) without the full 9 GB zip.

    python3 -I experiments/drivec_fetch.py --out ~/drivec --list
    python3 -I experiments/drivec_fetch.py --out ~/drivec --types defocus_blur lens_occlusion --severities 1 3 5

Reads the zip's central directory with HTTP range requests and extracts only matching entries, in
parallel. Downloaded files are data only; nothing from the archive is executed. Run with -I.
"""
import argparse
import io
import zipfile
import zlib
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://zenodo.org/records/19656444/files/drivec_core_v1.zip?download=1"


class Remote(io.RawIOBase):
    def __init__(self, url):
        head = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60)
        self.url, self.size, self.pos = head.url, int(head.headers["Content-Length"]), 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def read_range(self, start, length):
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{start + length - 1}"})
        return urllib.request.urlopen(request, timeout=300).read()

    def readinto(self, buffer):
        if self.pos >= self.size:
            return 0
        data = self.read_range(self.pos, min(len(buffer), self.size - self.pos))
        buffer[:len(data)] = data
        self.pos += len(data)
        return len(data)


def extract(remote, info, out: Path):
    target = out / info.filename
    if target.exists() and target.stat().st_size == info.file_size:
        return info.filename, "cached"
    header = remote.read_range(info.header_offset, 30)
    data_start = info.header_offset + 30 + int.from_bytes(header[26:28], "little") + int.from_bytes(header[28:30], "little")
    raw = remote.read_range(data_start, info.compress_size)
    data = raw if info.compress_type == zipfile.ZIP_STORED else zlib.decompress(raw, -15)
    if zlib.crc32(data) != info.CRC:
        raise ValueError(f"CRC mismatch for {info.filename}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return info.filename, len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--types", nargs="*", default=[])
    ap.add_argument("--severities", nargs="*", default=["1", "2", "3", "4", "5"])
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    remote = Remote(URL)
    entries = [i for i in zipfile.ZipFile(io.BufferedReader(Remote(URL), buffer_size=1 << 20)).infolist() if not i.is_dir()]
    if args.list:
        sizes = {}
        for i in entries:
            parts = i.filename.split("/")
            key = parts[2] if len(parts) > 3 and parts[1] == "corrupted" else parts[1]
            sizes[key] = sizes.get(key, 0) + i.file_size
        for key, size in sorted(sizes.items()):
            print(f"{size / 1e6:9.1f} MB  {key}")
        return
    wanted = [i for i in entries if "/corrupted/" not in i.filename and not i.filename.endswith(".png")
              or (i.filename.split("/")[2] in args.types and i.filename.split("/")[3] in {f"s{s}" for s in args.severities})]
    print(f"fetching {len(wanted)} files, {sum(i.file_size for i in wanted) / 1e6:.0f} MB", flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for name, result in pool.map(lambda i: extract(remote, i, args.out), wanted):
            print(name, result, flush=True)


if __name__ == "__main__":
    main()
