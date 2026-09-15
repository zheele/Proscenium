#!/usr/bin/env python3
"""
make_cards.py - Generate a printable A4 PDF of GM-screen character cards
from a folder of images + matching Markdown files.

There are two separate physical frames per character, so this produces
two independently-packed sets of cutouts:

  FRONT frame (character art):
    Outer card:      45 wide  x 62 tall
    Inner window:    41 wide  x 56 tall
                        - 2mm margin left/right
                        - 4mm margin from the top
                        - 2mm margin from the bottom

  BACK frame (name + stats) - a smaller frame with the SAME margins as
  the front, just a shorter window, so its outer size works out smaller:
    Inner window:    41 wide  x 22 tall
    Outer card:       45 wide x 28 tall
                        (2mm left/right + 4mm top + 2mm bottom, same as front)

Because the back cards are physically smaller, they're packed as densely
as will fit per page independently of the front layout - the two sheets
are not positionally aligned. Each card carries its own identity (the art
on the front, the name text on the back), so that's not a problem for
matching them up afterwards.

Folder layout expected in CARDS_DIR - pairs of files sharing a name:

    goblin.png
    goblin.md
    skeleton.jpg
    skeleton.md

Each .md file's first heading (# Name) becomes the centered, bold name;
everything else becomes the stat block below it. Basic **bold**, *italic*
and "- bullet" markdown is supported. A file with an image but no .md
(or vice versa) still gets a card - the missing side is left blank.

Usage:
    python make_cards.py CARDS_DIR [-o cards.pdf] [options]

Run with -h for all options.
"""

import argparse
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

# ---------------------------------------------------------------------------
# Geometry (all in mm) - edit these if your frame's dimensions differ.
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = 210.0, 297.0          # A4

MARGIN_L = 2.0    # left/right margin between a frame's outer edge and its
MARGIN_T = 4.0    # inner (visible) window - same for both frames
MARGIN_B = 2.0

# --- front frame (character art) ---
FRONT_WIN_W, FRONT_WIN_H = 41.0, 56.0
FRONT_CARD_W = FRONT_WIN_W + 2 * MARGIN_L
FRONT_CARD_H = MARGIN_T + FRONT_WIN_H + MARGIN_B

# --- back frame (name + stats) ---
BACK_WIN_W, BACK_WIN_H = 41.0, 22.0
BACK_CARD_W = BACK_WIN_W + 2 * MARGIN_L
BACK_CARD_H = MARGIN_T + BACK_WIN_H + MARGIN_B

GUTTER = 2.0         # gap between cards
PAGE_MARGIN = 8.0    # minimum margin used only to decide how many cards
                      # fit per page; the grid is then centered on the page

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}

# ---------------------------------------------------------------------------
# Grid layout
# ---------------------------------------------------------------------------

