#!/usr/bin/env python3
"""
Build a PDC sequence holding every icon in a folder as a frame.

Frame order comes from the filenames, sorted. Prefix each file with a number to
fix its position:

    icons/000_cloud.svg    -> frame 0, I_CLOUD
    icons/010_sun.svg      -> frame 1, I_SUN
    icons/020_partly.svg   -> frame 2, I_PARTLY

Gaps of ten leave room to slot something in later without renaming everything.
The prefix is stripped to make the constant name.

Why a sequence rather than one file per icon: Pebble assigns resource ids in
build order and they shift whenever resources are added or reordered, while
Poco only accepts the bare number — the identifier typed into CloudPebble is a
C constant and throws "not found" from Alloy. A sequence sidesteps that; the
watch locates each set by the fingerprint stored in its frame duration.

Two modes:

    python3 build_icons.py seq    <svg_folder> [more...] <output.pdc>
    python3 build_icons.py single <svg_folder> <output_folder>

seq packs a folder into one PDC sequence, one icon per frame. Use it where the
code computes the index — the weather icons, where wx_slot() returns an offset.
Folders concatenate in the order given, each sorted by filename.

single writes one PDC image per SVG, named after the file. Use it for icons
referenced by name exactly once — arrows, windsock, compass, steps, heart. In C
each becomes its own RESOURCE_ID_ constant, so there are no frame numbers to
keep in step and adding one cannot disturb the others.

Both modes print the package.json media entries and the C defines to paste.

Run with no arguments to print this usage.

Both paths may be absolute or relative to the current directory. The viewbox
is taken from the first SVG, so a folder of 18px icons produces an 18px
sequence — drawDCI does not scale, so each size the watch draws needs its own
folder and its own sequence.
"""

import argparse
import glob
import os
import re
import struct
import subprocess
import sys
import tempfile

def icon_name(path):
    """000_cloud.svg -> cloud"""
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'^[0-9]+[_-]?', '', stem)


def fingerprint(names):
    """16-bit FNV-1a over the ordered icon names.

    Nothing animates, so the frame duration is a free field. Storing the
    fingerprint there lets the watch check at load that the resource it found
    was built from the same list its constants were written for. Reorder or add
    an icon and the number changes, so a stale upload reports a mismatch
    instead of silently drawing the wrong icons.
    """
    h = 0x811c
    for ch in ",".join(names):
        h ^= ord(ch)
        h = (h * 0x0101) & 0xFFFF
    return h or 1          # 0 would read as "no duration"


def box_of(svg_text):
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg_text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'width="(\d+)".*?height="(\d+)"', svg_text, re.S)
    if not m:
        sys.exit("cannot read the viewbox from an SVG")
    return int(m.group(1)), int(m.group(2))


def normalise(svg_text, box):
    """Frames of a sequence share one viewbox, taken from the first file."""
    w, h = box
    svg_text = re.sub(r'width="\d+"', f'width="{w}"', svg_text, count=1)
    svg_text = re.sub(r'height="\d+"', f'height="{h}"', svg_text, count=1)
    svg_text = re.sub(r'viewBox="0 0 \d+ \d+"', f'viewBox="0 0 {w} {h}"',
                      svg_text, count=1)
    return svg_text


def collect(icon_dirs, block=0):
    """Concatenate the folders in the order given, each sorted by filename.

    With a block size, each folder is padded out to a multiple of it so the
    next folder always starts at the same index. Padding entries are (None,
    name) and become empty frames.
    """
    files, names, bases = [], [], []

    for d in icon_dirs:
        found = sorted(glob.glob(os.path.join(d, "*.svg")))
        if not found:
            sys.exit(f"no SVGs in {d}/")

        bases.append((os.path.basename(d.rstrip("/")), len(files), len(found)))
        files += found
        names += [icon_name(f) for f in found]

        if block:
            if len(found) > block:
                sys.exit(f"{d}/ has {len(found)} frames, over the block of {block}")
            for k in range(block - len(found)):
                files.append(None)
                names.append(f"pad{len(names)}")

    real = [n for f, n in zip(files, names) if f is not None]
    dupes = sorted({n for n in real if real.count(n) > 1})
    if dupes:
        sys.exit("duplicate frame names across folders: " + ", ".join(dupes))

    return files, names, bases


