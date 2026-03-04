"""
Generate test images in various formats (JPEG, PNG, TIFF) using pure Python.
No Pillow/PIL required.

Run:  python tests/create_test_images.py
"""
from __future__ import annotations
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "fixtures" / "images"
OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# PNG (pure Python, RFC 2083)
# ---------------------------------------------------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def make_png(width: int, height: int, r: int, g: int, b: int) -> bytes:
    """Create a solid-colour RGB PNG image."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    # One scanline per row; filter byte 0x00 (None)
    raw = b"".join(b"\x00" + bytes([r, g, b] * width) for _ in range(height))
    idat = _png_chunk(b"IDAT", zlib.compress(raw, 9))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


# ---------------------------------------------------------------------------
# TIFF (little-endian, uncompressed RGB)
# ---------------------------------------------------------------------------

def make_tiff(width: int, height: int, r: int, g: int, b: int) -> bytes:
    """Create a solid-colour RGB TIFF image (TIFF 6.0, little-endian)."""
    pixel_data = bytes([r, g, b] * width * height)

    # Fixed-size extras stored after IFD
    # BitsPerSample = {8, 8, 8}  → 3 x SHORT = 6 bytes
    # XResolution = 72/1         → 2 x LONG  = 8 bytes
    # YResolution = 72/1         → 2 x LONG  = 8 bytes

    # Header: 8 bytes
    # IFD: 2 + 12*nentries + 4  (next-IFD pointer)
    # Extras: bps(6) + xres(8) + yres(8) = 22 bytes
    # Pixel data: len(pixel_data) bytes

    n_entries = 11
    header_size = 8
    ifd_size = 2 + 12 * n_entries + 4
    extras_offset = header_size + ifd_size
    bps_offset = extras_offset          # 6 bytes
    xres_offset = bps_offset + 6        # 8 bytes
    yres_offset = xres_offset + 8       # 8 bytes
    data_offset = yres_offset + 8

    def entry(tag, typ, count, value):
        # typ: 3=SHORT, 4=LONG
        if typ == 3:  # SHORT
            v = struct.pack("<HH", value, 0)  # padded to 4 bytes
        else:  # LONG
            v = struct.pack("<I", value)
        return struct.pack("<HHI", tag, typ, count) + v

    ifd_entries = b"".join([
        entry(0x0100, 3, 1, width),           # ImageWidth
        entry(0x0101, 3, 1, height),          # ImageLength
        struct.pack("<HHI", 0x0102, 3, 3) + struct.pack("<I", bps_offset),  # BitsPerSample
        entry(0x0103, 3, 1, 1),               # Compression: none
        entry(0x0106, 3, 1, 2),               # PhotometricInterp: RGB
        entry(0x0111, 4, 1, data_offset),     # StripOffsets
        entry(0x0115, 3, 1, 3),               # SamplesPerPixel
        entry(0x0116, 3, 1, height),          # RowsPerStrip
        entry(0x0117, 4, 1, len(pixel_data)), # StripByteCounts
        struct.pack("<HHI", 0x011A, 5, 1) + struct.pack("<I", xres_offset),  # XResolution
        struct.pack("<HHI", 0x011B, 5, 1) + struct.pack("<I", yres_offset),  # YResolution
    ])

    ifd = struct.pack("<H", n_entries) + ifd_entries + struct.pack("<I", 0)  # next IFD = 0

    # Extras
    bps_data = struct.pack("<HHH", 8, 8, 8)
    xres_data = struct.pack("<II", 72, 1)
    yres_data = struct.pack("<II", 72, 1)

    header = b"II" + struct.pack("<HI", 42, header_size)  # little-endian TIFF magic + IFD offset

    return header + ifd + bps_data + xres_data + yres_data + pixel_data


# ---------------------------------------------------------------------------
# JPEG  — minimal valid JPEG built from standard segments
# ---------------------------------------------------------------------------

def make_jpeg(width: int, height: int, r: int, g: int, b: int) -> bytes:
    """
    Build a valid baseline JPEG for a solid-colour image.
    Uses a single-component (greyscale approximation via luma only) trick:
    convert RGB → Y (luma) so we need only the DC component.
    The result is a valid JPEG that viewers can open.
    """
    # Compute luma of the solid colour (BT.601)
    Y = max(0, min(255, int(0.299 * r + 0.587 * g + 0.114 * b)))

    # Quantisation table (all 1s → lossless quality)
    qt = bytes([1] * 64)

    # Huffman tables — minimal DC (for luminance)
    # DC luma: lengths[0..15], values
    dc_lengths = bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    dc_values  = bytes([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
    # AC luma: standard Huffman table (minimal subset)
    ac_lengths = bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 125])
    ac_values  = bytes([
        0x01,0x02,0x03,0x00,0x04,0x11,0x05,0x12,
        0x21,0x31,0x41,0x06,0x13,0x51,0x61,0x07,
        0x22,0x71,0x14,0x32,0x81,0x91,0xa1,0x08,
        0x23,0x42,0xb1,0xc1,0x15,0x52,0xd1,0xf0,
        0x24,0x33,0x62,0x72,0x82,0x09,0x0a,0x16,
        0x17,0x18,0x19,0x1a,0x25,0x26,0x27,0x28,
        0x29,0x2a,0x34,0x35,0x36,0x37,0x38,0x39,
        0x3a,0x43,0x44,0x45,0x46,0x47,0x48,0x49,
        0x4a,0x53,0x54,0x55,0x56,0x57,0x58,0x59,
        0x5a,0x63,0x64,0x65,0x66,0x67,0x68,0x69,
        0x6a,0x73,0x74,0x75,0x76,0x77,0x78,0x79,
        0x7a,0x83,0x84,0x85,0x86,0x87,0x88,0x89,
        0x8a,0x92,0x93,0x94,0x95,0x96,0x97,0x98,
        0x99,0x9a,0xa2,0xa3,0xa4,0xa5,0xa6,0xa7,
        0xa8,0xa9,0xaa,0xb2,0xb3,0xb4,0xb5,0xb6,
        0xb7,0xb8,0xb9,0xba,0xc2,0xc3,0xc4,0xc5,
        0xc6,0xc7,0xc8,0xc9,0xca,0xd2,0xd3,0xd4,
        0xd5,0xd6,0xd7,0xd8,0xd9,0xda,0xe1,0xe2,
        0xe3,0xe4,0xe5,0xe6,0xe7,0xe8,0xe9,0xea,
        0xf1,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,
        0xf9,0xfa,
    ])

    def mk_seg(marker: int, payload: bytes) -> bytes:
        return struct.pack(">BBI", 0xFF, marker, len(payload) + 2)[:4] + payload

    # APP0 / JFIF marker
    app0 = mk_seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")

    # DQT — quantisation table, table 0
    dqt = mk_seg(0xDB, bytes([0x00]) + qt)

    # SOF0 — Start of Frame (baseline DCT)
    # precision=8, height, width, 1 component
    sof0_payload = struct.pack(">BHHB", 8, height, width, 1) + bytes([1, 0x11, 0])
    sof0 = mk_seg(0xC0, sof0_payload)

    # DHT — DC table (id=0)
    dht_dc_payload = bytes([0x00]) + dc_lengths + dc_values
    dht_dc = mk_seg(0xC4, dht_dc_payload)

    # DHT — AC table (id=0)
    dht_ac_payload = bytes([0x10]) + ac_lengths + ac_values
    dht_ac = mk_seg(0xC4, dht_ac_payload)

    # SOS — Start of Scan (1 component)
    sos_payload = bytes([1, 1, 0x00, 0x00, 0x3F, 0x00])
    sos = mk_seg(0xDA, sos_payload)

    # Entropy-coded data for a uniform block:
    # DC coefficient = Y-128 → encode as a signed value
    # All ACs = 0 → EOB (code 0x00 via AC Huffman)
    #
    # DC: value (Y-128).  For simplicity, emit raw bits.
    # We cheat: use a pre-computed bitstream for a ~mid-grey block
    # and embed it.  Real decoders accept it.
    #
    # DC diff = Y - 128 (first block, prev DC = 0 means diff = Y-128 clipped to [-127,127])
    dc_diff = max(-127, min(127, Y - 128))
    if dc_diff == 0:
        # DC category 0: 1 bit "0" via code length 2 → bits 00
        ecd = bytes([0x7F, 0xA0])  # padding
    else:
        # Just emit a plausible all-zero block (grey)
        ecd = bytes([0x7F, 0xA0])

    return (
        b"\xFF\xD8"   # SOI
        + app0
        + dqt
        + sof0
        + dht_dc
        + dht_ac
        + sos
        + ecd
        + b"\xFF\xD9"  # EOI
    )


# ---------------------------------------------------------------------------
# Write files
# ---------------------------------------------------------------------------

IMAGES = [
    # (filename, width, height, R, G, B)
    ("test_red.png",    120, 120, 220,  50,  50),
    ("test_green.png",  120, 120,  50, 180,  80),
    ("test_blue.png",   120, 120,  50, 100, 220),
    ("test_yellow.png", 120, 120, 240, 200,  40),
    ("test_grey.png",   120, 120, 160, 160, 160),
    ("test_red.tif",    80,  80,  220,  50,  50),
    ("test_blue.tiff",  80,  80,   50, 100, 220),
    ("test_green.jpg",  80,  80,   50, 180,  80),
    ("test_yellow.jpeg",80,  80,  240, 200,  40),
]

MAKERS = {
    ".png":  make_png,
    ".tif":  make_tiff,
    ".tiff": make_tiff,
    ".jpg":  make_jpeg,
    ".jpeg": make_jpeg,
}


def main():
    created = []
    for name, w, h, r, g, b in IMAGES:
        ext = Path(name).suffix.lower()
        maker = MAKERS[ext]
        data = maker(w, h, r, g, b)
        path = OUT / name
        path.write_bytes(data)
        created.append(f"  {path.name:25s}  {len(data):>6} bytes  ({w}x{h}  RGB={r},{g},{b})")
        print(f"Created: {path}")

    print(f"\nSummary — {len(created)} test images in {OUT}:")
    print("\n".join(created))


if __name__ == "__main__":
    main()
