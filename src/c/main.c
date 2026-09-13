/*
 * Weather Dashboard — Pebble Time 2 (emery, 200x228)
 *
 *   battery bar
 *   [icon]   temp / wind        steps / heart
 *   HH:MM   LCD digits drawn from segments
 *   place
 *   forecast grid: legend column + one column per day
 *
 * All network and location work happens in PKJS. This side receives a place
 * string and one packed weather string over AppMessage.
 *
 * Icons come from a single PDC sequence, one icon per frame. The digits are
 * drawn from segments rather than loaded, so their colour and geometry stay
 * adjustable here.
 */

#include <pebble.h>

/* ==================================================================
 * ICONS
 * ==================================================================
 * Two kinds, for two reasons.
 *
 * The weather icons are sequences: wx_slot() computes an offset, so an
 * index is what the code wants. Two sets, since a PDC draws at the size
 * it was built — 40px for the current conditions, 18px for the grid.
 *
 * The markers are separate images: each is referenced by name exactly
 * once, so a frame number would be indirection for nothing. Adding one
 * cannot disturb the others.
 *
 *     python3 gen_weather_icons.py
 *     python3 gen_marker_icons.py
 *     python3 build_icons.py seq    weather_40 weather_40.pdc
 *     python3 build_icons.py seq    weather_18 weather_18.pdc
 *     python3 build_icons.py single markers    out/
 * ================================================================== */

/* ---------- layout ---------- */

#define PAD            4
#define BAT_H          4

#define DIG_W         40        /* one digit */
#define DIG_H         60
#define SEG_T          8        /* segment thickness, and so the chamfer depth */
#define GAP            1        /* per-end inset; the visible seam is twice this */
#define SPACING        4
#define COLON_W       10
#define COLON_DOT      7

#define YMID    (DIG_H / 2)
#define YG      (YMID - SEG_T / 2)
#define X_R     (DIG_W - SEG_T)
#define CLOCK_W (DIG_W * 4 + COLON_W + SPACING * 4)

#define AMPM_H        18        /* the AM/PM label, bottom-aligned with the digits */
#define AMPM_GAP       3        /* between the label and the first digit */

#define CLOCK_TOP     49        /* clock's top edge, measured from the top of
                                   the screen — an absolute position rather
                                   than an offset from centre, so raising it
                                   gives the forecast grid the space */
#define PLACE_GAP     -3
#define DATE_DROP      0        /* same font as the city, so no offset needed */        /* negative: tuck the city under the digits */
#define WX_ICON       40        /* current-conditions icon box, top left */
#define WX_TEXT_GAP    4        /* between that icon and the lines beside it */
#define GRID_ICON     18        /* forecast row legends */
#define ACT_ICON      22        /* steps and heart, beside larger text */
#define TEXT_LIFT      4        /* graphics_draw_text leaves ascender padding
                                   above the glyphs; pull the rect up by this */
#define ROW2_LIFT      2        /* the second line of the top band only: the
                                   icons beside it stay where they are */
#define PLACE_LIFT     1        /* the city and date line: Roboto Condensed has
                                   different ascender padding from Gothic, so
                                   it needs its own value */
#define ACT_W         74        /* reserved width of the activity block */

#define DAYS           5        /* forecast columns */
#define LEG_W         22        /* legend column width */
#define GRID_ROW      14        /* a text row: the font height, no padding */
#define GRID_RULE      2        /* the line under the header */
#define ROW_GAP        1

/* header + rule + max + min + icons + wind + direction */
#define GRID_H  (GRID_ROW * 5 + GRID_RULE + GRID_ICON + ROW_GAP)

#define NIGHT_FROM    21        /* clear sky draws the moon from this hour */
#define NIGHT_TO       6

#define SHOW_GHOST   true       /* unlit segments */