def build_single(files, names, out_dir, here):
    """One PDC image per SVG. No frame numbers: each gets its own resource."""
    converter = os.path.join(here, "svg2pdc.py")
    os.makedirs(out_dir, exist_ok=True)

    made = []
    for src, name in zip(files, names):
        out = os.path.join(out_dir, name + ".pdc")
        result = subprocess.run([sys.executable, converter, src, "-o", out],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            sys.exit(f"conversion failed for {src}")

        d = open(out, "rb").read()
        if d[0:4] != b"PDCI":
            sys.exit(f"{out}: expected an image, magic is {d[0:4]!r}")
        made.append((name, len(d)))

    print(f"\n{out_dir}: {len(made)} images")
    for name, size in made:
        print(f"  {name}.pdc{'':<4}{size:>5} bytes")

    print("\npackage.json media entries:\n")
    for name, _ in made:
        print('  { "type": "raw", "name": "ICON_' + name.upper() +
              '", "file": "data/' + name + '.pdc" },')

    print("\nC:\n")
    for name, _ in made:
        print(f"  gdraw_command_image_create_with_resource("
              f"RESOURCE_ID_ICON_{name.upper()});")


def build(files, names, out_path, here):
    converter = os.path.join(here, "svg2pdc.py")
    if not os.path.exists(converter):
        sys.exit("svg2pdc.py not found beside this script")

    frame_ms = fingerprint(names)

    # frames share one viewbox: take the largest, so nothing is clipped
    boxes = [box_of(open(f).read()) for f in files if f is not None]
    box = (max(b[0] for b in boxes), max(b[1] for b in boxes))

    with tempfile.TemporaryDirectory() as tmp:
        # svg2pdc orders frames by filename; renumber into the temp directory
        # so the order cannot depend on how the source names happen to sort
        blank = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 f'<svg xmlns="http://www.w3.org/2000/svg" width="{box[0]}" '
                 f'height="{box[1]}" viewBox="0 0 {box[0]} {box[1]}"></svg>\n')
        for i, src in enumerate(files):
            with open(os.path.join(tmp, f"{i:03d}.svg"), "w") as f:
                f.write(blank if src is None else normalise(open(src).read(), box))

        result = subprocess.run(
            [sys.executable, converter, tmp, "--sequence",
             "--duration", str(frame_ms), "--play_count", "1",
             "-o", os.path.abspath(out_path)],
            capture_output=True, text=True)

    for line in result.stdout.splitlines():
        # the converter warns about coordinates it rounds; harmless
        if "Invalid point" not in line:
            print(line)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit("conversion failed")

    return frame_ms


def verify(path, names, frame_ms, bases=None):
    """Parse the result back, so a broken build fails here rather than showing
    up as a blank corner on the watch."""
    d = open(path, "rb").read()
    if d[0:4] != b"PDCS":
        sys.exit(f"not a sequence: magic is {d[0:4]!r}")

    ver, _res, w, h = struct.unpack("<BBHH", d[8:14])
    play, nframes = struct.unpack("<HH", d[14:18])

    print(f"\n{os.path.basename(path)}: {len(d)} bytes, "
          f"viewbox {w}x{h}, version {ver}, play_count {play}")

    if nframes != len(names):
        sys.exit(f"expected {len(names)} frames, got {nframes}")

    off = 18
    for i in range(nframes):
        dur, ncmd = struct.unpack("<HH", d[off:off + 4])
        if dur != frame_ms:
            sys.exit(f"frame {i} duration is {dur}, expected {frame_ms}")
        o = off + 4
        for _ in range(ncmd):
            _t, _flags, _sc, _sw, _fc = struct.unpack("<BBBBB", d[o:o + 5])
            _radius, npts = struct.unpack("<HH", d[o + 5:o + 9])
            o += 9 + 4 * npts
        if not names[i].startswith("pad"):
            print(f"  frame {i}  {names[i]:<12} {ncmd:>2} commands")
        off = o

    if off != len(d):
        sys.exit(f"trailing bytes: parsed {off} of {len(d)}")

    if bases:
        print("\nfolder bases:")
        for folder, base, count in bases:
            print(f"  {base:>3}  {folder} ({count} frames)")

    print("\nPaste into main.js:\n")
    print(f"const ICON_SET = {frame_ms};   // fingerprint of the icon list")
    for i, name in enumerate(names):
        if not name.startswith("pad"):
            print(f"const I_{name.upper()} = {i};")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Build PDC resources from folders of SVG icons.",
        epilog="examples:\n"
               "  python3 build_icons.py seq weather_40 weather_40.pdc\n"
               "  python3 build_icons.py single markers out/",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", choices=["seq", "single"],
                    help="seq: one sequence, indexed by frame. "
                         "single: one image per SVG, named")
    ap.add_argument("--block", type=int, default=0, metavar="N",
                    help="seq only: pad each folder to a multiple of N frames")
    ap.add_argument("paths", nargs="*", metavar="folder ... output",
                    help="SVG folder(s), then the output file or folder")

    if len(sys.argv) == 1:
        ap.print_help()
        sys.exit(1)

    args = ap.parse_args()
    if not args.mode or len(args.paths) < 2:
        ap.print_help()
        sys.exit("\nneed a mode, at least one folder, and an output")

    *folders, output = args.paths

    here = os.path.dirname(os.path.abspath(__file__))
    resolved = []
    for f in folders:
        d = f if os.path.isabs(f) else os.path.join(os.getcwd(), f)
        if not os.path.isdir(d):
            d = os.path.join(here, f)
        resolved.append(d)

    if args.mode == "single":
        if len(resolved) != 1:
            sys.exit("single mode takes one folder")
        files, names, _ = collect(resolved)
        build_single(files, names, output, here)
    else:
        files, names, bases = collect(resolved, args.block)
        ms = build(files, names, output, here)
        verify(output, names, ms, bases)