def compute_grid(card_w, card_h):
    avail_w = PAGE_W - 2 * PAGE_MARGIN
    avail_h = PAGE_H - 2 * PAGE_MARGIN
    cols = max(1, int((avail_w + GUTTER) // (card_w + GUTTER)))
    rows = max(1, int((avail_h + GUTTER) // (card_h + GUTTER)))
    grid_w = cols * card_w + (cols - 1) * GUTTER
    grid_h = rows * card_h + (rows - 1) * GUTTER
    offset_x = (PAGE_W - grid_w) / 2
    offset_y = (PAGE_H - grid_h) / 2
    return cols, rows, offset_x, offset_y


def card_origin(index, cols, offset_x, offset_y, card_w, card_h):
    """Bottom-left (x, y) of a card in mm, reportlab's bottom-left origin."""
    col = index % cols
    row = index // cols
    x = offset_x + col * (card_w + GUTTER)
    top_y = PAGE_H - offset_y - row * (card_h + GUTTER)
    y = top_y - card_h
    return x, y


# ---------------------------------------------------------------------------
# Markdown -> reportlab helpers
# ---------------------------------------------------------------------------

def xml_escape(text):
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))


def inline_md(text):
    text = xml_escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_([^_\n]+?)_(?!_)', r'<i>\1</i>', text)
    return text


def parse_card_md(md_text):
    """Split a card's markdown into (header_text, [body_lines])."""
    lines = [l.rstrip() for l in md_text.strip('\n').split('\n')]
    header = None
    body = []
    for raw in lines:
        line = raw.strip()
        if not line:
            body.append('')
            continue
        m = re.match(r'^#{1,6}\s+(.*)', line)
        if m:
            if header is None:
                header = m.group(1)
            else:
                body.append('**' + m.group(1) + '**')
            continue
        b = re.match(r'^[-*]\s+(.*)', line)
        if b:
            body.append('• ' + b.group(1))
        else:
            body.append(line)
    if header is None:
        for i, l in enumerate(body):
            if l:
                header = l
                body.pop(i)
                break
    while body and not body[0]:
        body.pop(0)
    while body and not body[-1]:
        body.pop()
    return header or '', body


def fit_two_paragraphs(header_xml, body_xml, avail_w_pt, avail_h_pt,
                        header_align=TA_CENTER, body_align=TA_CENTER,
                        max_size=9.0, min_size=3.0, gap_pt=2.0):
    """Find the largest font scale where a header + body paragraph both
    fit inside avail_h_pt. Returns (hp, bp, hh, bh, total_h)."""
    size = max_size
    while size >= min_size:
        h_size = size
        b_size = size * 0.72
        h_style = ParagraphStyle('h', fontName='Helvetica-Bold',
                                  fontSize=h_size, leading=h_size * 1.12,
                                  alignment=header_align)
        b_style = ParagraphStyle('b', fontName='Helvetica',
                                  fontSize=b_size, leading=b_size * 1.18,
                                  alignment=body_align)
        hp = Paragraph(header_xml, h_style) if header_xml else None
        bp = Paragraph(body_xml, b_style) if body_xml else None
        hh = bh = 0.0
        if hp:
            _, hh = hp.wrap(avail_w_pt, avail_h_pt * 10)
        if bp:
            _, bh = bp.wrap(avail_w_pt, avail_h_pt * 10)
        total_h = hh + bh + (gap_pt if hp and bp else 0.0)
        if total_h <= avail_h_pt:
            return hp, bp, hh, bh, total_h
        size -= 0.25

    # nothing fit even at min_size - use min_size anyway (will overflow)
    h_size = min_size
    b_size = min_size * 0.72
    h_style = ParagraphStyle('h', fontName='Helvetica-Bold',
                              fontSize=h_size, leading=h_size * 1.12,
                              alignment=header_align)
    b_style = ParagraphStyle('b', fontName='Helvetica',
                              fontSize=b_size, leading=b_size * 1.18,
                              alignment=body_align)
    hp = Paragraph(header_xml, h_style) if header_xml else None
    bp = Paragraph(body_xml, b_style) if body_xml else None
    hh = bh = 0.0
    if hp:
        _, hh = hp.wrap(avail_w_pt, avail_h_pt * 10)
    if bp:
        _, bh = bp.wrap(avail_w_pt, avail_h_pt * 10)
    total_h = hh + bh + (gap_pt if hp and bp else 0.0)
    return hp, bp, hh, bh, total_h


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def load_image_reader(path, target_w_mm, target_h_mm, fit='cover'):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    if fit == 'cover':
        target_ratio = target_w_mm / target_h_mm
        w, h = img.size
        src_ratio = w / h
        if src_ratio > target_ratio:
            new_w = max(1, int(h * target_ratio))
            x0 = (w - new_w) // 2
            img = img.crop((x0, 0, x0 + new_w, h))
        else:
            new_h = max(1, int(w / target_ratio))
            y0 = (h - new_h) // 2
            img = img.crop((0, y0, w, y0 + new_h))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return ImageReader(buf)


# ---------------------------------------------------------------------------
# Card collection
# ---------------------------------------------------------------------------

class CardEntry:
    def __init__(self, stem, image_path, md_path):
        self.stem = stem
        self.image_path = image_path
        self.md_path = md_path


def collect_entries(cards_dir):
    cards_dir = Path(cards_dir)
    stems = {}
    for p in sorted(cards_dir.iterdir()):
        if p.is_dir():
            continue
        ext = p.suffix.lower()
        if ext not in IMAGE_EXTS and ext != '.md':
            continue
        entry = stems.setdefault(p.stem, {'image': None, 'md': None})
        if ext in IMAGE_EXTS:
            entry['image'] = p
        elif ext == '.md':
            entry['md'] = p
    entries = []
    for stem in sorted(stems.keys()):
        d = stems[stem]
        entries.append(CardEntry(stem, d['image'], d['md']))
    return entries


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def draw_cut_lines(c, x, y, card_w, card_h):
    c.saveState()
    c.setLineWidth(0.25)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.rect(x * mm, y * mm, card_w * mm, card_h * mm, stroke=1, fill=0)
    c.restoreState()


def draw_debug_label(c, x, y, card_w, stem):
    c.saveState()
    c.setFont('Helvetica', 4)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawCentredString((x + card_w / 2) * mm, (y - 2.5) * mm, stem)
    c.restoreState()


def draw_front_card(c, entry, x, y, fit, cut_lines, debug):
    if cut_lines:
        draw_cut_lines(c, x, y, FRONT_CARD_W, FRONT_CARD_H)
    win_x = x + MARGIN_L
    win_y = y + MARGIN_B
    if entry.image_path:
        try:
            img_reader = load_image_reader(entry.image_path, FRONT_WIN_W, FRONT_WIN_H, fit=fit)
            if fit == 'cover':
                c.drawImage(img_reader, win_x * mm, win_y * mm,
                            width=FRONT_WIN_W * mm, height=FRONT_WIN_H * mm,
                            mask='auto')
            else:
                c.drawImage(img_reader, win_x * mm, win_y * mm,
                            width=FRONT_WIN_W * mm, height=FRONT_WIN_H * mm,
                            preserveAspectRatio=True, anchor='c', mask='auto')
        except Exception as e:
            print(f"  ! could not place image for '{entry.stem}': {e}", file=sys.stderr)
    else:
        c.saveState()
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.setDash(1, 2)
        c.rect(win_x * mm, win_y * mm, FRONT_WIN_W * mm, FRONT_WIN_H * mm)
        c.restoreState()
    if debug:
        draw_debug_label(c, x, y, FRONT_CARD_W, entry.stem)


def draw_back_card(c, entry, x, y, cut_lines, header_align, body_align, debug):
    if cut_lines:
        draw_cut_lines(c, x, y, BACK_CARD_W, BACK_CARD_H)
    win_x = x + MARGIN_L
    win_y = y + MARGIN_B

    if debug:
        c.saveState()
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setDash(1, 2)
        c.rect(win_x * mm, win_y * mm, BACK_WIN_W * mm, BACK_WIN_H * mm)
        c.restoreState()

    if entry.md_path:
        try:
            text = entry.md_path.read_text(encoding='utf-8')
        except Exception as e:
            print(f"  ! could not read {entry.md_path}: {e}", file=sys.stderr)
            text = ''
        header, body_lines = parse_card_md(text)
        header_xml = f"<b>{inline_md(header)}</b>" if header else ''
        body_xml = '<br/>'.join(inline_md(l) if l else '' for l in body_lines)

        hp, bp, hh, bh, total_h = fit_two_paragraphs(
            header_xml, body_xml, BACK_WIN_W * mm, BACK_WIN_H * mm,
            header_align=header_align, body_align=body_align)

        box_top = (win_y + BACK_WIN_H) * mm
        box_bottom = win_y * mm
        top_margin = ((box_top - box_bottom) - total_h) / 2
        cursor = box_top - top_margin
        if hp:
            cursor -= hh
            hp.drawOn(c, win_x * mm, cursor)
            cursor -= 2.0
        if bp:
            cursor -= bh
            bp.drawOn(c, win_x * mm, cursor)

    if debug:
        draw_debug_label(c, x, y, BACK_CARD_W, entry.stem)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_pdf(entries, output_path, fit='cover', cut_lines=True,
              header_align_name='center', body_align_name='center', debug=False):
    align_map = {'center': TA_CENTER, 'left': TA_LEFT}
    header_align = align_map[header_align_name]
    body_align = align_map[body_align_name]

    front_cols, front_rows, front_ox, front_oy = compute_grid(FRONT_CARD_W, FRONT_CARD_H)
    front_per_page = front_cols * front_rows

    back_cols, back_rows, back_ox, back_oy = compute_grid(BACK_CARD_W, BACK_CARD_H)
    back_per_page = back_cols * back_rows

    c = canvas.Canvas(str(output_path), pagesize=(PAGE_W * mm, PAGE_H * mm))

    # --- front (art) pages ---
    for page_start in range(0, len(entries), front_per_page):
        page_entries = entries[page_start:page_start + front_per_page]
        for i, entry in enumerate(page_entries):
            x, y = card_origin(i, front_cols, front_ox, front_oy, FRONT_CARD_W, FRONT_CARD_H)
            draw_front_card(c, entry, x, y, fit, cut_lines, debug)
        c.showPage()

    # --- back (name/stats) pages - packed independently, smaller cards ---
    for page_start in range(0, len(entries), back_per_page):
        page_entries = entries[page_start:page_start + back_per_page]
        for i, entry in enumerate(page_entries):
            x, y = card_origin(i, back_cols, back_ox, back_oy, BACK_CARD_W, BACK_CARD_H)
            draw_back_card(c, entry, x, y, cut_lines, header_align, body_align, debug)
        c.showPage()

    c.save()
    return (front_cols, front_rows, front_per_page), (back_cols, back_rows, back_per_page)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cards_dir', help='Folder containing image + .md pairs')
    ap.add_argument('-o', '--output', default='cards.pdf', help='Output PDF path')
    ap.add_argument('--fit', choices=['cover', 'contain'], default='cover',
                     help='How to fit images into the front window '
                          '(default: cover = crop to fill; contain = letterbox)')
    ap.add_argument('--no-cut-lines', action='store_true', help='Do not draw cut guide lines')
    ap.add_argument('--header-align', choices=['center', 'left'], default='center')
    ap.add_argument('--body-align', choices=['center', 'left'], default='center')
    ap.add_argument('--debug', action='store_true',
                     help='Draw window outlines and filenames for alignment checking')
    args = ap.parse_args()

    entries = collect_entries(args.cards_dir)
    if not entries:
        print(f"No images or .md files found in {args.cards_dir}", file=sys.stderr)
        sys.exit(1)

    missing_img = [e.stem for e in entries if e.image_path is None]
    missing_md = [e.stem for e in entries if e.md_path is None]
    if missing_img:
        print(f"Note: no image for: {', '.join(missing_img)} (front left blank)")
    if missing_md:
        print(f"Note: no .md for: {', '.join(missing_md)} (back left blank)")

    (fcols, frows, fpp), (bcols, brows, bpp) = build_pdf(
        entries, args.output, fit=args.fit, cut_lines=not args.no_cut_lines,
        header_align_name=args.header_align, body_align_name=args.body_align,
        debug=args.debug)

    f_pages = -(-len(entries) // fpp)  # ceil
    b_pages = -(-len(entries) // bpp)
    print(f"{len(entries)} card(s)")
    print(f"  fronts: {fcols}x{frows} grid ({fpp}/page) -> {f_pages} page(s)")
    print(f"  backs:  {bcols}x{brows} grid ({bpp}/page) -> {b_pages} page(s)")
    print(f"Wrote {args.output}")


if __name__ == '__main__':
    main()
