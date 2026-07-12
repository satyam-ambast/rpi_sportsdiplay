"""
pixel_font_var.py

A proportional (variable-width) bitmap pixel font, 5 rows tall, where
each glyph declares its own width instead of all glyphs sharing a
fixed cell size. Narrow characters (I, ., :, 1, etc.) take up only
1-2 columns instead of forcing every character to the width of the
widest one — this is how classic small LED/pixel fonts pack more
text into less horizontal space without shrinking the actual pixel
grid (and therefore without losing legibility the way a smaller
fixed grid would).

Same crisp-by-construction guarantee as the other pixel_font modules:
every "on" pixel is a hard putpixel, so there is never any
anti-aliasing or blur, at any zoom level.

Grid convention: each glyph is a list of 5 row-strings. All rows in
a glyph share the same length (that glyph's width); different glyphs
can have different widths. '1' = pixel on, '0' = off.
"""

from PIL import Image

FONT_VAR = {
    'A': ["010", "101", "111", "101", "101"],
    'B': ["110", "101", "110", "101", "110"],
    'C': ["011", "100", "100", "100", "011"],
    'D': ["110", "101", "101", "101", "110"],
    'E': ["111", "100", "110", "100", "111"],
    'F': ["111", "100", "110", "100", "100"],
    'G': ["011", "100", "101", "101", "011"],
    'H': ["101", "101", "111", "101", "101"],
    'I': ["1", "1", "1", "1", "1"],
    'J': ["001", "001", "001", "101", "010"],
    'K': ["101", "101", "110", "101", "101"],
    'L': ["10", "10", "10", "10", "11"],
    'M': ["10001", "11011", "10101", "10001", "10001"],
    'N': ["101", "111", "111", "101", "101"],
    'O': ["111", "101", "101", "101", "111"],
    'P': ["111", "101", "111", "100", "100"],
    'Q': ["111", "101", "101", "111", "001"],
    'R': ["111", "101", "111", "110", "101"],
    'S': ["011", "100", "111", "001", "110"],
    'T': ["111", "010", "010", "010", "010"],
    'U': ["101", "101", "101", "101", "111"],
    'V': ["101", "101", "101", "101", "010"],
    'W': ["10001", "10001", "10101", "10101", "01010"],
    'X': ["101", "101", "010", "101", "101"],
    'Y': ["101", "101", "010", "010", "010"],
    'Z': ["111", "001", "010", "100", "111"],

    '0': ["111", "101", "101", "101", "111"],
    '1': ["01", "11", "01", "01", "11"],
    '2': ["111", "001", "111", "100", "111"],
    '3': ["111", "001", "111", "001", "111"],
    '4': ["101", "101", "111", "001", "001"],
    '5': ["111", "100", "111", "001", "111"],
    '6': ["111", "100", "111", "101", "111"],
    '7': ["111", "001", "001", "001", "001"],
    '8': ["111", "101", "111", "101", "111"],
    '9': ["111", "101", "111", "001", "111"],

    ' ': ["0", "0", "0", "0", "0"],
    '/': ["001", "001", "010", "100", "100"],
    '.': ["0", "0", "0", "0", "1"],
    ':': ["0", "1", "0", "1", "0"],
    '-': ["000", "000", "111", "000", "000"],
    "'": ["1", "1", "0", "0", "0"],
    '!': ["1", "1", "1", "0", "1"],
    '(': ["01", "10", "10", "10", "01"],
    ')': ["10", "01", "01", "01", "10"],
}

GLYPH_H = 5

# small = native size (1x). medium/large are crisp integer upscales -
# each logical font pixel is drawn as an NxN solid block instead of
# being resampled, so there is still zero anti-aliasing at any size.
SIZE_SCALE = {
    'small': 1,
    'medium': 2,
    'large': 3,
}


def glyph_width(ch):
    glyph = FONT_VAR.get(ch, FONT_VAR.get(ch.upper(), FONT_VAR[' ']))
    return len(glyph[0])


def _gap(prev_ch, next_ch, spacing):
    """
    Spacing between two adjacent characters. A space character already
    acts as a gap by itself, so we don't add extra spacing right next
    to one (that would double up the gap and waste width). Between two
    real letters/digits, the full spacing is used - this is what makes
    individual letters visually distinct instead of touching.
    """
    if prev_ch == ' ' or next_ch == ' ':
        return 0
    return spacing


def text_width(text, spacing=1, size='small'):
    """
    Pixel width a string will occupy when blitted, at the given size
    ('small', 'medium', or 'large'). `spacing` is in small-font pixels
    and scales up automatically with size, same as the glyphs do.
    """
    if not text:
        return 0
    scale = SIZE_SCALE[size]
    widths = [glyph_width(ch) for ch in text]
    total = sum(widths)
    for i in range(len(text) - 1):
        total += _gap(text[i], text[i + 1], spacing)
    return total * scale


def text_height(size='small'):
    """Pixel height a line of text occupies at the given size."""
    return GLYPH_H * SIZE_SCALE[size]


def blit_text(img, x, y, text, color, spacing=1, size='small'):
    """
    Draw `text` onto a PIL Image `img` at top-left (x, y) using the
    proportional pixel font, at the given size ('small', 'medium', or
    'large'). Every pixel is drawn as a solid NxN block via putpixel/
    rectangle fill - no blending, no anti-aliasing, fully crisp at any
    size or zoom level.

    spacing=1 (default) puts a 1px (pre-scale) gap between adjacent
    letters/digits so they stay visually distinct instead of touching.
    No extra gap is added next to a literal space character, since the
    space glyph itself already provides separation between words.
    """
    scale = SIZE_SCALE[size]
    cursor_x = x
    prev_ch = None
    for ch in text:
        if prev_ch is not None:
            cursor_x += _gap(prev_ch, ch, spacing) * scale
        glyph = FONT_VAR.get(ch, FONT_VAR.get(ch.upper(), FONT_VAR[' ']))
        w = len(glyph[0])
        for row_i, row in enumerate(glyph):
            for col_i, bit in enumerate(row):
                if bit == '1':
                    bx = cursor_x + col_i * scale
                    by = y + row_i * scale
                    for dx in range(scale):
                        for dy in range(scale):
                            px, py = bx + dx, by + dy
                            if 0 <= px < img.width and 0 <= py < img.height:
                                img.putpixel((px, py), color)
        cursor_x += w * scale
        prev_ch = ch
