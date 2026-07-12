PanoStack Flow: Automated HDR Panorama & Noise Reduction Workflow

PanoStack Flow is a specialized Python-based workflow utility designed to
automate the management and processing of large quantities of RAW image files.
It focuses primarily on the creation of HDR panoramas and the optimization of
image quality through advanced stacking techniques.

The tool is ideal for challenging conditions—such as sunrises or interiors—where
high ISO settings and limited apertures are required. By bridging the gap
between raw capture and a clean, noise-free final image, it allows for
professional results without manual drudgery.

Functionality

1. Advanced Sorting and Organizing (Tab 1)

The script analyzes metadata to create a structured hierarchy: Camera Model >
Capture Date > Sequence Folder.

  - HDR Brackets (Reeks_): RAW files with exposure differences (bracketing) are
    automatically grouped into stacks based on the selected bracket size
    (e.g., 3, 5, or 7).
  - High-ISO Burst Sequences (Burst_): Sequences captured with identical
    exposure settings at ISO > 800 are identified as a single "Burst." This is
    specifically designed for noise reduction in low-light photography.
  - Sets (Serie_): Groups with identical exposures at low ISO (≤ 800) are
    categorized as standard series.
  - Workspace Safety: The first capture of every sequence and all individual
    loose photos remain in the source folder, providing a visual overview and a
    backup set.

2. Intelligent Noise Reduction & HDR Production (Tabs 2 & 3)

The script processes sequences to ensure maximum image cleanliness and dynamic
range:

  - HDR Processing (Tab 2): Brackets can be processed into Enfuse (TIFF) files
    for immediate use with smooth gradients (ideal for sunrises) or HDRmerge
    (DNG) 16-bit RAW files for maximum editing flexibility.
  - Burst Stacking (Tab 3): To combat noise from high ISO settings, the script
    utilizes Mean Stacking logic. By mathematically averaging a burst of 8 or 16
    identical frames, random sensor noise is cancelled out. This results in a
    "clean" TIFF file, preserving fine details that traditional noise reduction
    filters often destroy.
  - Performance: Features a "Stop" button in every processing tab and background
    execution to keep the UI responsive.

3. Panorama Stitching (Tab 4)

The final stage merges the collected HDR or Burst results into a seamless
panorama.

  - Source Selection: A dedicated filter allows you to choose between your
    collected TIFF/JPG files or DNG files. (Note: TIFF is recommended for
    panoramas to avoid exposure seams caused by varying HDRmerge masks).
  - Background Loading: Thumbnails are loaded in the background with a progress
    bar, preventing the UI from hanging even with 180+ folders.
  - Darktable Integration: A dedicated button opens the selected preview
    directly in Darktable using the --library :memory: flag. This ensures a
    database-free, fast launch for final inspection or minor adjustments.

The XMP Logic (Development)

The program is highly flexible in how RAW files are "developed" via Darktable:

1.  Individual Sidecars: If a .xmp file exists alongside the RAW photo (created
    previously in the Darktable GUI), those specific settings are used.
2.  Global Preset (oppepper.xmp): If no sidecar is found, the script looks for
    oppepper.xmp in the script's directory to apply a consistent "look" (e.g.,
    Sigmoid or AgX) across the entire sequence.
3.  Default: If both are missing, Darktable falls back to internal factory
    settings.

Installation Instructions (Linux)

Software Dependencies

The script requires a Linux environment. While it integrates perfectly with KDE
Plasma, the PySide6 interface is fully compatible with GNOME and other desktop
environments.

Installation (Arch Linux example):

sudo pacman -S pyside6 perl-image-exiftool darktable hugin enblend-enfuse hdrmerge imagemagick python-opencv

Preparing the XMP Profile

1.  Open a RAW photo in Darktable.
2.  Clear the history and set 'White Balance' to 'Camera'.
3.  Enable 'Lens Correction' and your preferred tone mapper (e.g., Sigmoid).
4.  Export these settings as oppepper.xmp to the directory where the script is
    located.

Execution

chmod +x panostack_flow.py
./panostack_flow.py

About

PanoStack Flow is the essential bridge for photographers who need to master
low-light HDR panorama photography. By automating the alignment and stacking
process, it delivers noise-free, high-dynamic-range images while maintaining a
fast and organized workflow.
