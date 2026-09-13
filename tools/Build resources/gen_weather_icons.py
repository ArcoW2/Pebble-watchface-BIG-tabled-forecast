#!/usr/bin/env python3
"""
Generate the weather icon SVGs at both sizes.

    python3 gen_weather_icons.py

Writes two folders, both sequences — the code computes the frame index, since
wx_slot() returns an offset within the run:

    weather_40/   40px, the current-conditions icon
    weather_18/   18px, the same icons for the forecast columns

The row legends and activity icons are not here: they are referenced by name
exactly once each, so gen_marker_icons.py writes them as separate images.

drawDCI does not scale, so every size the watch draws needs its own frames.
Both come from the same shape definitions here, so they cannot drift apart.

Frame order is the same in both folders, so one wx_slot() serves either.
"""

import math
import os

W = "#FFFFFF"
KNOCKOUT = "#000000"     # must match BG_RGB in main.js: PDC stores a colour per
                         # command, so a "hole" is really a shape painted in the
                         # background colour


def circle(cx, cy, r, fill=W):
    return f'  <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}"/>'


def ring(cx, cy, r, t):
    return (f'  <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="none" '
            f'stroke="{W}" stroke-width="{t:.2f}"/>')


def rect(x, y, w, h):
    return f'  <rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{W}"/>'


def seg(x1, y1, x2, y2, t):
    return (f'  <line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{W}" stroke-width="{t:.2f}"/>')


def poly(pts):
    s = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return f'  <polygon points="{s}" fill="{W}"/>'


# ---- shapes, all in fractions of the box so they scale ----

def cloud(S, f=1.0, ox=0.0, oy=0.0):
    """Body is a bar capped by two circles: rounded rects lose their corners
    in conversion."""
    u = S / 40.0 * f
    return [
        circle(ox + 8 * u, oy + 24 * u, 6 * u),
        circle(ox + 31 * u, oy + 24 * u, 6 * u),
        rect(ox + 8 * u, oy + 18 * u, 23 * u, 12 * u),
        circle(ox + 14 * u, oy + 18 * u, 8 * u),
        circle(ox + 26 * u, oy + 16 * u, 9 * u),
    ]


def sun(S, cx, cy, r, t, gap, ray=0.45):
    out = []
    for i in range(8):
        a = i * math.pi / 4
        out.append(seg(cx + math.cos(a) * (r + gap), cy + math.sin(a) * (r + gap),
                       cx + math.cos(a) * (r + gap + r * ray),
                       cy + math.sin(a) * (r + gap + r * ray), t))
    out.append(circle(cx, cy, r))
    return out


def flake(S, cx, cy, r):
    """fill=none plus a stroke gives a ring, so the centre needs no knockout."""
    out = [ring(cx, cy, r * 2 / 3, max(1.0, r * 0.32))]
    for k in range(3):
        a = k * math.pi / 3
        out.append(seg(cx - math.cos(a) * r, cy - math.sin(a) * r,
                       cx + math.cos(a) * r, cy + math.sin(a) * r,
                       max(1.0, r * 0.22)))
    return out


def crescent(cx, cy, R, dx, dy, Ri):
    """A white disc with a background-coloured disc over it.

    PDC has no subtract, but it does store a colour per command, so the bite is
    simply painted in KNOCKOUT. Two commands and a true circle, against a
    45-point polygon when the boundary was sampled instead. The cost is that
    the icon only composites correctly over that background colour.
    """
    return [circle(cx, cy, R),
            circle(cx + dx, cy + dy, Ri, KNOCKOUT)]


def windsock(S, bands=3):
    """Pole, a ridge where the sleeve is hooped on, then the sleeve tapering
    right. Alternate segments are dropped, which reads as stripes in one
    colour; an odd count starts and ends filled."""
    segments = bands * 2 - 1
    poleW = max(1.5, S * 0.07)
    poleX = S * 0.08
    out = [rect(poleX, S * 0.08, poleW, S * 0.86)]

    hMouth, hTip, yTop = S * 0.46, S * 0.22, S * 0.16
    ridgeW = max(1.5, S * 0.05)
    out.append(rect(poleX + poleW, yTop - S * 0.05, ridgeW, hMouth + S * 0.10))

    x0 = poleX + poleW + ridgeW
    x1 = S * 0.94
    for i in range(segments):
        if i % 2:
            continue
        fa, fb = i / segments, (i + 1) / segments
        xa, xb = x0 + (x1 - x0) * fa, x0 + (x1 - x0) * fb
        ha = hMouth + (hTip - hMouth) * fa
        hb = hMouth + (hTip - hMouth) * fb
        out.append(poly([(xa, yTop + (hMouth - ha) / 2),
                         (xb, yTop + (hMouth - hb) / 2),
                         (xb, yTop + (hMouth + hb) / 2),
                         (xa, yTop + (hMouth + ha) / 2)]))
    return out


