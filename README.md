README 
PanoStack is an automated high-performance HQ RAW workflow utility for professional photographers. 

1. Sorting Tab (The Foundation) 
HDR Gap: Max time (s) between bracketed shots with different exposure settings. 
Burst Gap: Max time (s) between shots with identical exposures (panoramas/bursts). Default: 3.0s. 
Copy 1st frame: Enables a Non-HDR Workflow. By keeping a reference of the first frame in the root, you can stitch a fast preview panorama without waiting for HDR stacking. 

2. Stacking & Noise Reduction 
HDR Stacking: Combine brackets into high-quality 16-bit TIFF files via Enfuse. This preserves maximum detail for stitching. 
Burst Stacking: Handheld noise reduction via median pixel evaluation (8-16 frames recommended). Excellent for low-light shots without a tripod. 
Dual Progress: Total progress (upper bar) and individual file progress (lower bar) are displayed. 

3. Panorama Tab & Engines 
Engines: 
16-bit Hugin CLI: Professional quality, automatic leveling, and best for high-res output. 
Ultra-HQ OpenCV (8-bit): Extremely fast engine for quick previews or standard panoramas. 

System Dependencies (Arch Linux) 
sudo pacman -S darktable hugin enblend-enfuse perl-image-exiftool imagemagick pyside6 python-opencv python-numpy 
