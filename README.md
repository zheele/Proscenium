# GM screen portrait cards

Generates a printable A4 PDF of character cards for your card frames, from a
folder of images + matching Markdown stat blocks.

## Setup

```
pip install -r requirements.txt
```

## Folder format

Put pairs of files with the **same name** in a folder (see `cards/` for a
working example):

```
cards/
  goblin.png
  goblin.md
  skeleton.jpg
  skeleton.md
```

- Any of `.png .jpg .jpeg .webp .bmp .tif .tiff` works for the image.
- The `.md` file's first heading becomes the card's name (bold, centered);
  everything after it becomes the stat block. `**bold**`, `*italic*` and
  `- bullet` lines are supported. Example:

  ```markdown
  # Grubnash the Sly

  - **AC** 13
  - **HP** 7 (2d6)
  - **Speed** 30 ft
  - Nimble Escape: disengages or hides as a bonus action
  ```

- A file with only an image (no `.md`) or only a `.md` (no image) still
  gets a card - the missing side is just left blank.

## Generate the PDF

```
python make_cards.py cards -o cards.pdf
```

This produces one PDF with:
1. **Front pages** - one card per image, cropped to fill the art window.
2. **Back pages** - one card per stat block, name + stats centered.

The front and back are two *separate, differently-sized* frames (see
below), so they're packed independently and as densely as each page
allows - they are **not** in matching grid positions across the two
sheets. That's fine in practice: the art identifies the front card and
the printed name identifies the back card, so there's nothing to mix up
while cutting.

Cut along the thin gray outer rectangle on each card (pass
`--no-cut-lines` to omit it once you've got your cutting technique down).

## Card geometry

Based on the frame dimensions you supplied, there are two frames per
character - a larger one on the front for the art, and a smaller one on
the back for the name/stats, using the *same* margins between outer edge
and inner window on both:

| | outer width | outer height | window width | window height |
|---|---|---|---|---|
| Front frame (art) | 45 mm | 62 mm | 41 mm | 56 mm |
| Back frame (name/stats) | 45 mm | 28 mm | 41 mm | 22 mm |

Both frames use the same margins: 2 mm left/right, 4 mm from the top,
2 mm from the bottom - the back frame is simply shorter because its
window is shorter (4 + 22 + 2 = 28 mm), which is what lets it hang over
the top edge of the GM screen while the front frame sits in the screen
panel.

If your margins are actually different, edit `MARGIN_L` / `MARGIN_T` /
`MARGIN_B` at the top of `make_cards.py` - both frames' outer sizes are
computed from those plus the window sizes, so you only need to change
them in one place.

## Other options

```
python make_cards.py cards -o cards.pdf --fit contain   # letterbox instead of crop-to-fill
python make_cards.py cards -o cards.pdf --header-align left --body-align left
python make_cards.py cards -o cards.pdf --debug          # show window outlines + filenames, for checking alignment before a real print
python make_cards.py cards -o cards.pdf --brighten 1.3   # brighten front-card images, for a printer that prints dark
```

`--brighten` only affects the front (art) images - it doesn't touch the
back stat-block pages. `1.0` is unchanged, `1.2` is 20% brighter, and so
on; there's no single right value, since it depends on your printer, so
print a test page and adjust from there.

## Settings file

So you don't have to retype the same flags every time, `--fit`,
`--cut-lines`/`--no-cut-lines`, `--brighten`, `--header-align` and
`--body-align` can also be set in a TOML settings file:

- `~/.gm_cards.toml` - global defaults, used for every `cards` folder.
- `<cards_dir>/.gm_cards.toml` - per-folder overrides, for a deck that
  needs different settings (e.g. a printer-specific `brighten` value).

A CLI flag, when given explicitly, always wins over both files. Example:

```toml
# ~/.gm_cards.toml
brighten = 1.3
fit = "contain"
```

Requires Python 3.11+ (for the standard library's `tomllib`); on older
Python, settings files are ignored with a warning.

Run `python make_cards.py -h` for the full list.

All the geometry constants (page size, card size, margins, gutter between
cards) live at the top of `make_cards.py` if your frames turn out to be
slightly different from the numbers above.