def arrow(S, up):
    """Chevron over a stem. A filled triangle would need one fill per scanline
    when drawn in code; as a polygon here it is one command."""
    t = max(1.5, S * 0.16)
    cx = S / 2
    tip = S * 0.12 if up else S * 0.88
    arm = S * 0.44 if up else S * 0.56
    return [
        seg(cx, tip, S * 0.24, arm, t),
        seg(cx, tip, S * 0.76, arm, t),
        rect(cx - t / 2, S * 0.12, t, S * 0.76),
    ]


def compass(S):
    """Wind direction marker: a needle inside a ring."""
    t = max(1.0, S * 0.09)
    cx = cy = S / 2
    r = S * 0.40
    return [
        ring(cx, cy, r, t),
        poly([(cx, cy - r * 0.72), (cx + r * 0.34, cy + r * 0.30),
              (cx, cy + r * 0.10), (cx - r * 0.34, cy + r * 0.30)]),
    ]
def build_set(S, fog_bands, sock_bands):
    u = S / 40.0
    return {
        "cloud":     cloud(S),
        "sun":       sun(S, S / 2, S / 2, 10 * u, max(1.5, 3 * u), 2.5 * u),
        "partly":    sun(S, 13 * u, 11 * u, 6 * u, max(1.2, 2 * u), 2.0 * u, 0.40)
                     + cloud(S, 0.86, 4 * u, 7.2 * u),
        "rain":      cloud(S, 0.94, 0, -2.4 * u)
                     + [seg((11.2 + i * 8.8) * u, 29.6 * u,
                            (7.2 + i * 8.8) * u, 38.4 * u, max(1.2, 3 * u))
                        for i in range(3)],
        "snow":      cloud(S, 0.70, 0, 0.8 * u) + flake(S, 28 * u, 27.2 * u, 10.4 * u),
        "thunder":   cloud(S, 0.90, 0, -4 * u)
                     + [seg(23.2 * u, 21.6 * u, 15.2 * u, 28.8 * u, max(1.2, 3 * u)),
                        seg(15.2 * u, 28.8 * u, 22.4 * u, 28.8 * u, max(1.2, 3 * u)),
                        seg(22.4 * u, 28.8 * u, 14.4 * u, 36 * u, max(1.2, 3 * u))],
        "fog":       [rect(S * (0.10 if i % 2 else 0.04),
                           S * (0.14 + i * (0.76 / (fog_bands - 1))),
                           S * (0.80 if i % 2 else 0.88),
                           max(1.5, S * (0.10 if fog_bands <= 3 else 0.07)))
                      for i in range(fog_bands)],
        "moon":      crescent(S / 2, S / 2, 15.2 * u, 7.9 * u, -4.6 * u, 13.4 * u),
        "arrowup":   arrow(S, True),
        "arrowdown": arrow(S, False),
        "windsock":  windsock(S, sock_bands),
        "compass":   compass(S),
    }


# name -> position. Weather icons keep the same indices in both sets, so one
# wxSlot() serves the top-left icon and the forecast columns.
ORDER = ["cloud", "sun", "partly", "rain", "snow", "thunder", "fog", "moon",
         "arrowup", "arrowdown", "windsock", "compass"]

WEATHER_ONLY = ORDER[:8]

# name -> position within a weather run. wxSlot() in main.js returns an offset
# into this order, so the two sets must list the same names in the same order.
ORDER = ["cloud", "sun", "partly", "rain", "snow", "thunder", "fog", "moon",
         "arrowup", "arrowdown", "windsock", "compass"]

WEATHER_ONLY = ORDER[:8]


def write(folder, S, names, prefix, fog_bands, sock_bands, box):
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        if f.endswith(".svg"):
            os.remove(os.path.join(folder, f))

    shapes = build_set(S, fog_bands, sock_bands)
    for i, name in enumerate(names):
        body = "\n".join(shapes[name])
        open(os.path.join(folder, f"{i * 10:03d}_{prefix}{name}.svg"), "w").write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{box}" '
            f'height="{box}" viewBox="0 0 {box} {box}">\n{body}\n</svg>\n')

    print(f"{folder}: {len(names)} frames at {S}px")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))

    write(os.path.join(here, "weather_40"), 40, WEATHER_ONLY, "",
          fog_bands=5, sock_bands=3, box=40)

    # fewer fog bands at the small size; the wider ones merge
    write(os.path.join(here, "weather_18"), 18, WEATHER_ONLY, "",
          fog_bands=3, sock_bands=1, box=18)