/* Custom font for the city and date line.
 *
 * The system set has one condensed face, Roboto Condensed 21, and nothing
 * narrower. For a narrower line, add a TTF under Resources:
 *
 *   type        font
 *   identifier  FONT_PLACE_CONDENSED_SUBSET_23
 *   file        Calvines-Regular.ttf
 *
 * The trailing number in the identifier is not decoration: it sets the size
 * the font is rasterised at. One resource per size, so the same TTF at two
 * sizes is two entries with two identifiers.
 *
 * SUBSET is a convention for a font trimmed with a character regex, which
 * CloudPebble offers when adding the resource. That saves flash, not width.
 *
 * The C constant is RESOURCE_ID_ plus the identifier verbatim — so the example
 * above gives RESOURCE_ID_FONT_PLACE_CONDENSED_SUBSET_23, which is what
 * PLACE_FONT_ID is set to.
 *
 * Fonts are flash, not RAM, so this costs nothing that is scarce. A custom
 * font must be unloaded again — see deinit().
 */
#define USE_PLACE_FONT   1      /* 0 = system Roboto Condensed 21 */
#define PLACE_FONT_ID    RESOURCE_ID_FONT_PLACE_CONDENSED_SUBSET_23

/* ---------- colours ---------- */

#define COL_BG      GColorBlack
#define COL_ON      GColorWhite
#define COL_GHOST   GColorFromHEX(0x151515)   /* quantised by the display */
#define COL_ACT     GColorFromHEX(0x55aaff)
#define COL_HR      GColorFromHEX(0xff5566)
#define COL_WARN    GColorFromHEX(0xffcc00)
#define COL_CRIT    GColorFromHEX(0xff4444)

/* ---------- state ---------- */

static Window *s_window;
static Layer *s_layer;

static GFont s_font_text;       /* place line and activity */
static GFont s_font_grid;
static GFont s_font_ampm;
static GFont s_font_place;   /* condensed: the city and date share one line */

static GDrawCommandSequence *s_wx40;    /* current conditions */
static GDrawCommandSequence *s_wx18;    /* forecast columns */

static GDrawCommandImage *s_ic_arrowup;
static GDrawCommandImage *s_ic_arrowdown;
static GDrawCommandImage *s_ic_windsock;
static GDrawCommandImage *s_ic_compass;
static GDrawCommandImage *s_ic_steps;
static GDrawCommandImage *s_ic_heart;

static struct tm s_now;

static char s_place[32] = "";
static char s_temp[8] = "";
static char s_wind[12] = "";
static char s_steps[8] = "--";
static char s_heart[8] = "--";
static char s_month[4] = "";
static char s_date[16] = "";

static int s_cur_code = -1;
static bool s_have_wx = false;

/* forecast, one entry per day */
static int s_fc_code[DAYS];
static char s_fc_day[DAYS][4];
static char s_fc_max[DAYS][6];
static char s_fc_min[DAYS][6];
static char s_fc_wind[DAYS][6];
static char s_fc_dir[DAYS][4];
static int s_fc_days = 0;

