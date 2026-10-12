"""kyeon.exe 의 아이콘(tools/kyeon.ico)을 그린다. 표준 라이브러리만 쓴다.

  python tools/make_icon.py            tools/kyeon.ico 를 새로 쓴다

어두운 둥근 네모 한가운데에 호박색 불빛 하나. 이름의 '켠'(불을 켜다)을 그린 것이다.
"""
import math
import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "kyeon.ico"
SIZES = (256, 64, 48, 32, 24, 16)
BG = (0x2A, 0x27, 0x23)
EDGE = (0x4A, 0x44, 0x3A)
AMBER = (0xE3, 0xBE, 0x72)
CREAM = (0xFF, 0xF3, 0xD6)
SS = 4  # 한 픽셀을 SS x SS 로 나누어 가장자리를 부드럽게


def in_round_box(x: float, y: float, half: float, r: float) -> float:
    """둥근 네모 안쪽 거리(양수면 안). 중심 0.5,0.5 기준."""
    qx, qy = abs(x - 0.5) - (half - r), abs(y - 0.5) - (half - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return r - (outside + inside)


def shade(x: float, y: float) -> tuple:
    """한 점의 색(r, g, b, a). 안쪽 테두리 선, 불빛 둘레의 번짐, 불빛 알맹이."""
    d = in_round_box(x, y, 0.48, 0.2)
    if d < 0:
        return (0, 0, 0, 0.0)
    col = BG
    if d < 0.018:  # 가장자리 선
        col = EDGE
    # 불빛은 한가운데에서 살짝 위
    dx, dy = x - 0.5, y - 0.47
    r = math.hypot(dx, dy)
    glow = 0.5 * math.exp(-(r / 0.2) ** 2)
    col = tuple(c + (a - c) * glow for c, a in zip(col, AMBER))
    if r < 0.15:  # 알맹이: 가운데는 더 밝게
        t = r / 0.15
        core = tuple(a + (c - a) * (1 - t) ** 1.6 for a, c in zip(AMBER, CREAM))
        col = core
    return (col[0], col[1], col[2], 1.0)


def render(size: int) -> bytes:
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG 필터 없음
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    cr, cg, cb, ca = shade((px + (sx + 0.5) / SS) / size, (py + (sy + 0.5) / SS) / size)
                    r += cr * ca
                    g += cg * ca
                    b += cb * ca
                    a += ca
            if a:
                row += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / (SS * SS))))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> int:
    images = [(s, render(s)) for s in SIZES]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, png in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    OUT.write_bytes(head + entries + blobs)
    print(f"{OUT} ({OUT.stat().st_size:,} 바이트, 크기 {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
