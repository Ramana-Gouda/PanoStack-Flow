PanoStack Flow: Photo Workflow Automation for HDR, Panorama, and Noise Reduction

This script automates the management and processing of large quantities of RAW
image files. It is specifically designed for photographers working in
challenging low-light conditions, where high ISO settings are required. The tool
performs the essential preparatory steps: sorting sequences by camera and date,
generating intermediate HDR files, and performing high-quality noise reduction
on high-ISO burst sequences.

Functionality

1. Advanced Sorting and Organizing

The script analyzes metadata to create a structured hierarchy: Camera Model >
Capture Date > Sequence Folder.

  - Low-Light Burst Sequences: Sequences captured with identical exposure
    settings (intended for noise reduction) are identified as a single "Burst."
    Unlike HDR stacks, bursts are kept as one continuous sequence, regardless of
    how many frames were captured.
  - HDR Brackets: RAW files with exposure differences (for high-contrast scenes)
    are automatically grouped into stacks based on the selected stack size
    (e.g., 3, 5, or 7).
  - High-ISO Labeling: Sequences captured at ISO 1600 or higher are
    automatically tagged (e.g., Burst_001_ISO3200) for immediate identification
    of files requiring noise reduction.
  - Visual Overview: Individual loose photos and the first capture of every
    sequence remain in the source folder. This ensures a clean workspace and
    provides a backup set for standard processing.

2. Intelligent Noise Reduction & HDR Production

The script processes sequences based on their metadata to ensure optimal image
quality:

  - Burst Sequences (Low-Light): To achieve maximum image cleanliness, the
    script utilizes Mean Stacking logic via Enfuse. By mathematically averaging
    every frame in a high-ISO burst, willekeurige sensor noise is cancelled out,
    resulting in a significantly cleaner TIFF file while preserving fine details
    that traditional noise reduction filters often destroy. HDRmerge (DNG) is
    automatically skipped for these sequences as it is not applicable to
    identical exposures.
  - HDR Brackets (Reeks): Brackets are processed into 32-bit DNG files (via
    HDRmerge) or TIFF files (via Enfuse) to expand the dynamic range in
    high-contrast low-light scenes.

3. Collection and Cleanup

Completed results are moved to a central folder named Verzamelde_HDR_bestanden,
located one level above the working directory. To maintain a clean system,
temporary folders containing the source RAW files can be automatically deleted
after successful processing.

The XMP Profile (oppepper.xmp)

The use of an XMP profile is only required for the TIFF method (Enfuse). When
using the DNG method (HDRmerge), this file is ignored.

  - Purpose of the profile: The profile applies basic corrections during the
    RAW-to-TIFF conversion. For low-light photography, the primary objective is
    lens correction and white balance consistency. Correcting distortions
    beforehand allows for more accurate image alignment. Additionally, modules
    like 'Sigmoid' or 'Local Contrast' can pre-optimize the distribution of the
    dynamic range before blending.

Installation Instructions (Linux/Arch Linux)

Software Dependencies: The following packages must be present. Installation
(Arch Linux example):

sudo pacman -S pyside6 perl-image-exiftool darktable hugin enblend-enfuse hdrmerge xdg-desktop-portal-kde

Preparing the XMP Profile:

1.  Open a RAW photo (preferably a high-ISO shot) in Darktable.
2.  Clear the history and set 'White Balance' to 'Camera'.
3.  Disable 'Color Calibration' (to prevent shifts between camera brands).
4.  Enable 'Lens Correction' and desired base enhancements for low-light shots.
5.  Export these settings as oppepper.xmp to the script directory.

Execution:

chmod +x panostack_flow.py
./panostack_flow.py

About

PanoStack Flow is a Python-based utility for photographers who need to organize
thousands of files and automate the bridge between high-ISO capture and a clean,
noise-free final image. It is the ideal tool for mastering low-light photography
without sacrificing detail.

