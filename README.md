PanoStack v3.5.0 - High-Quality RAW Workflow

PanoStack is an automated utility for Arch Linux designed to organize, stack,
and stitch professional-grade panoramas using Darktable, Hugin, and OpenCV.

🛠 Dependencies (Arch Linux)

# Core tools
sudo pacman -S darktable hugin enblend-enfuse perl-image-exiftool imagemagick
# Python environment
sudo pacman -S python-pyside6 python-opencv python-numpy
# AUR (Required for DNG stacking)
yay -S hdrmerge

💡 Key Concepts

  - XMP Workflow: PanoStack uses Darktable for RAW development.
  - Lens Correction: Use a Free XMP with Lens Correction enabled in Tab 4. This
    ensures perfect alignment and a straight horizon.
  - 16-bit Quality: All intermediate files are 16-bit TIFFs to preserve maximum
    dynamic range.

📂 Tab 1: Sorting & Non-HDR Workflow

  - HDR Gap: Max time between bracketed frames.
  - Burst Gap (5.0s): Max time between panorama frames.
  - Pro Tip: Enabling "Copy 1st of series" puts standard exposures in your root
    folder. Use these in Tab 4 for a lightning-fast Non-HDR panorama preview
    without waiting for HDR processing.

🏗 Tab 2 & 3: Stacking

  - HDRmerge (DNG): Best for 32-bit editing flexibility.
  - Enfuse (TIFF): Best for ready-to-use tone-mapped results.
  - Burst (Median): Aligns handheld sequences and removes sensor noise while
    maintaining sharpness.

🖼 Tab 4: Panorama & Exposure Fix

  - Stitching Engines: Choose between fast OpenCV (8-bit Ultra-HQ) or
    professional Hugin CLI (16-bit) with automatic horizon leveling.
  - Individual EV Fix: If frames have different brightness (common in HDRmerge):
    1.  Right-click the thumbnail.
    2.  Select +1 to -3 EV.
    3.  PanoStack injects this fix into your XMP history, maintaining your
        color/noise settings while only adjusting brightness.

Waarom deze versie goed is:

1.  Directe actie: De installatiecommando's staan bovenaan.
2.  Highlighting: Belangrijke termen zijn vetgedrukt.
3.  Pro-tip: De Non-HDR workflow wordt als een 'geheim voordeel' gepresenteerd.
4.  Duidelijke stappen: De EV-fix (je nieuwste functie) wordt uitgelegd als een
    simpel 1-2-3 stappenplan.

