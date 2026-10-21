"""HP 48 graphics objects (GROBs) and screen captures as Python bitmaps.

A bitmap is a list of rows, each a list of 0/1 pixels.  In a GROB, each row is
padded to whole bytes and stored as nibbles; bit 0 of a nibble is the leftmost
of its 4 pixels.
"""
import re

# 5x7 digits for the big code display, scaled up by SCALE.
DIGITS_5X7 = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
}
SCALE = 3
DIGIT_W, DIGIT_H = 5 * SCALE, 7 * SCALE

# Where DSCR puts the six big digits (must match rpl/DSCR.hp).
CODE_X, CODE_Y, CODE_STEP, CODE_GAP = 11, 18, 17, 6


def digit_bitmap(d):
    rows = []
    for line in DIGITS_5X7[d]:
        row = [int(c) for c in line for _ in range(SCALE)]
        rows += [row] * SCALE
    return rows


def code_x(k):
    """Left edge of digit k (0-based) of the 6-digit code."""
    return CODE_X + k * CODE_STEP + (CODE_GAP if k >= 3 else 0)


def to_grob(bitmap):
    h, w = len(bitmap), len(bitmap[0])
    nibs_per_row = 2 * ((w + 7) // 8)
    out = []
    for row in bitmap:
        padded = row + [0] * (4 * nibs_per_row - w)
        for i in range(nibs_per_row):
            q = padded[4 * i:4 * i + 4]
            out.append(f"{q[0] | q[1] << 1 | q[2] << 2 | q[3] << 3:X}")
    return f"GROB {w} {h} {''.join(out)}"


def from_grob(text):
    m = re.search(r"GROB\s+(\d+)\s+(\d+)\s+([0-9A-Fa-f]+)", text)
    w, h, data = int(m.group(1)), int(m.group(2)), m.group(3)
    nibs_per_row = 2 * ((w + 7) // 8)
    rows = []
    for y in range(h):
        row = []
        for i in range(nibs_per_row):
            v = int(data[y * nibs_per_row + i], 16)
            row += [(v >> b) & 1 for b in range(4)]
        rows.append(row[:w])
    return rows


# x48ng's small TUI draws 2x2 pixels per character with quadrant blocks.
QUADRANTS = {
    " ": (0, 0, 0, 0), "▘": (1, 0, 0, 0), "▝": (0, 1, 0, 0), "▀": (1, 1, 0, 0),
    "▖": (0, 0, 1, 0), "▌": (1, 0, 1, 0), "▞": (0, 1, 1, 0), "▛": (1, 1, 1, 0),
    "▗": (0, 0, 0, 1), "▚": (1, 0, 0, 1), "▐": (0, 1, 0, 1), "▜": (1, 1, 0, 1),
    "▄": (0, 0, 1, 1), "▙": (1, 0, 1, 1), "▟": (0, 1, 1, 1), "█": (1, 1, 1, 1),
}


def from_tui(screen):
    """LCD bitmap (131x64) from tools/x48.sh screen output."""
    # The frame's side is "│", or "x" when the terminal draws it with the VT100
    # line-drawing set.  Tabs only appear if the terminal type allows hardware tabs.
    lines = [l.expandtabs(8) for l in screen.splitlines() if l[:1] in "│x" and len(l) >= 67][:32]
    rows = [[0] * 132 for _ in range(64)]
    for cy, line in enumerate(lines):
        for cx, ch in enumerate(line[1:67]):
            tl, tr, bl, br = QUADRANTS.get(ch, (0, 0, 0, 0))
            rows[2 * cy][2 * cx], rows[2 * cy][2 * cx + 1] = tl, tr
            rows[2 * cy + 1][2 * cx], rows[2 * cy + 1][2 * cx + 1] = bl, br
    return [r[:131] for r in rows]


def crop(bitmap, x, y, w, h):
    return [row[x:x + w] for row in bitmap[y:y + h]]


def read_code(bitmap):
    """The 6-digit code drawn by DSCR, or None if a digit doesn't match the font."""
    out = ""
    for k in range(6):
        cell = crop(bitmap, code_x(k), CODE_Y, DIGIT_W, DIGIT_H)
        match = [d for d in DIGITS_5X7 if digit_bitmap(d) == cell]
        if not match:
            return None
        out += match[0]
    return out


# Home view rows (rpl/HSCR.hp): 5 rows of 8 px from y=12, code "287 082" at x=87
# in the medium font (6 px per character).
HOME_Y, HOME_ROWS, HOME_CODE_X = 12, 5, 87


def glyphs(strip, chars="0123456789"):
    """Per-character bitmaps from a GROB of `chars` rendered with 2 ->GROB (6x8 each)."""
    return {c: crop(strip, 6 * i, 0, 6, 8) for i, c in enumerate(chars)}


def read_home(bitmap, digits):
    """[(code, selected)] for the home view's visible rows, code None if unreadable."""
    rows = []
    for k in range(HOME_ROWS):
        y = HOME_Y + 8 * k
        selected = bitmap[y][0] == 1  # the selected row is drawn inverted
        code = ""
        for i in (0, 1, 2, 4, 5, 6):
            cell = crop(bitmap, HOME_CODE_X + 6 * i, y, 6, 8)
            if selected:
                cell = [[1 - p for p in row] for row in cell]
            match = [d for d, g in digits.items() if g == cell]
            code += match[0] if match else "?"
        rows.append((None if "?" in code else code, selected))
    return rows


def ascii_art(bitmap):
    return "\n".join("".join("#" if p else "." for p in row) for row in bitmap)
