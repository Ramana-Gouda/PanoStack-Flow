# PanoStack (v9.8 - ART Edition)

**PanoStack** is an automated, high-quality RAW workflow utility designed for photographers. It streamlines sorting, bracket stacking (HDR & Burst noise reduction), and panorama stitching into an intuitive, multi-stage pipeline.

---

## Key Features & Core Architecture

### 1. RAW Conversion Powered by ART-cli
At the core of PanoStack's image pipeline is **ART-cli** (*Another RawTherapee* command-line interface).
* **16-bit TIFF Development:** All RAW exposures (`.rw2`, `.arw`, `.cr2`, `.cr3`, `.nef`, `.orf`, `.raf`, `.dng`) are accurately demosaiced and developed into uncompressed or high-fidelity 16-bit TIFF files before any alignment, stacking, or stitching takes place.
* **Custom Processing Profiles (`.arp`):** Choose the built-in profile or supply your own custom `.arp` profile (*Vrije ARP*). This applies consistent lens geometry correction (vignetting, distortion, chromatic aberration), tone curves, and white balance across all frames in a panorama or HDR bracket before stitching.

### 2. Flexible Post-Processing ("Start Fotoprogramma")
Once panoramas are stitched or intermediate brackets are generated, you can open them immediately in your photo editor of choice:
* **Custom Editor Selector:** Choose from defaults like `art`, `darktable`, `ansel`, or `gimp`, or type in any executable available in your system path.
* **Seamless Launching:** Applications launch detached and independently without blocking PanoStack or locking I/O buffers. You can open the finished panorama or any selected DNG/TIFF/RAW files with a single click.

---

## Workflow Tabs

### Tab 1: Sort ("1. Sorteren")
Analyzes source folders and organizes photos chronologically by EXIF metadata into structured subfolders by Camera Model and Date:
* **HDR Gap:** Maximum time interval (seconds) allowed between shots with differing exposure times (brackets).
* **Burst / Pano Gap:** Maximum time interval (default: 3.0s) between shots taken with identical exposure parameters (panoramas or high-speed bursts).
* **Keep Reference Copy:** Automatically saves a copy of the first shot in the root folder for rapid thumbnail browsing.

### Tab 2: HDR Stacking ("2. HDR")
Merges bracketed exposures into high dynamic range masters:
* **Enfuse (16-bit TIFF):** RAW files are developed via **ART-cli** (using the chosen `.arp` profile), aligned sub-pixel with `align_image_stack`, and blended with `enfuse`.
* **HDRmerge (32-bit Floating-Point DNG):** Merges raw sensor data directly into a 32-bit linear DNG for maximum shadow and highlight recovery.
* **Dual Progress Bars:** Track both overall batch progress and individual frame development simultaneously.

### Tab 3: Burst Stacking ("3. Burst")
Reduces noise in handheld, high-ISO burst sequences:
* Develops frames via **ART-cli**, aligns perspectives, and performs median sequence evaluation via ImageMagick to produce a clean, noise-free 16-bit master file without tripod blur.

### Tab 4: Panorama Stitching & Management ("4. Panorama")
* **Mode Switching:** Instantly filter and switch views between intermediate HDR TIFFs, DNGs, raw sequence sets, or single frames. The collection folder automatically points to the corresponding `TIFF/` or `DNG/` directory.
* **Robust Previews:** Built-in multi-stage preview loader supporting embedded EXIF JPEGs, fast `ART-cli -s` preview demosaicing for HDRmerge DNGs, and ImageMagick/OpenCV fallbacks for large 16-bit TIFFs.
* **Dual Stitching Engines:**
  * **16-bit Hugin CLI:** Full professional pipeline (`pto_gen`, `cpfind`, `cpclean`, `autooptimiser`, `pano_modify`, and `hugin_executor`) with automatic leveling and photometric blending. Supports an optional "Open GUI" mode.
  * **Ultra-HQ OpenCV (8-bit):** Ultra-fast preview and projection engine utilizing an advanced 16-to-8-bit compression pipeline (Percentile Stretching + Lab-CLAHE).

---

## System Requirements (Linux)

Install core packages via your package manager:

```bash
# Arch Linux / Manjaro
sudo pacman -S art hugin enblend-enfuse perl-image-exiftool imagemagick pyside6 python-opencv python-numpy python-psutil

# AUR (Required for DNG merging)
yay -S hdrmerge
