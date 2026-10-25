#!/usr/bin/env python3
"""Graft a stock Android boot image's AVB footer onto a fastboot-boot image.

PHK110's ABL rejects an otherwise valid, unsigned boot image before executing
it.  The existing Udon boot experiments pass this check by moving the stock
vbmeta blob immediately after the replacement image content and updating the
footer's original-image-size and vbmeta-offset fields.  The stock vbmeta and
cryptographic footer are reused byte for byte; this is not a new signature.

usage: graft-boot-footer.py --image reader.img --stock stock-boot.img --out grafted.img
"""
import argparse
import hashlib
import struct
from pathlib import Path


MAGIC = b"AVBf"
FOOTER = struct.Struct(">4sIIQQQ")
FOOTER_SIZE = 64


def footer_at_end(image, label):
    if len(image) < FOOTER_SIZE:
        raise SystemExit(f"{label} is too small to contain an AVB footer")
    footer = FOOTER.unpack_from(image, len(image) - FOOTER_SIZE)
    if footer[0] != MAGIC:
        raise SystemExit(f"{label} has no AVB footer at the end of the partition")
    _, _, _, original_size, vbmeta_offset, vbmeta_size = footer
    if original_size > vbmeta_offset or vbmeta_offset + vbmeta_size > len(image) - FOOTER_SIZE:
        raise SystemExit(f"{label} has an invalid AVB footer layout")
    vbmeta = image[vbmeta_offset:vbmeta_offset + vbmeta_size]
    if len(vbmeta) != vbmeta_size or vbmeta[:4] != b"AVB0":
        raise SystemExit(f"{label} has a truncated or invalid vbmeta blob")
    return original_size, vbmeta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--stock", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    image = a.image.read_bytes()
    stock = a.stock.read_bytes()
    if image[:8] != b"ANDROID!":
        raise SystemExit(f"{a.image} is not an Android boot image")
    if stock[:8] != b"ANDROID!":
        raise SystemExit(f"{a.stock} is not an Android boot image")
    if image[-FOOTER_SIZE:-FOOTER_SIZE + len(MAGIC)] == MAGIC:
        raise SystemExit(f"{a.image} already contains AVB footer data; pass the unsigned boot image")

    _, vbmeta = footer_at_end(stock, str(a.stock))
    partition_size = len(stock)
    if len(image) + len(vbmeta) + FOOTER_SIZE > partition_size:
        raise SystemExit("boot image and vbmeta do not fit in the stock partition")

    output = bytearray(partition_size)
    output[:len(image)] = image
    output[len(image):len(image) + len(vbmeta)] = vbmeta
    footer = FOOTER.pack(MAGIC, 1, 0, len(image), len(image), len(vbmeta))
    output[-FOOTER_SIZE:] = footer + b"\0" * (FOOTER_SIZE - len(footer))
    footer_at_end(output, str(a.out))
    a.out.write_bytes(output)

    print(
        f"wrote {a.out}: image={len(image)} vbmeta={len(vbmeta)} "
        f"partition={partition_size} sha256={hashlib.sha256(output).hexdigest()}"
    )


if __name__ == "__main__":
    main()
