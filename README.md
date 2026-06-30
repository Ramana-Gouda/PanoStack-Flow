**Photo Workflow Automation for HDR and Panorama Photography**

This script automates the management and processing of large quantities of RAW image files. It is designed to perform the preparatory steps for panorama construction: sorting sequences, generating intermediate HDR files, and organizing the folder structure.

**Functionality**

1. **Sorting and Organizing:** RAW files are automatically grouped into sequences (stacks) based on capture time and exposure differences. Only the first capture of each sequence, along with individual loose photos, remains in the source folder. This creates a clean visual overview and secures a complete set of images for stitching a standard (non-HDR) panorama should the HDR processing yield undesirable results (e.g., due to 'ghosting').

2. **Batch HDR Production:** All identified sequences are processed sequentially into HDR files. Options include TIFF files (via Enfuse) or 32-bit DNG files (via HDRmerge). Processing occurs serially per folder to prevent system overload while utilizing all available processor threads for calculations.

3. **Collection and Cleanup:** Completed HDR results are moved to a central folder named 'Verzamelde_HDR_bestanden', located one level above the working directory. If the option is enabled, temporary folders containing RAW files are deleted following successful processing.

**The XMP Profile (oppepper.xmp)**

The use of an XMP profile is **only required for the TIFF method (Enfuse)**. When using the DNG method (HDRmerge), this file is ignored.

* **Purpose of the profile:** The profile is used to apply basic corrections during the RAW-to-TIFF conversion. The primary objective is to apply **lens correction**. Correcting lens distortions beforehand allows for more accurate image alignment. Additionally, modules such as 'Sigmoid' and 'Local Contrast' can be utilized to pre-optimize the distribution of the dynamic range.

**Installation Instructions (Linux/Arch Linux)**

1. **Software Dependencies: \**
The following packages must be present on the system. Installation can be performed via the terminal (Arch Linux example):

sudo pacman -S pyside6 perl-image-exiftool darktable hugin enblend-enfuse hdrmerge xdg-desktop-portal-kde

1. **Preparing the XMP Profile: \**
Follow these steps in the Darktable GUI to create 'oppepper.xmp':

* Open a RAW photo.

* Clear the entire history in the 'History' panel.

* Set the 'White Balance' module to 'Camera'.

* Disable the 'Color Calibration' module entirely to prevent color shifts between different camera brands.

* Enable 'Lens Correction' and desired contrast modules.

* Export these settings as 'oppepper.xmp' to the script directory.

1. **Execution: \**
Make the script executable and launch the application:

chmod +x workflow_hdr.py \
./workflow_hdr.py