static const char *COMPASS[] = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
static const char *MONTHS[] = { "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };

/* ==================================================================
 * helpers
 * ================================================================== */

static const char *compass(int deg) {
  int i = ((deg % 360) + 360) % 360;
  return COMPASS[((i + 22) / 45) % 8];
}

/* WMO code -> offset within a weather run: cloud, sun, partly, rain, snow,
   thunder, fog, moon. The same order in both weather sequences, so one lookup
   serves the 40px icon and the 18px grid columns. */
static int wx_slot(int code, bool night) {
  if (code == 0) return night ? 7 : 1;                    /* clear sky */
  if (code <= 2) return 2;                                /* partly */
  if (code == 3) return 0;                                /* overcast */
  if (code == 45 || code == 48) return 6;                 /* fog */
  if (code >= 51 && code <= 67) return 3;                 /* drizzle, rain */
  if (code >= 80 && code <= 82) return 3;                 /* showers */
  if (code >= 71 && code <= 77) return 4;                 /* snowfall */
  if (code == 85 || code == 86) return 4;                 /* snow showers */
  if (code >= 95) return 5;                               /* thunderstorm */
  return 0;
}

static bool is_night(void) {
  return s_now.tm_hour >= NIGHT_FROM || s_now.tm_hour < NIGHT_TO;
}

/* one frame of a sequence, chosen by index */
static void draw_wx(GContext *ctx, GDrawCommandSequence *seq,
                    int slot, int x, int y) {
  if (!seq) return;
  GDrawCommandFrame *frame = gdraw_command_sequence_get_frame_by_index(seq, slot);
  if (frame) gdraw_command_frame_draw(ctx, seq, frame, GPoint(x, y));
}

/* a standalone image, by name */
static void draw_marker(GContext *ctx, GDrawCommandImage *img, int x, int y) {
  if (img) gdraw_command_image_draw(ctx, img, GPoint(x, y));
}

static void draw_text_in(GContext *ctx, const char *text, GFont font,
                         int x, int y, int w, int h, GTextAlignment align) {
  graphics_draw_text(ctx, text, font, GRect(x, y, w, h),
                     GTextOverflowModeTrailingEllipsis, align, NULL);
}

/* ==================================================================
 * LCD digits
 * ==================================================================
 * Segments interlock: each one's outer edge is square and full length, and
 * only the edges facing a neighbour are chamfered at 45 degrees. GAP opens a
 * hairline between them. The middle bar is a chevron at both ends, so its base
 * inset is about half the thickness; outboard of that chevron tip there is no
 * middle bar and the verticals meet each other at the midline.
 * ================================================================== */

/* mode 0 = top bar, 1 = bottom bar, 2 = middle bar */
static void hbar(GContext *ctx, int x, int y, int mode) {
  for (int j = 0; j < SEG_T; j++) {
    int ins;
    if (mode == 0) ins = j;
    else if (mode == 1) ins = SEG_T - 1 - j;
    else ins = (SEG_T - j > j + 1) ? SEG_T - j : j + 1;
    ins += GAP;
    int len = DIG_W - 2 * ins;
    if (len > 0)
      graphics_fill_rect(ctx, GRect(x + ins, y + j, len, 1), 0, GCornerNone);
  }
}

/* side 0 = left, 1 = right. half 0 = upper, 1 = lower */
static void vbar(GContext *ctx, int x, int y, int side, int half) {
  for (int i = 0; i < SEG_T; i++) {
    int k = side ? SEG_T - 1 - i : i;
    int top, bot;
    if (half) {
      top = y + YG + k;
      if (top < y + YMID) top = y + YMID;
      bot = y + DIG_H - 2 - k;
    } else {
      top = y + k + 1;
      bot = y + YG + SEG_T - 1 - k;
      if (bot > y + YMID - 1) bot = y + YMID - 1;
    }
    top += GAP;
    bot -= GAP;
    if (bot >= top)
      graphics_fill_rect(ctx, GRect(x + i, top, 1, bot - top + 1), 0, GCornerNone);
  }
}

/* bit order: a b c d e f g */
static const uint8_t SEGS[] = { 0x3f, 0x06, 0x5b, 0x4f, 0x66,
                                0x6d, 0x7d, 0x07, 0x7f, 0x6f };

static void seg_color(GContext *ctx, uint8_t mask, uint8_t bit) {
  graphics_context_set_fill_color(ctx, (mask & bit) ? COL_ON : COL_GHOST);
}

static void draw_digit(GContext *ctx, int n, int x, int y) {
  uint8_t m = SEGS[n];

  if (SHOW_GHOST || (m & 0x01)) { seg_color(ctx, m, 0x01); hbar(ctx, x, y, 0); }
  if (SHOW_GHOST || (m & 0x08)) { seg_color(ctx, m, 0x08); hbar(ctx, x, y + DIG_H - SEG_T, 1); }
  if (SHOW_GHOST || (m & 0x40)) { seg_color(ctx, m, 0x40); hbar(ctx, x, y + YG, 2); }

  if (SHOW_GHOST || (m & 0x20)) { seg_color(ctx, m, 0x20); vbar(ctx, x, y, 0, 0); }
  if (SHOW_GHOST || (m & 0x02)) { seg_color(ctx, m, 0x02); vbar(ctx, x + X_R, y, 1, 0); }
  if (SHOW_GHOST || (m & 0x10)) { seg_color(ctx, m, 0x10); vbar(ctx, x, y, 0, 1); }
  if (SHOW_GHOST || (m & 0x04)) { seg_color(ctx, m, 0x04); vbar(ctx, x + X_R, y, 1, 1); }
}

/* In twelve-hour mode the tens place is only ever blank or a one, so only the
   two right-hand segments exist there. Drawing a full digit would ghost all
   seven and read as an eight waiting to happen. */
static void draw_leading_one(GContext *ctx, int x, int y, bool lit) {
  if (!lit && !SHOW_GHOST) return;
  graphics_context_set_fill_color(ctx, lit ? COL_ON : COL_GHOST);
  vbar(ctx, x + X_R, y, 1, 0);
  vbar(ctx, x + X_R, y, 1, 1);
}

static void draw_colon(GContext *ctx, int x, int y) {
  int cx = x + (COLON_W - COLON_DOT) / 2;
  int q = DIG_H / 4;
  graphics_context_set_fill_color(ctx, COL_ON);
  graphics_fill_rect(ctx, GRect(cx, y + q - COLON_DOT / 2, COLON_DOT, COLON_DOT),
                     0, GCornerNone);
  graphics_fill_rect(ctx, GRect(cx, y + DIG_H - q - COLON_DOT / 2, COLON_DOT, COLON_DOT),
                     0, GCornerNone);
}

/* ==================================================================
 * parsing
 * ==================================================================
 * "code,temp,wind,dir|code,max,min,wind,dir|..." — the current block first,
 * then one block per forecast day. Walked character by character, so no
 * tokenising buffers are needed.
 * ================================================================== */

static void parse_wx(const char *str) {
  int val = 0, field = 0, block = 0;
  bool neg = false;
  int cur[4] = { 0, 0, 0, 0 };
  int day[5] = { 0, 0, 0, 0, 0 };

  s_fc_days = 0;

  for (const char *p = str; ; p++) {
    char ch = *p ? *p : '|';         /* the terminator flushes the last field */

    if (ch >= '0' && ch <= '9') { val = val * 10 + (ch - '0'); continue; }
    if (ch == '-') { neg = true; continue; }

    int v = neg ? -val : val;

    if (block == 0) {
      if (field < 4) cur[field] = v;
    } else if (block <= DAYS && field < 5) {
      day[field] = v;
    }

    val = 0;
    neg = false;
    field++;

    if (ch == '|') {
      if (block == 0) {
        s_cur_code = cur[0];
        snprintf(s_temp, sizeof(s_temp), "%d\xC2\xB0", cur[1]);
        snprintf(s_wind, sizeof(s_wind), "%d %s", cur[2], compass(cur[3]));
        s_have_wx = true;
      } else if (block <= DAYS && field >= 5) {
        int i = block - 1;
        s_fc_code[i] = day[0];
        snprintf(s_fc_max[i], sizeof(s_fc_max[i]), "%d", day[1]);
        snprintf(s_fc_min[i], sizeof(s_fc_min[i]), "%d", day[2]);
        snprintf(s_fc_wind[i], sizeof(s_fc_wind[i]), "%d", day[3]);
        snprintf(s_fc_dir[i], sizeof(s_fc_dir[i]), "%s", compass(day[4]));
        s_fc_days = block;
      }
      block++;
      field = 0;
    }

    if (!*p) break;
  }
}

/* day-of-month labels and the month name, rebuilt when the date rolls over */
static void format_dates(void) {
  snprintf(s_month, sizeof(s_month), "%s", MONTHS[s_now.tm_mon]);
  snprintf(s_date, sizeof(s_date), "%d %s'%02d",
           s_now.tm_mday, MONTHS[s_now.tm_mon], (1900 + s_now.tm_year) % 100);

  /* lowercase in place rather than keeping a second month table; the grid
     header wants the capitalised form from MONTHS */
  for (char *c = s_date; *c; c++)
    if (*c >= 'A' && *c <= 'Z') *c += 'a' - 'A';

  time_t t = time(NULL);
  for (int i = 0; i < DAYS; i++) {
    time_t d = t + i * 86400;
    struct tm *tm = localtime(&d);
    snprintf(s_fc_day[i], sizeof(s_fc_day[i]), "%d", tm->tm_mday);
  }
}

/* ==================================================================
 * sensors
 * ================================================================== */

static void read_activity(void) {
  HealthServiceAccessibilityMask steps_ok = health_service_metric_accessible(
      HealthMetricStepCount, time_start_of_today(), time(NULL));

  if (steps_ok & HealthServiceAccessibilityMaskAvailable) {
    int n = (int)health_service_sum_today(HealthMetricStepCount);
    if (n >= 10000)
      snprintf(s_steps, sizeof(s_steps), "%d.%dk", n / 1000, (n % 1000) / 100);
    else
      snprintf(s_steps, sizeof(s_steps), "%d", n);
  }

  /* peek_current_value returns 0 when there is no recent reading; keep the
     last good one rather than flicking back to dashes */
  int hr = (int)health_service_peek_current_value(HealthMetricHeartRateBPM);
  if (hr > 0) snprintf(s_heart, sizeof(s_heart), "%d", hr);
}

/* ==================================================================
 * drawing
 * ================================================================== */

static int clock_top(void) {
  return CLOCK_TOP;
}

static void draw_battery(GContext *ctx, int w) {
  BatteryChargeState b = battery_state_service_peek();

  graphics_context_set_fill_color(ctx, GColorDarkGray);
  graphics_fill_rect(ctx, GRect(0, 0, w, BAT_H), 0, GCornerNone);

  GColor c = COL_ACT;
  if (b.is_charging || b.is_plugged) c = GColorGreen;
  else if (b.charge_percent <= 10) c = COL_CRIT;
  else if (b.charge_percent <= 25) c = COL_WARN;

  graphics_context_set_fill_color(ctx, c);
  graphics_fill_rect(ctx, GRect(0, 0, w * b.charge_percent / 100, BAT_H),
                     0, GCornerNone);
}

static void draw_time(GContext *ctx, int w) {
  int y = clock_top();

  /* right-aligned rather than centred, so the digits end on the same pixel as
     the date below them */
  int x = w - PAD - CLOCK_W;

  bool h24 = clock_is_24h_style();
  int hour = s_now.tm_hour;

  if (h24) {
    draw_digit(ctx, hour / 10, x, y);
  } else {
    int h12 = hour % 12;
    if (h12 == 0) h12 = 12;

    draw_leading_one(ctx, x, y, h12 >= 10);

    /* The label sits on the digits' baseline. It can run under the tens place:
       a one occupies only the rightmost X_R..DIG_W of that cell, so everything
       left of X_R is empty and there is room for the text there. */
    graphics_context_set_text_color(ctx, COL_ON);
    draw_text_in(ctx, hour < 12 ? "AM" : "PM", s_font_ampm,
                 PAD, y + DIG_H - AMPM_H - TEXT_LIFT,
                 x + X_R - AMPM_GAP - PAD, AMPM_H + TEXT_LIFT,
                 GTextAlignmentRight);

    hour = h12;
  }

  x += DIG_W + SPACING;
  draw_digit(ctx, hour % 10, x, y);
  x += DIG_W + SPACING;
  draw_colon(ctx, x, y);
  x += COLON_W + SPACING;
  draw_digit(ctx, s_now.tm_min / 10, x, y);
  x += DIG_W + SPACING;
  draw_digit(ctx, s_now.tm_min % 10, x, y);
}

/* City on the left, date on the right, sharing a line.

   Both use Roboto Condensed 21 and the date is abbreviated to "11 sep'26", so
   the pair fits the 192px line where Gothic 24 and a full year did not. */
static void draw_place(GContext *ctx, int w) {
  int y = clock_top() + DIG_H + PLACE_GAP - PLACE_LIFT;

  graphics_context_set_text_color(ctx, COL_ON);

  if (s_place[0])
    draw_text_in(ctx, s_place, s_font_place, PAD, y,
                 w - PAD * 2, 26 + PLACE_LIFT, GTextAlignmentLeft);

  draw_text_in(ctx, s_date, s_font_place, PAD, y + DATE_DROP,
               w - PAD * 2, 26 + PLACE_LIFT, GTextAlignmentRight);
}

static void draw_activity(GContext *ctx, int w) {
  int line_h = ACT_ICON - 2;   /* icons nearly touch; text does not */
  int icon_x = w - PAD - ACT_ICON;
  int text_r = icon_x - 4;
  int y = BAT_H + 2;

  graphics_context_set_text_color(ctx, COL_ACT);

  draw_text_in(ctx, s_steps, s_font_text, PAD, y - TEXT_LIFT,
               text_r - PAD, line_h + TEXT_LIFT, GTextAlignmentRight);
  draw_marker(ctx, s_ic_steps, icon_x, y);

  draw_text_in(ctx, s_heart, s_font_text, PAD, y + line_h - TEXT_LIFT - ROW2_LIFT,
               text_r - PAD, line_h + TEXT_LIFT, GTextAlignmentRight);
  draw_marker(ctx, s_ic_heart, icon_x, y + line_h);
}

static void draw_weather(GContext *ctx, int w) {
  if (!s_have_wx) return;

  draw_wx(ctx, s_wx40, wx_slot(s_cur_code, is_night()), PAD, BAT_H + 2);

  /* left-aligned against the icon rather than centred in the gap, so the two
     lines share an edge with each other and with the icon beside them */
  int left = PAD + WX_ICON + WX_TEXT_GAP;
  int right = w - ACT_W;

  graphics_context_set_text_color(ctx, COL_ON);
  draw_text_in(ctx, s_temp, s_font_text, left, BAT_H + 2 - TEXT_LIFT,
               right - left, 28, GTextAlignmentLeft);
  draw_text_in(ctx, s_wind, s_font_text, left, BAT_H + 24 - TEXT_LIFT - ROW2_LIFT,
               right - left, 28, GTextAlignmentLeft);
}

static void grid_cell(GContext *ctx, const char *text, int col, int col_w, int y) {
  draw_text_in(ctx, text, s_font_grid, PAD + LEG_W + col * col_w,
               y - TEXT_LIFT, col_w, GRID_ROW + TEXT_LIFT, GTextAlignmentCenter);
}

static int grid_row(GContext *ctx, int y, GDrawCommandImage *marker,
                    int leg_x, int col_w, char values[][6]) {
  draw_marker(ctx, marker, leg_x, y - (GRID_ICON - GRID_ROW) / 2);
  for (int i = 0; i < s_fc_days; i++) grid_cell(ctx, values[i], i, col_w, y);
  return y + GRID_ROW;
}

/*
 *   Sep | 11 | 12 | 13 | 14      header: month, then day of month
 *   ----+----+----+----+----     rule
 *    up | 19 | 21 | 18 | 20      max
 *  down |  9 | 11 |  8 | 10      min
 *  icon |    |    |    |         conditions
 *  sock | 10 | 16 | 14 | 17      wind speed
 *  comp | SW |  W | NW |  W      wind direction
 */
static void draw_forecast(GContext *ctx, int w, int h) {
  if (!s_fc_days) return;

  int col_w = (w - PAD * 2 - LEG_W) / DAYS;
  int leg_x = PAD + (LEG_W - GRID_ICON) / 2;

  int y = h - PAD - GRID_H;

  graphics_context_set_text_color(ctx, COL_ON);
  /* same lift as the day numbers beside it, or it sits lower than they do */
  draw_text_in(ctx, s_month, s_font_grid, PAD, y - TEXT_LIFT, LEG_W,
               GRID_ROW + TEXT_LIFT, GTextAlignmentLeft);
  for (int i = 0; i < s_fc_days; i++) grid_cell(ctx, s_fc_day[i], i, col_w, y);
  y += GRID_ROW;

  graphics_context_set_fill_color(ctx, COL_ON);
  graphics_fill_rect(ctx, GRect(PAD, y, w - PAD * 2, 1), 0, GCornerNone);
  y += GRID_RULE;

  graphics_context_set_text_color(ctx, COL_ON);
  y = grid_row(ctx, y, s_ic_arrowup, leg_x, col_w, s_fc_max);
  y = grid_row(ctx, y, s_ic_arrowdown, leg_x, col_w, s_fc_min);

  draw_wx(ctx, s_wx18, 0, leg_x, y);   /* cloud, as the row marker */
  for (int i = 0; i < s_fc_days; i++)
    draw_wx(ctx, s_wx18, wx_slot(s_fc_code[i], false),
            PAD + LEG_W + i * col_w + (col_w - GRID_ICON) / 2, y);
  y += GRID_ICON + ROW_GAP;

  y = grid_row(ctx, y, s_ic_windsock, leg_x, col_w, s_fc_wind);

  draw_marker(ctx, s_ic_compass, leg_x, y - (GRID_ICON - GRID_ROW) / 2);
  for (int i = 0; i < s_fc_days; i++) grid_cell(ctx, s_fc_dir[i], i, col_w, y);
}

static void update_proc(Layer *layer, GContext *ctx) {
  GRect b = layer_get_bounds(layer);

  graphics_context_set_fill_color(ctx, COL_BG);
  graphics_fill_rect(ctx, b, 0, GCornerNone);

  draw_battery(ctx, b.size.w);
  draw_weather(ctx, b.size.w);
  draw_activity(ctx, b.size.w);
  draw_time(ctx, b.size.w);
  draw_place(ctx, b.size.w);
  draw_forecast(ctx, b.size.w, b.size.h);
}

/* ==================================================================
 * events
 * ================================================================== */

static void tick_handler(struct tm *tick, TimeUnits units) {
  int prev_day = s_now.tm_mday;
  s_now = *tick;

  if (s_now.tm_mday != prev_day) format_dates();

  read_activity();
  layer_mark_dirty(s_layer);
}

static void inbox_received(DictionaryIterator *iter, void *context) {
  Tuple *t;

  t = dict_find(iter, MESSAGE_KEY_PLACE);
  if (t && t->type == TUPLE_CSTRING) {
    snprintf(s_place, sizeof(s_place), "%s", t->value->cstring);
    persist_write_string(MESSAGE_KEY_PLACE, s_place);
  }

  t = dict_find(iter, MESSAGE_KEY_WX);
  if (t && t->type == TUPLE_CSTRING) {
    parse_wx(t->value->cstring);
    persist_write_string(MESSAGE_KEY_WX, t->value->cstring);
  }

  layer_mark_dirty(s_layer);
}

/* ==================================================================
 * lifecycle
 * ================================================================== */

static void load_cache(void) {
  if (persist_exists(MESSAGE_KEY_PLACE))
    persist_read_string(MESSAGE_KEY_PLACE, s_place, sizeof(s_place));

  if (persist_exists(MESSAGE_KEY_WX)) {
    char buf[128];
    persist_read_string(MESSAGE_KEY_WX, buf, sizeof(buf));
    parse_wx(buf);
  }
}

static void window_load(Window *window) {
  Layer *root = window_get_root_layer(window);
  s_layer = layer_create(layer_get_bounds(root));
  layer_set_update_proc(s_layer, update_proc);
  layer_add_child(root, s_layer);
}

static void window_unload(Window *window) {
  layer_destroy(s_layer);
}

static void init(void) {
  s_font_text = fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD);
  s_font_grid = fonts_get_system_font(FONT_KEY_GOTHIC_14_BOLD);
  s_font_ampm = fonts_get_system_font(FONT_KEY_GOTHIC_18_BOLD);

#if USE_PLACE_FONT
  s_font_place = fonts_load_custom_font(resource_get_handle(PLACE_FONT_ID));
#else
  /* Roboto Condensed is the one narrow face in the system set: nearly the
     height of Gothic 24 in appreciably less width, which is what lets the city
     and the date share a 192px line. */
  s_font_place = fonts_get_system_font(FONT_KEY_ROBOTO_CONDENSED_21);
#endif

  s_wx40 = gdraw_command_sequence_create_with_resource(RESOURCE_ID_WEATHER_40);
  s_wx18 = gdraw_command_sequence_create_with_resource(RESOURCE_ID_WEATHER_18);

  s_ic_arrowup = gdraw_command_image_create_with_resource(RESOURCE_ID_ICON_ARROWUP);
  s_ic_arrowdown = gdraw_command_image_create_with_resource(RESOURCE_ID_ICON_ARROWDOWN);
  s_ic_windsock = gdraw_command_image_create_with_resource(RESOURCE_ID_ICON_WINDSOCK);
  s_ic_compass = gdraw_command_image_create_with_resource(RESOURCE_ID_ICON_COMPASS);
  s_ic_steps = gdraw_command_image_create_with_resource(RESOURCE_ID_ICON_STEPS);
  s_ic_heart = gdraw_command_image_create_with_resource(RESOURCE_ID_ICON_HEART);

  if (!s_wx40 || !s_wx18) APP_LOG(APP_LOG_LEVEL_ERROR, "weather icons missing");
  if (!s_ic_steps || !s_ic_heart) APP_LOG(APP_LOG_LEVEL_ERROR, "markers missing");

  time_t now = time(NULL);
  s_now = *localtime(&now);
  format_dates();

  load_cache();
  read_activity();

  s_window = window_create();
  window_set_background_color(s_window, COL_BG);
  window_set_window_handlers(s_window, (WindowHandlers) {
    .load = window_load,
    .unload = window_unload,
  });
  window_stack_push(s_window, true);

  tick_timer_service_subscribe(MINUTE_UNIT, tick_handler);

  app_message_register_inbox_received(inbox_received);
  app_message_open(512, 128);

  APP_LOG(APP_LOG_LEVEL_INFO, "heap free at start: %d", (int)heap_bytes_free());
}

static void deinit(void) {
  tick_timer_service_unsubscribe();

#if USE_PLACE_FONT
  fonts_unload_custom_font(s_font_place);
#endif
  if (s_wx40) gdraw_command_sequence_destroy(s_wx40);
  if (s_wx18) gdraw_command_sequence_destroy(s_wx18);

  if (s_ic_arrowup) gdraw_command_image_destroy(s_ic_arrowup);
  if (s_ic_arrowdown) gdraw_command_image_destroy(s_ic_arrowdown);
  if (s_ic_windsock) gdraw_command_image_destroy(s_ic_windsock);
  if (s_ic_compass) gdraw_command_image_destroy(s_ic_compass);
  if (s_ic_steps) gdraw_command_image_destroy(s_ic_steps);
  if (s_ic_heart) gdraw_command_image_destroy(s_ic_heart);
  window_destroy(s_window);
}

int main(void) {
  init();
  app_event_loop();
  deinit();
}