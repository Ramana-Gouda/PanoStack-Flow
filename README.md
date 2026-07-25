This is a professional README.md file tailored for your project.

PanoStack (v1.1)

PanoStack is a specialized RAW workflow utility designed for Arch Linux. It
streamlines the process of sorting large batches of photos, merging HDR
brackets, stacking bursts for noise reduction, and stitching panoramas.

By leveraging powerful CLI tools like Darktable, Hugin, and HDRmerge, PanoStack
provides a high-quality 16-bit pipeline for demanding photographers.

✨ Key Features

  - Smart Sorter: Automatically groups photos into "Series," "Bursts," or "HDR
    Brackets" based on timestamps and EXIF data.
  - HDR Processing:
      - HDRmerge: Creates 16-bit float DNGs.
      - Enfuse: Creates high-dynamic-range TIFFs with adjustable weights for
        exposure, saturation, and contrast.
  - Burst Stacking: Uses median evaluation to eliminate noise and moving objects
    from burst shots.
  - Panorama Stitching:
      - Fast Mode: Uses OpenCV for quick 8-bit previews and stitches.
      - Pro Mode (Hugin CLI): Full 16-bit pipeline with photometric optimization
        (-p) for seamless transitions.
  - Darktable Integration: Bypasses the Hugin RAW selection menu by
    pre-processing files via Darktable, ensuring your specific "look" is
    preserved.

🛠 Prerequisites (Arch Linux)

Ensure you have the following dependencies installed via pacman:

sudo pacman -S darktable hugin enblend-enfuse hdrmerge perl-image-exiftool imagemagick python-pyside6 python-opencv

🎨 XMP & Image Style Management

PanoStack relies on Darktable for high-quality RAW development. You can control
the look of your output files using .xmp sidecar files.

1. The Default: oppepper.xmp

  - Function: This is the default "booster" profile. It is applied to all RAW
    files during conversion if no other instructions are found. It typically
    handles basic lens corrections, sharpening, and exposure normalization.
  - Placement: Place the oppepper.xmp file in the same directory as the
    panostack.py script.

2. Folder-Specific XMPs

If you want a specific look for a particular photo series, place an .xmp file
inside that folder. PanoStack will prioritize any XMP found in the local
directory over the global oppepper.xmp.

3. Manual XMP Selection

In the Panorama Tab, you can manually select a "Free XMP" file. This is
particularly useful when you have developed one frame of a panorama in the
Darktable GUI and want to apply those exact settings to all other frames before
stitching.

🚀 Workflow

1.  Sorter: Point to your SD card/import folder. PanoStack will move files into
    a structured directory tree (Model > Date > Sequence).
2.  HDR/Burst: Process the organized folders.
      - HDR merges different exposures.
      - Burst stacks identical exposures to clean up high ISO noise.
3.  Panorama:
      - Select the processed TIFFs or original RAWs.
      - Use Hugin (16-bit) for final gallery-quality results.
      - The "Open GUI" checkbox allows you to refine the stitch in the Hugin
        interface, while still benefiting from PanoStack's automated Darktable
        pre-processing.

⚙️ Configuration

Settings such as directory names and the maximum time gap for sorting are saved
in panostack_config.json in the script directory. You can also adjust these
directly within the UI.

📜 License

This project is provided as-is for the Arch Linux photography community. Feel
free to modify and distribute.
