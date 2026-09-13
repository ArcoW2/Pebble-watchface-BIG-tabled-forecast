#!/usr/bin/env python3
"""
Generate the marker icons — one SVG per icon, in two folders.

    python3 gen_marker_icons.py
    python3 build_icons.py single markers  out/
    python3 build_icons.py single activity out/

    markers/    18px  arrows, windsock, compass — the forecast row legends,
                      sitting beside 14px text
    activity/   22px  steps, heart — beside 24px text, and a footprint needs
                      the extra room to read

These are referenced by name exactly once each, so they are built as separate
PDC images rather than frames of a sequence: in C each gets its own
RESOURCE_ID_ICON_* constant, there are no frame numbers to keep in step, and
adding one cannot disturb the others.

    arrowup, arrowdown   forecast max and min rows
    windsock             wind speed row
    compass              wind direction row
    steps, heart         the activity block

Shapes avoid rounded rectangles, which lose their corners in conversion: a
capsule is a rect with a circle at each end instead.
"""

import math
import os

LEGEND_SIZE = 18         # forecast row markers, next to 14px text
ACTIVITY_SIZE = 22       # steps and heart, next to 24px text
HEART = "#FF5555"        # baked in; quantised to the display palette

W = "#FFFFFF"
KNOCKOUT = "#000000"     # must match BG_RGB in main.js: PDC stores a colour per
                         # command, so a "hole" is really a shape painted in the
                         # background colour


def circle(cx, cy, r, fill=W):
    return f'  <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}"/>'


def ring(cx, cy, r, t):
    return (f'  <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="none" '
            f'stroke="{W}" stroke-width="{t:.2f}"/>')


def rect(x, y, w, h, fill=W):
    return (f'  <rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" '
            f'height="{h:.2f}" fill="{fill}"/>')


def seg(x1, y1, x2, y2, t):
    return (f'  <line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{W}" stroke-width="{t:.2f}"/>')


def poly(pts, fill=W):
    s = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return f'  <polygon points="{s}" fill="{fill}"/>'


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


def bar(p1, p2, w):
    """A thick line segment as a quad — a limb.

    No stroke width to rely on for filled shapes, so each limb is its own
    four-point polygon perpendicular to its direction.
    """
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1
    ox, oy = -dy / n * w / 2, dx / n * w / 2
    return poly([(x1 + ox, y1 + oy), (x2 + ox, y2 + oy),
                 (x2 - ox, y2 - oy), (x1 - ox, y1 - oy)])


def steps(S):
    """A walking figure.

    A footprint was tried first at several sizes: its detail — toes, arch —
    merges into stacked blocks on this display. A pedestrian silhouette reads
    from its outline alone, which survives the resolution.
    """
    u = S / 22.0
    P = lambda x, y: (x * u, y * u)

    out = [circle(11.0 * u, 3.4 * u, 2.7 * u)]           # head

    out.append(bar(P(11.2, 6.4), P(10.0, 12.2), 3.2 * u))   # torso

    out.append(bar(P(10.4, 11.8), P(13.6, 15.0), 2.7 * u))  # front thigh
    out.append(bar(P(13.6, 15.0), P(14.6, 19.8), 2.5 * u))  # front shin

    out.append(bar(P(10.4, 11.8), P(7.6, 15.4), 2.7 * u))   # back thigh
    out.append(bar(P(7.6, 15.4), P(6.4, 19.8), 2.5 * u))    # back shin

    out.append(bar(P(11.0, 7.6), P(14.8, 10.0), 2.2 * u))   # leading arm
    out.append(bar(P(11.0, 7.6), P(7.4, 10.8), 2.2 * u))    # trailing arm

    return out


def heart(S):
    """Two lobes over a triangle."""
    r = S * 0.22
    return [circle(S * 0.31, S * 0.34, r, HEART),
            circle(S * 0.69, S * 0.34, r, HEART),
            poly([(S * 0.09, S * 0.40), (S * 0.91, S * 0.40), (S * 0.50, S * 0.90)],
                 HEART)]


LEGENDS = {
    "arrowup":   lambda S: arrow(S, True),
    "arrowdown": lambda S: arrow(S, False),
    "windsock":  lambda S: windsock(S, 1),
    "compass":   compass,
}

ACTIVITY = {
    "steps": steps,
    "heart": heart,
}


def write(folder, size, icons):
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        if f.endswith(".svg"):
            os.remove(os.path.join(folder, f))

    for name, fn in icons.items():
        body = "\n".join(fn(size))
        open(os.path.join(folder, name + ".svg"), "w").write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
            f'height="{size}" viewBox="0 0 {size} {size}">\n{body}\n</svg>\n')

    print(f"{folder}: {len(icons)} icons at {size}px")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    write(os.path.join(here, "markers"), LEGEND_SIZE, LEGENDS)
    write(os.path.join(here, "activity"), ACTIVITY_SIZE, ACTIVITY)
