# Watchface icons — sources and build

Icons are drawn from parameterised Python, written out as SVG, and converted to
PDC. Two shapes of output, for two different jobs.

## Sequences, for indexed icons

    python3 gen_weather_icons.py
    python3 build_icons.py seq weather_40 weather_40.pdc
    python3 build_icons.py seq weather_18 weather_18.pdc

The weather icons are chosen by computation — `wx_slot()` maps a WMO code to an
offset — so an index is what the code wants. Frame order is the filename order,
fixed by the numeric prefix, and identical in both folders so one lookup serves
either size.

Two sizes because a PDC draws at the size it was built: 40px for the current
conditions, 18px for the forecast columns. `gdraw_command_frame_draw` does not
scale.

## Single images, for named icons

    python3 gen_marker_icons.py
    python3 build_icons.py single markers out/

The row legends and activity icons are each referenced once, by name. As
separate images they get their own `RESOURCE_ID_ICON_*` constants — no frame
numbers to keep in step with the code, and adding one cannot disturb the
others.

Both modes print the `package.json` media entries and the matching C to paste.

## What lives where

| folder | output | used for |
|---|---|---|
| `weather_40/` | `weather_40.pdc` | current conditions, 40px |
| `weather_18/` | `weather_18.pdc` | forecast columns, 18px |
| `markers/` | one .pdc each | arrows, windsock, compass, steps, heart |

The LCD digits are not here. They are drawn from segments in `main.c`, which
keeps thickness, chamfer and gap adjustable without regenerating anything.

## Editing

Edit the Python, not the SVGs — every run deletes and rewrites the folders. The
two weather sizes come from one set of shape definitions, so they cannot drift
apart.

## Converter notes

`svg2pdc.py` is Pebble's own tool. Three changes were needed to run it:

1. It needs `pebble_image_routines.py` beside it (included).
2. `pack('H', self.radius)` receives a float under Python 3 — patched to
   `int(round(...))`.
3. `serialize_sequence` builds its header as `str` and concatenates `bytes` —
   patched to build it as bytes throughout.

Supported elements: `g`, `layer`, `path`, `rect`, `polyline`, `polygon`,
`line`, `circle`. Warnings about "Invalid point" are the converter rounding to
coordinates the format can represent, and are harmless.

## Drawing constraints learned building these

- Rounded rectangles lose their corners, so a capsule is a rect with a circle
  at each end, and the cloud body is a rect with a circle at each end too.
- There is no subtract. The crescent moon is a white disc with a
  background-coloured disc painted over it — which means it only composites
  correctly over that background.
- `fill="none"` plus a stroke gives a ring, which is how the snowflake centre
  is drawn without a knockout.
- Colours are baked in and quantised to the display palette. In C they can be
  changed at runtime with `gdraw_command_set_fill_color` over the command list,
  which is the route if icons should follow a theme.
- Filled triangles cost one command as a polygon here, against one
  `graphics_fill_rect` per scanline when drawn in code.
