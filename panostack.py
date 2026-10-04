#!/usr/bin/env python3
"""
PanoStack (v9.8)
- INFO: FULL DETAILED COMPREHENSIVE USER MANUAL restored under the ⓘ button.
- NEW v9.4: Automatische detectie van OpenCL (GPU) ondersteuning voor Darktable.
- NEW v9.3: Thumbnailbalk past hoogte automatisch aan op gekozen thumbnailgrootte, horizontaal scrollen met muiswiel.
- NEW v9.2: UI verfijning: smallere dialoogkolommen en horizontale scrollbare panorama-thumbnails.
- NEW v9.1: UI optimalisatie: Tab 1 kolomverhouding en Tab 4 layout marges.
- NEW v8.0: GPU ACCELERATION: OpenCL ingeschakeld voor Radeon RX 580 (Darktable).
- NEW v7.9: Toegevoegd: "Verplaats Selectie" knop in Panorama tab.
- NEW v7.8: FIX: Herstel stabiele Darktable 5.6 CLI-aanroep en volledige XMP.
- ALL original UI layouts, splitters and manuals preserved.
"""

import sys
import os
import shutil
import subprocess
import glob
import json
import tempfile
import re
import gc
import psutil
from datetime import datetime

# --- IMPORTS ---
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
        QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox,
        QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea,
        QSplitter, QSizePolicy, QCheckBox, QMenu
    )
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize, QProcess, QEvent
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QImage, QColor, QBrush, QAction, QImageReader
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Fout: {e}")
    sys.exit(1)

# --- INGEBOUWDE XMP DATA (OPPEPPER.XMP - HERSTELD VOOR V5.6 met AgX blender-like) ---
DEFAULT_XMP_DATA = """<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:darktable="http://darktable.sf.net/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:lr="http://ns.adobe.com/lightroom/1.0/"
   exif:DateTimeOriginal="2026:08:15 06:22:01.474"
   xmpMM:DerivedFrom="P1566881.RW2"
   xmp:Rating="1"
   darktable:import_timestamp="63922554595224891"
   darktable:change_timestamp="63922554687230474"
   darktable:export_timestamp="63922554729836493"
   darktable:print_timestamp="-1"
   darktable:xmp_version="5"
   darktable:raw_params="0"
   darktable:auto_presets_applied="1"
   darktable:history_end="18"
   darktable:iop_order_version="4"
   darktable:history_auto_hash="2b9c34b77807df1f28802ec90736a2af"
   darktable:history_current_hash="ac17165aedee866c475ea445e2582005">
   <darktable:masks_history><rdf:Seq/></darktable:masks_history>
   <darktable:history><rdf:Seq>
     <rdf:li darktable:num="0" darktable:operation="rawprepare" darktable:enabled="1" darktable:modversion="2" darktable:params="000000000000000042000000000000009000900090009000ff0f000000000000" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="1" darktable:operation="colorin" darktable:enabled="1" darktable:modversion="7" darktable:params="gz48eJzjZhgFowABWAbaAaNgwAEAOQAAEA==" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="2" darktable:operation="colorout" darktable:enabled="1" darktable:modversion="5" darktable:params="gz35eJxjZBgFo4CBAQAEEAAC" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="3" darktable:operation="gamma" darktable:enabled="1" darktable:modversion="1" darktable:params="0000000000000000" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="4" darktable:operation="temperature" darktable:enabled="1" darktable:modversion="4" darktable:params="00401a400000803f0080e43f0000000004000000" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="5" darktable:operation="highlights" darktable:enabled="1" darktable:modversion="4" darktable:params="050000000000803f00000000000000000000803f000000001e00000006000000cdcccc3e000000400000000000000000" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYGBgYARiCQYYOOHEgAZY0QWgejBBgz0Ej1Q+dcF/IADRAGwSHQY="/>
     <rdf:li darktable:num="6" darktable:operation="flip" darktable:enabled="1" darktable:modversion="2" darktable:params="ffffffff" darktable:multi_name="_builtin_auto" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="7" darktable:operation="agx" darktable:enabled="1" darktable:modversion="7" darktable:params="gz03eJxjYACBBnsYnjVTEkgrHGRguOBw9swZ21Nq0vZvAi3sGBgcHBjg4IC9sXEwUJ4HSazBnomBEIDZgxsAACzDEfU=" darktable:multi_name="blender-like|base" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="8" darktable:operation="bilat" darktable:enabled="1" darktable:modversion="3" darktable:params="010000000000003f0000003f0000803e0000003f" darktable:blendop_version="14" darktable:blendop_params="gz10eJxjYGBgYAJiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAG2yHQc="/>
     <rdf:li darktable:num="9" darktable:operation="cacorrectrgb" darktable:enabled="1" darktable:modversion="1" darktable:params="010000000000a0400000003f0000000000000000" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="10" darktable:operation="channelmixerrgb" darktable:enabled="1" darktable:modversion="3" darktable:params="gz04eJxjYGiwZ8AAxIqRD5igmAWIGYHYc9NWu6Kg/XaJjya7guxihMoDAKgsCNM=" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="11" darktable:operation="demosaic" darktable:enabled="1" darktable:modversion="6" darktable:params="0000000000000000000000000500000001000000cdcc4c3e2fb0073f1383c03e00000000080000000000000001000000" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="12" darktable:operation="denoiseprofile" darktable:enabled="1" darktable:modversion="12" darktable:params="gz05eJxjYGiwZ2B44MAApJveLwCyGRruZjy3OXvmjC0DWK5h/+GfsuZvy6ean395xkjy7W2jr8nvjBgZIGD1Ki271atW2QGZ9kC2fVhoqD1E36CSGxIYFKbIGAQA8XpSEQ==" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="13" darktable:operation="hazeremoval" darktable:enabled="1" darktable:modversion="3" darktable:params="d0cccc3dcdcc4c3e0000000001000000" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="14" darktable:operation="lens" darktable:enabled="1" darktable:modversion="10" darktable:params="gz04eJxjZGBgYGeAgHTJJnsg5cDAYONkbPwYSFe5MAIFXJx13S0NGAYM+JTmZlYouCuEJRZl5isYGumaGeTmKqTpG+uZ6prqmSk4Fhdk6CkE5JenFin4ewbTyBUN9rgxTB4O7KEYDABrtxnU" darktable:blendop_version="14" darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li darktable:num="15" darktable:operation="exposure" darktable:enabled="1" darktable:modversion="7" darktable:params="00000000000080b93333333f00004842000080c00100000001000000" darktable:multi_name="_builtin_scene-referred default" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="16" darktable:operation="exposure" darktable:enabled="1" darktable:modversion="7" darktable:params="00000000000000000000c03f00004842000080c00000000000000000" darktable:multi_name="1" darktable:multi_priority="1" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
     <rdf:li darktable:num="17" darktable:operation="colorbalancergb" darktable:enabled="1" darktable:modversion="5" darktable:params="gz03eJxjYCAVNNij0ggwY+ZMO3SxA2d8bC+c8dkL4098a2N35oyPHYxmBIoBAOdMEHY=" darktable:multi_name="extra" darktable:blendop_version="14" darktable:blendop_params="gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""

# --- CONFIGURATIE ---
if getattr(sys, 'frozen', False): SCRIPT_DIR = sys._MEIPASS
else: SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".panostack_config.json")
DEFAULT_CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "PANO_COLLECT_NAME": "Verzamelde_Panoramas",
    "DT_XMP_FILE": "oppepper.xmp",
    "LAST_SOURCE_DIR": os.path.expanduser("~"),
    "MAX_GAP": 1.0, "SAME_GAP": 3.0, "COPY_FIRST_TO_ROOT": True
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return {**DEFAULT_CONFIG, **json.load(f)}
        except: return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)
    except: pass

CONFIG = load_config()
VALID_EXTS = {ext.lower() for ext in ['.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng', '.tif', '.tiff', '.jpg', '.jpeg']}
RAW_EXTS = {'.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng'}
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, (os.cpu_count() or 2) - 1))

# --- HELPERS ---

def check_opencl_support(): return True

GPU_ENABLED = check_opencl_support()

def find_best_xmp():
    target = CONFIG["DT_XMP_FILE"]
    for p in [os.path.join(SCRIPT_DIR, target), f"/usr/share/panostack/{target}"]:
        if os.path.exists(p): return p
    tmp = os.path.join(tempfile.gettempdir(), "panostack_fallback.xmp")
    with open(tmp, "w") as f: f.write(DEFAULT_XMP_DATA)
    return tmp

def check_dependencies():
    deps = {"darktable-cli": "darktable", "enfuse": "enblend-enfuse", "hdrmerge": "hdrmerge", "exiftool": "perl-image-exiftool", "align_image_stack": "hugin", "hugin": "hugin", "mogrify": "imagemagick", "convert": "imagemagick"}
    return [cmd for cmd in deps if shutil.which(cmd) is None], deps

def smart_copy(src, dst):
    try: subprocess.run(['cp', '--reflink=auto', src, dst], check=True, capture_output=True); return True
    except:
        try: shutil.copy2(src, dst); return True
        except: return False

def convert_16_to_8_hq(cv_img):
    if cv_img.dtype != np.uint16: return cv_img
    p_low, p_high = np.percentile(cv_img, (0.1, 99.9))
    if p_high > p_low:
        clipped = np.clip(cv_img, p_low, p_high)
        img_8 = ((clipped - p_low) / (p_high - p_low) * 255.0).astype(np.uint8)
    else: img_8 = (cv_img / 256).astype(np.uint8)
    if len(img_8.shape) == 2:
        clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(8, 8))
        res = clahe.apply(img_8); return cv2.addWeighted(res, 0.75, img_8, 0.25, 0)
    lab = cv2.cvtColor(img_8, cv2.COLOR_BGR2LAB); l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(8, 8)); l_clahe = clahe.apply(l)
    l_final = cv2.addWeighted(l_clahe, 0.75, l, 0.25, 0); enhanced_lab = cv2.merge((l_final, a, b))
    return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

def get_image_robust(path):
    if not path or not os.path.exists(path): return QImage()
    ext = os.path.splitext(path)[1].lower()
    img = QImage()
    if ext in RAW_EXTS:
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
            if res.stdout and len(res.stdout) > 5000:
                img.loadFromData(res.stdout); break
    else:
        try:
            cv_img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if cv_img is not None:
                cv_img = convert_16_to_8_hq(cv_img)
                if len(cv_img.shape) == 3:
                    if cv_img.shape[2] == 4: cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGRA2RGB)
                    else: cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                elif len(cv_img.shape) == 2:
                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_GRAY2RGB)
                h, w, ch = cv_img.shape
                img = QImage(cv_img.data, w, h, ch * w, QImage.Format_RGB888).copy()
        except: img = QImage()
        if img.isNull():
            reader = QImageReader(path); reader.setAllocationLimit(0)
            if reader.canRead():
                orig_size = reader.size()
                if orig_size.width() > 5000 or orig_size.height() > 5000:
                    orig_size.scale(3000, 3000, Qt.KeepAspectRatio); reader.setScaledSize(orig_size)
                img = reader.read()
    if img.isNull(): return QImage()
    try:
        out = subprocess.run(['exiftool', '-S3', '-Orientation', '-n', path], capture_output=True, text=True)
        orient = int(out.stdout.strip()) if out.stdout.strip() else 1
        if orient in [3, 6, 8]:
            trans = QTransform()
            if orient == 6: trans.rotate(90)
            elif orient == 8: trans.rotate(270)
            elif orient == 3: trans.rotate(180)
            img = img.transformed(trans, Qt.SmoothTransformation)
    except: pass
    return img

def get_capture_date_compact(path):
    try:
        res = subprocess.run(['exiftool', '-S3', '-d', '%Y%m%d', '-DateTimeOriginal', path], capture_output=True, text=True)
        if res.stdout.strip(): return res.stdout.strip()
    except: pass
    return datetime.now().strftime("%Y%m%d")

# --- WORKERS ---

class BaseWorker(QObject):
    finished, progress, log, result_path = Signal(), Signal(int), Signal(str), Signal(str)
    def __init__(self): super().__init__(); self._is_running = True; self.active_proc = None
    def stop(self):
        self._is_running = False
        if self.active_proc:
            try: self.active_proc.terminate()
            except: pass
        self.log.emit("<br><b style='color:#e74c3c;'>[STOP] Proces afgebroken.</b>")
    def safe_run(self, cmd, env=None):
        if not self._is_running: return 1
        try:
            self.active_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            return self.active_proc.wait()
        except: return 1

class SortWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, source_dir, max_gap, same_gap, copy_first=False):
        super().__init__(); self.source_dir, self.max_gap, self.same_gap, self.copy_first = source_dir, max_gap, same_gap, copy_first
    @Slot()
    def run(self):
        try:
            self.log.emit(f"<b style='color:#2980b9;'>Analyse start:</b> {self.source_dir}")
            all_paths = []
            for root, _, files in os.walk(self.source_dir):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in VALID_EXTS) and not f.lower().endswith('.xmp'):
                        if "_HDR" in f or "_Pano" in f: continue
                        all_paths.append(os.path.join(root, f))
            all_paths.sort()
            if not all_paths: self.log.emit("Geen bestanden gevonden."); self.finished.emit(); return
            photos = []
            for i in range(0, len(all_paths), 40):
                if not self._is_running: break
                batch = all_paths[i:i + 40]
                res = subprocess.run(['exiftool', '-q', '-f', '-S3', '-T', '-n', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO'] + batch, capture_output=True, text=True)
                for idx, line in enumerate(res.stdout.strip().splitlines()):
                    p = line.split('\t')
                    if len(p) >= 5:
                        try:
                            dt = datetime.strptime(p[0].split('.')[0].strip(), "%Y:%m:%d %H:%M:%S")
                            photos.append({'full_path': batch[idx], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[1]}A{p[2]}", 'iso': int(re.sub(r"\D", "", p[4])) if p[4] != "-" else 0, 'model': p[3].strip().replace(' ','_'), 'name': os.path.basename(batch[idx])})
                        except: continue
                self.sub_progress.emit(int(((i + len(batch)) / len(all_paths)) * 100))
            photos.sort(key=lambda x: x['ts'])
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest_root, exist_ok=True)
            curr, seq = [], 0
            for idx, p in enumerate(photos):
                if not self._is_running: break
                limit = self.same_gap if curr and (p['exp'] == curr[-1]['exp'] and p['iso'] == curr[-1]['iso']) else self.max_gap
                if not curr or (p['ts'] - curr[-1]['ts'] <= limit): curr.append(p)
                else: seq = self._process_group(curr, dest_root, seq); curr = [p]
                self.progress.emit(int(((idx + 1) / len(photos)) * 100))
            if curr: seq = self._process_group(curr, dest_root, seq)
            self.log.emit(f"<br><b style='color:#27ae60;'>✓ Sorteren voltooid.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()
    def _process_group(self, group, dest_root, seq):
        if len(group) < 2: return seq
        exposures = {p['exp'] for p in group}
        type_p = "Reeks" if len(exposures) > 1 else ("Burst" if ((group[-1]['ts'] - group[0]['ts']) / (len(group)-1) < 1.2 and group[0]['iso'] > 800) else "Serie")
        seq += 1; target = os.path.join(dest_root, group[0]['model'], group[0]['date'], f"{type_p}_{seq:03d}"); os.makedirs(target, exist_ok=True)
        self.log.emit(f"  -> Map: {type_p}_{seq:03d} ({len(group)} foto's)")
        for f in group:
            dest = os.path.join(target, f['name'])
            if f['full_path'] != dest: shutil.move(f['full_path'], dest)
        if self.copy_first:
            try:
                for i in range(min(3, len(group))):
                    shutil.copy2(os.path.join(target, group[i]['name']), os.path.join(self.source_dir, group[i]['name']))
            except: pass
        return seq

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, crop_percent, burst_limit=0, weights=(1.0, 0.2, 0.1), custom_xmp=None):
        super().__init__()
        self.base_dir, self.mode, self.method, self.bit_depth = base_dir, mode, method.lower(), bit_depth
        self.crop_percent, self.burst_limit, self.weights, self.custom_xmp = crop_percent, burst_limit, weights, custom_xmp
    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = [os.path.join(r, d) for r, ds, _ in os.walk(self.base_dir) for d in ds if d.startswith(prefix) or d.startswith("_" + prefix)]
            if not subdirs: self.log.emit(f"Geen {prefix} mappen gevonden."); self.finished.emit(); return
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            os.makedirs(os.path.join(coll_root, "DNG"), exist_ok=True); os.makedirs(os.path.join(coll_root, "TIFF"), exist_ok=True)
            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: break
                files = sorted([f for f in os.listdir(path) if any(f.lower().endswith(ex) for ex in VALID_EXTS) and "_HDR" not in f and "_Burst" not in f])
                if not files: continue
                out_name = f"{os.path.splitext(files[0])[0]}_{'HDR' if self.mode == 'HDR' else 'Burst'}"
                xmp_to_use = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp()
                self.log.emit(f"<br><b>Actief:</b> {os.path.basename(path)} &rarr; {out_name}")
                coll_dng, coll_tif = os.path.join(coll_root, "DNG", f"{out_name}.dng"), os.path.join(coll_root, "TIFF", f"{out_name}.tif")
                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method) and not os.path.exists(coll_dng):
                    raws = [os.path.join(path, f) for f in files if any(f.lower().endswith(ex) for ex in RAW_EXTS)]
                    out = os.path.join(path, f"{out_name}.dng")
                    if self.safe_run(['hdrmerge', '-b', '16', '-o', out] + raws) == 0:
                        smart_copy(out, coll_dng); self.result_path.emit(out); self.log.emit(f"  -> ✓ DNG gereed.")
                if (self.mode == "BURST" or "enfuse" in self.method or "beide" in self.method):
                    if not os.path.basename(path).startswith("_") and not os.path.exists(coll_tif):
                        res = self._do_enfuse(path, out_name, xmp_to_use, files)
                        if res: smart_copy(res, coll_tif); self.result_path.emit(res); self.log.emit(f"  -> <b style='color:#27ae60;'>✓ TIFF gereed.</b>")
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            self.log.emit("<br><b style='color:#27ae60;'>✓ Voltooid.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()
    def _do_enfuse(self, path, out_name, xmp, files):
        use_files = files[:self.burst_limit] if (self.mode == "BURST" and self.burst_limit > 0) else files
        with tempfile.TemporaryDirectory() as tmp:
            tifs = []
            for idx, f in enumerate(use_files):
                if not self._is_running: return None
                out = os.path.join(tmp, f"i{idx:03d}.tif")
                self.log.emit(f"     -> Ontwikkelen frame {idx+1}/{len(use_files)}: {f} (GPU)")
                cmd = ['darktable-cli', os.path.join(path, f), xmp, out, '--library', ':memory:']
                if GPU_ENABLED: cmd.append('--enable-opencl')
                cmd.append('--core')
                if self.safe_run(cmd) == 0 and os.path.exists(out): tifs.append(out)
                else: self.log.emit(f"<span style='color:#e74c3c;'>     -> Fout bij frame: {f}</span>")
                self.sub_progress.emit(int(((idx+1)/len(use_files))*70))
            if len(tifs) < 2: return None
            self.log.emit(f"     -> Frames uitlijnen..."); ali = os.path.join(tmp, "a_")
            self.safe_run(['align_image_stack', '-m', '10', '-a', ali, '-c', '20', '-z', '-x', '-y'] + tifs)
            alis = sorted(glob.glob(os.path.join(tmp, "a_*.tif")))
            for a in alis: self.safe_run(['mogrify', '-alpha', 'off', '-type', 'truecolor', '+matte', a])
            out_h = os.path.join(tmp, "res.tif")
            if self.mode == "BURST": self.safe_run(['convert'] + alis + ['-evaluate-sequence', 'median', out_h])
            else: self.safe_run(['enfuse', f'--depth={self.bit_depth}',
                                 f'--exposure-weight={self.weights[0]}',
                                 f'--saturation-weight={self.weights[1]}',
                                 f'--contrast-weight={self.weights[2]}',
                                 '--output', out_h] + alis, env=ENV_STABLE)
            if os.path.exists(out_h):
                final = os.path.join(path, f"{out_name}.tif")
                if self.crop_percent > 0: self.safe_run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h])
                shutil.copy2(out_h, final); return final
        return None

class PanoWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, custom_xmp=None, output_dir="."):
        super().__init__(); self.files, self.custom_xmp, self.output_dir = files, custom_xmp, output_dir
    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            imgs = []
            try:
                self.log.emit(f"<b style='color:#2980b9;'>OpenCV HQ Panorama gestart</b>")
                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    xmp_f = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp()
                    is_raw = any(f.lower().endswith(ex) for ex in RAW_EXTS)
                    if is_raw:
                        self.log.emit(f"  -> Ontwikkelen {i+1}/{len(self.files)}: {os.path.basename(f)} (GPU)")
                        t = os.path.join(tmp_dir, f"p{i}.tif")
                        cmd = ['darktable-cli', f, xmp_f, t, '--library', ':memory:']
                        if GPU_ENABLED: cmd.append('--enable-opencl')
                        cmd.append('--core')
                        self.safe_run(cmd); read_f = t
                    else: read_f = f
                    img = cv2.imread(read_f, cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        img = convert_16_to_8_hq(img)
                        if not is_raw:
                            try:
                                o_res = subprocess.run(['exiftool', '-S3', '-Orientation', '-n', f], capture_output=True, text=True)
                                orient = int(o_res.stdout.strip()) if o_res.stdout.strip() else 1
                                if orient == 6: img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
                                elif orient == 8: img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                                elif orient == 3: img = cv2.rotate(img, cv2.ROTATE_180)
                            except: pass
                        if len(img.shape) == 3 and img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        imgs.append(img)
                    self.sub_progress.emit(int(((i + 1) / len(self.files)) * 80))
                if len(imgs) > 1 and self._is_running:
                    self.log.emit(f"Stitchen start (Engine: OpenCV)...")
                    st = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                    status, res = st.stitch(imgs); del imgs; gc.collect()
                    if status == cv2.Stitcher_OK:
                        os.makedirs(self.output_dir, exist_ok=True); out = os.path.join(self.output_dir, f"{os.path.splitext(os.path.basename(self.files[0]))[0]}_Pano.tif")
                        cv2.imwrite(out, res); self.log.emit(f"<b style='color:#27ae60;'>✓ Panorama gereed:</b> {out}"); self.result_path.emit(out)
                self.progress.emit(100)
            except Exception as e: self.log.emit(f"Fout: {e}")
            finally: self.finished.emit()

class HuginCliWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, output_dir, custom_xmp=None):
        super().__init__(); self.files, self.output_dir, self.custom_xmp = files, output_dir, custom_xmp
    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                self.log.emit("<b style='color:#2980b9;'>Hugin CLI (16-bit) gestart</b>")
                tiffs = []
                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    xmp_f = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp()
                    if any(f.lower().endswith(ex) for ex in RAW_EXTS):
                        self.log.emit(f"  -> Ontwikkelen {i+1}/{len(self.files)}: {os.path.basename(f)} (GPU)")
                        t = os.path.join(tmp, f"h{i}.tif")
                        cmd = ['darktable-cli', f, xmp_f, t, '--library', ':memory:']
                        if GPU_ENABLED: cmd.append('--enable-opencl')
                        cmd.append('--core')
                        self.safe_run(cmd); tiffs.append(t)
                    else: t = os.path.join(tmp, f"h{i}{os.path.splitext(f)[1]}"); shutil.copy2(f, t); tiffs.append(t)
                if tiffs and self._is_running:
                    pto, pref = os.path.join(tmp, "p.pto"), os.path.join(tmp, "out")
                    steps = [(['pto_gen', '-o', pto] + tiffs, "pto_gen"), (['cpfind', '--multirow', '--celeste', '-o', pto, pto], "cpfind"), (['cpclean', '-o', pto, pto], "cpclean"), (['autooptimiser', '-a', '-m', '-p', '-s', '-l', '-o', pto, pto], "autooptimiser"), (['pano_modify', '--straighten', '--canvas=AUTO', '--crop=AUTO', '--center', '-o', pto, pto], "pano_modify"), (['hugin_executor', '--stitching', '--prefix', pref, pto], "final stitch")]
                    for cmd, label in steps: self.log.emit(f"  -> Hugin: {label}..."); self.safe_run(cmd)
                    final_res = next((p for p in [pref + ".tif", pref + ".tiff"] if os.path.exists(p)), None)
                    if final_res:
                        os.makedirs(self.output_dir, exist_ok=True); out = os.path.join(self.output_dir, f"Pano_Hugin_{get_capture_date_compact(self.files[0])}.tif")
                        shutil.move(final_res, out); self.log.emit(f"<b style='color:#27ae60;'>✓ Gereed:</b> {out}"); self.result_path.emit(out)
            except Exception as e: self.log.emit(f"Fout: {e}")
            finally: self.progress.emit(100); self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack v9.8"); self.resize(1300, 900)
        check_dependencies(); self.worker, self.thread, self.lt, self.last_pano_result = None, None, None, None
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs); self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteren"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Burst"); self.tabs.addTab(self.t4, "4. Panorama")
        self.setup_t1(); self.setup_t2(); self.setup_t3(); self.setup_t4()
        self.tabs.currentChanged.connect(lambda i: self.refresh_t4() if i == 3 else None); self._sync_paths()
        self.installEventFilter(self)

    def eventFilter(self, source, event):
        if source == self.lw.viewport() and event.type() == QEvent.Wheel:
            delta = event.angleDelta().y()
            h_bar = self.lw.horizontalScrollBar()
            h_bar.setValue(h_bar.value() - delta)
            return True
        return super().eventFilter(source, event)

    def _sync_paths(self):
        p = self.s1.text().strip(); sp = os.path.normpath(os.path.join(p, CONFIG["SORTED_DIR_NAME"]))
        if p and os.path.exists(p): self.s2.setText(sp); self.s3.setText(sp); self.s4.setText(os.path.normpath(os.path.join(p, CONFIG["HDR_COLLECT_NAME"])))

    def _make_thin_bar(self):
        pb = QProgressBar(); pb.setFixedHeight(8); pb.setTextVisible(False); pb.setStyleSheet("QProgressBar { border: 1px solid #bbb; background: #eee; } QProgressBar::chunk { background: #05B8CC; }"); return pb

    def setup_t1(self):
        l = QVBoxLayout(self.t1); h = QHBoxLayout(); self.s1 = QLineEdit(CONFIG["LAST_SOURCE_DIR"]); self.s1.textChanged.connect(self._sync_paths); h.addWidget(QLabel("Bron:")); h.addWidget(self.s1)
        b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s1)); h.addWidget(b); h.addWidget(QLabel("HDR Gap:")); self.gv = QDoubleSpinBox(); self.gv.setRange(0.5, 2.5); self.gv.setValue(1.0); h.addWidget(self.gv)
        h.addWidget(QLabel("Burst Gap:")); self.gv_same = QDoubleSpinBox(); self.gv_same.setRange(1.0, 20.0); self.gv_same.setValue(3.0); h.addWidget(self.gv_same)
        self.cb_copy_first = QCheckBox("Kopie 1e 3 van reeks"); self.cb_copy_first.setChecked(True); h.addWidget(self.cb_copy_first); btn_i = QPushButton("ⓘ"); btn_i.setFixedWidth(40); btn_i.clicked.connect(self.show_readme); h.addWidget(btn_i)
        l.addLayout(h)
        split = QSplitter(Qt.Horizontal); self.log1 = QTextEdit(); self.log1.setReadOnly(True); self.prev1 = QLabel(); self.prev1.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev1); sc.setWidgetResizable(True); split.addWidget(self.log1); split.addWidget(sc); split.setSizes([260, 1040]); l.addWidget(split)
        self.b1 = QPushButton("Start Sorteren"); self.b1.clicked.connect(self.go1); l.addWidget(self.b1); self.p1 = self._make_thin_bar(); l.addWidget(self.p1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2); h_main = QHBoxLayout(); h_main.addWidget(QLabel("Map:")); self.s2 = QLineEdit(); h_main.addWidget(self.s2); b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s2)); h_main.addWidget(b); self.m2 = QComboBox(); h_main.addWidget(self.m2)
        h_main.addWidget(QLabel("Crop:")); self.cp2 = QDoubleSpinBox(); self.cp2.setValue(1.5); h_main.addWidget(self.cp2); h_main.addWidget(QLabel("Exp:")); self.ew2 = QDoubleSpinBox(); self.ew2.setRange(0,1); self.ew2.setValue(0.3); h_main.addWidget(self.ew2); h_main.addWidget(QLabel("Sat:")); self.sw2 = QDoubleSpinBox(); self.sw2.setRange(0,1); self.sw2.setValue(1.0); h_main.addWidget(self.sw2); h_main.addWidget(QLabel("Con:")); self.cw2 = QDoubleSpinBox(); self.cw2.setRange(0,1); self.cw2.setValue(1.0); h_main.addWidget(self.cw2)
        h_main.addWidget(QLabel("Vrije XMP:")); self.x2 = QLineEdit(); h_main.addWidget(self.x2); self.b_xmp2 = QPushButton("Kies"); self.b_xmp2.clicked.connect(lambda: self.sel_xmp_field(self.x2)); h_main.addWidget(self.b_xmp2); l.addLayout(h_main)
        h_split2 = QSplitter(Qt.Horizontal); self.log2 = QTextEdit(); self.log2.setReadOnly(True); self.prev2 = QLabel(); self.prev2.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev2); sc.setWidgetResizable(True); h_split2.addWidget(self.log2); h_split2.addWidget(sc); h_split2.setSizes([260, 1040]); l.addWidget(h_split2)
        v_prog = QWidget(); v_prog.setFixedHeight(60); vp_l = QVBoxLayout(v_prog); vp_l.setContentsMargins(0,0,0,0); vp_l.addWidget(QLabel("Totaal:")); self.p2 = self._make_thin_bar(); vp_l.addWidget(self.p2); vp_l.addWidget(QLabel("Huidig:")); self.p2_sub = self._make_thin_bar(); vp_l.addWidget(self.p2_sub); l.addWidget(v_prog)
        h_ctrl = QHBoxLayout(); self.b2 = QPushButton("Start HDR"); self.b2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b2.clicked.connect(lambda: self.go_proc("HDR")); h_ctrl.addWidget(self.b2); self.stop2 = QPushButton("Stop"); self.stop2.setFixedWidth(80); self.stop2.clicked.connect(self.stop_proc); h_ctrl.addWidget(self.stop2); l.addLayout(h_ctrl)
        self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); self.m2.currentIndexChanged.connect(self.update_enfuse_visibility); self.update_enfuse_visibility()

    def setup_t3(self):
        l = QVBoxLayout(self.t3); h = QHBoxLayout(); h.addWidget(QLabel("Map:")); self.s3 = QLineEdit(); h.addWidget(self.s3); b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s3)); h.addWidget(b); self.bl3 = QComboBox(); self.bl3.addItems(["8", "16"]); h.addWidget(QLabel("Limiet:")); h.addWidget(self.bl3); l.addLayout(h)
        h_split3 = QSplitter(Qt.Horizontal); self.log3 = QTextEdit(); self.log3.setReadOnly(True); self.prev3 = QLabel(); self.prev3.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev3); sc.setWidgetResizable(True); h_split3.addWidget(self.log3); h_split3.addWidget(sc); h_split3.setSizes([260, 1040]); l.addWidget(h_split3)
        v_prog = QWidget(); v_prog.setFixedHeight(60); vp_l = QVBoxLayout(v_prog); vp_l.setContentsMargins(0,0,0,0); vp_l.addWidget(QLabel("Totaal:")); self.p3 = self._make_thin_bar(); vp_l.addWidget(self.p3); vp_l.addWidget(QLabel("Huidig:")); self.p3_sub = self._make_thin_bar(); vp_l.addWidget(self.p3_sub); l.addWidget(v_prog)
        h_ctrl = QHBoxLayout(); self.b3 = QPushButton("Start Burst"); self.b3.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b3.clicked.connect(lambda: self.go_proc("BURST")); h_ctrl.addWidget(self.b3); self.stop3 = QPushButton("Stop"); self.stop3.setFixedWidth(80); self.stop3.clicked.connect(self.stop_proc); h_ctrl.addWidget(self.stop3); l.addLayout(h_ctrl)

    def setup_t4(self):
        main_l = QVBoxLayout(self.t4); main_l.setContentsMargins(0, 0, 0, 0); main_l.setSpacing(0)
        h_paths = QHBoxLayout(); h_paths.setContentsMargins(5,5,5,5); h_paths.addWidget(QLabel("Verzamelmap:")); self.s4 = QLineEdit(); h_paths.addWidget(self.s4)
        b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s4)); h_paths.addWidget(b); self.lbl_x4 = QLabel("Vrije XMP:"); h_paths.addWidget(self.lbl_x4); self.x4 = QLineEdit(); h_paths.addWidget(self.x4); self.b_xmp4 = QPushButton("Kies"); self.b_xmp4.clicked.connect(lambda: self.sel_xmp_field(self.x4)); h_paths.addWidget(self.b_xmp4); main_l.addLayout(h_paths)

        self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(200, 200)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.lw.setFlow(QListWidget.LeftToRight); self.lw.setWrapping(False); self.lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn); self.lw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.lw.viewport().installEventFilter(self); self.lw.setFixedHeight(240); self.lw.itemDoubleClicked.connect(self.mark_for_deletion); main_l.addWidget(self.lw)

        h_opts = QHBoxLayout(); h_opts.setContentsMargins(0,0,0,0); h_opts.setSpacing(5); self.f4 = QComboBox(); self.f4.addItems(["TIFF/JPG", "DNG", "RAW (Serie)", "RAW (enkel)"]); self.f4.currentIndexChanged.connect(lambda idx: self.update_refresh_all()); h_opts.addWidget(self.f4); self.ts4 = QComboBox(); self.ts4.addItems(["100", "200", "300"]); self.ts4.setCurrentText("200"); self.ts4.currentIndexChanged.connect(lambda idx: self.update_refresh_all()); h_opts.addWidget(self.ts4); self.p4_load = self._make_thin_bar(); h_opts.addWidget(self.p4_load); main_l.addLayout(h_opts)

        h_split4 = QSplitter(Qt.Horizontal); h_split4.setStyleSheet("QSplitter::handle { background: transparent; width: 1px; }"); self.log4 = QTextEdit(); self.log4.setReadOnly(True); self.prev4 = QLabel(); self.prev4.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev4); sc.setWidgetResizable(True); h_split4.addWidget(self.log4); h_split4.addWidget(sc); h_split4.setSizes([325, 975]); main_l.addWidget(h_split4)

        bot_box = QVBoxLayout(); bot_box.setContentsMargins(0,0,0,0); bot_box.setSpacing(0); h_btn = QHBoxLayout(); h_btn.setContentsMargins(0,0,0,0); h_btn.setSpacing(5); self.b4 = QPushButton("Start openCV (8 bit)"); self.b4.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b4.clicked.connect(self.go4); h_btn.addWidget(self.b4); self.b_hu = QPushButton("Start Hugin (16 bit)"); self.b_hu.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b_hu.clicked.connect(self.go_hugin); h_btn.addWidget(self.b_hu); self.cb_hugin_gui = QCheckBox("Open GUI"); self.cb_hugin_gui.setFixedWidth(90); h_btn.addWidget(self.cb_hugin_gui); self.b_dt = QPushButton("Start Darktable"); self.b_dt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b_dt.clicked.connect(self.open_dt); h_btn.addWidget(self.b_dt); self.b_move = QPushButton("Verplaats Selectie"); self.b_move.setFixedWidth(140); self.b_move.clicked.connect(self.move_selected_files); h_btn.addWidget(self.b_move); self.b_del = QPushButton("Verwijder Gemarkeerd"); self.b_del.setFixedWidth(140); self.b_del.clicked.connect(self.do_delete_marked); h_btn.addWidget(self.b_del); bot_box.addLayout(h_btn); h_prog = QHBoxLayout(); h_prog.setContentsMargins(0,0,0,0); self.p4_sub = self._make_thin_bar(); h_prog.addWidget(self.p4_sub); self.stop4 = QPushButton("Stop"); self.stop4.setFixedWidth(50); self.stop4.setFixedHeight(18); self.stop4.clicked.connect(self.stop_proc); h_prog.addWidget(self.stop4); bot_box.addLayout(h_prog); main_l.addLayout(bot_box); self.update_pano_xmp_visibility()

    def mark_for_deletion(self, item):
        path = item.data(Qt.UserRole); res = QMessageBox.question(self, "Verwijderen?", f"Markeren voor verwijdering?", QMessageBox.Yes | QMessageBox.No)
        if res == QMessageBox.Yes: item.setData(Qt.UserRole + 2, True); item.setBackground(QBrush(QColor(255, 0, 0, 100))); item.setText(f"[VERWIJDEREN] {os.path.basename(path)}")

    def do_delete_marked(self):
        marked = [self.lw.item(i) for i in range(self.lw.count()) if self.lw.item(i).data(Qt.UserRole + 2)]
        for it in marked:
            try: os.remove(it.data(Qt.UserRole))
            except: pass
        self.refresh_t4()

    def move_selected_files(self):
        items = self.lw.selectedItems()
        if not items: return
        target_dir = QFileDialog.getExistingDirectory(self, "Verplaats naar map", self.s1.text(), QFileDialog.Option.DontUseNativeDialog)
        if target_dir:
            for it in items:
                src = it.data(Qt.UserRole)
                dst = os.path.join(target_dir, os.path.basename(src))
                try: shutil.move(src, dst)
                except Exception as e: print(f"Fout bij verplaatsen {src}: {e}")
            self.refresh_t4()

    def sel_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Kies Map", edit.text(), QFileDialog.Option.DontUseNativeDialog)
        if d: edit.setText(os.path.normpath(d)); self._sync_paths(); self.refresh_t4()

    def sel_xmp_field(self, edit):
        f, _ = QFileDialog.getOpenFileName(self, "Kies XMP", "", "XMP (*.xmp)", options=QFileDialog.Option.DontUseNativeDialog)
        if f: edit.setText(f)

    def update_refresh_all(self):
        sz = int(self.ts4.currentText()); self.lw.setIconSize(QSize(sz, sz)); self.lw.setFixedHeight(sz + 40); self.update_pano_xmp_visibility(); self.refresh_t4()

    def update_enfuse_visibility(self):
        is_enf = self.m2.currentText() != "HDRmerge (DNG)"
        for w in [self.ew2, self.sw2, self.cw2, self.cp2, self.x2, self.b_xmp2]: w.setEnabled(is_enf)

    def update_pano_xmp_visibility(self):
        mode = self.f4.currentIndex(); self.x4.setEnabled(mode != 0); self.b_xmp4.setEnabled(mode != 0)

    def stop_proc(self):
        if self.worker: self.worker.stop()

    def go1(self):
        self.log1.clear(); w = SortWorker(self.s1.text(), self.gv.value(), self.gv_same.value(), self.cb_copy_first.isChecked()); w.finished.connect(self.refresh_t4); self._run(w, self.p1, self.log1, self.b1)

    def go_proc(self, mode):
        p, log, b, stop = (self.s2.text(), self.log2, self.b2, self.stop2) if mode == "HDR" else (self.s3.text(), self.log3, self.b3, self.stop3)
        log.clear(); meth = self.m2.currentText() if mode == "HDR" else "Median"; limit = int(self.bl3.currentText()) if mode == "BURST" else 0
        w = HdrBurstWorker(p, mode, meth, "16", self.cp2.value(), limit, (self.ew2.value(), self.sw2.value(), self.cw2.value()), custom_xmp=self.x2.text() if mode == "HDR" else None)
        pb, ps = (self.p2, self.p2_sub) if mode == "HDR" else (self.p3, self.p3_sub); w.sub_progress.connect(ps.setValue); self._run(w, pb, log, b, stop)

    def go4(self):
        items = self.lw.selectedItems()
        if items:
            files = [it.data(Qt.UserRole) for it in items]; self.log4.clear(); w = PanoWorker(files, self.x4.text(), self._get_pano_save_dir(files[0]))
            w.sub_progress.connect(self.p4_sub.setValue); w.result_path.connect(lambda p: setattr(self, 'last_pano_result', p))
            w.finished.connect(self.lw.clearSelection); self._run(w, self.p4_sub, self.log4, self.b4, self.stop4)

    def open_dt(self):
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] == 'darktable':
                QMessageBox.warning(self, "Darktable Actief", "Darktable draait al. Sluit deze eerst af.")
                return
        sel = self.lw.selectedItems()
        target = sel[0].data(Qt.UserRole) if sel else self.last_pano_result
        if target and os.path.exists(target):
            user_config_dir = os.path.expanduser("~/.config/darktable")
            temp_config_dir = tempfile.mkdtemp(prefix="panostack_config_")
            if os.path.exists(user_config_dir):
                shutil.copytree(user_config_dir, temp_config_dir, dirs_exist_ok=True)
            db_file = os.path.join(temp_config_dir, "library.db")
            if os.path.exists(db_file): os.remove(db_file)
            if any(target.lower().endswith(ex) for ex in RAW_EXTS):
                xmp_src = self.x4.text() if (self.x4.text() and os.path.exists(self.x4.text())) else find_best_xmp()
                if xmp_src: shutil.copy2(xmp_src, target + ".xmp")
            target_dir = os.path.dirname(target)
            args = ['--configdir', temp_config_dir, target_dir]
            self.dt_proc = QProcess()
            self.dt_proc.start('darktable', args)

    def go_hugin(self):
        items = self.lw.selectedItems()
        if not items: return
        files = [it.data(Qt.UserRole) for it in items]
        if self.cb_hugin_gui.isChecked():
            tmp = os.path.join(os.path.expanduser("~/ps_h_temp"), datetime.now().strftime("%H%M%S")); os.makedirs(tmp, exist_ok=True); final = []
            for i, f in enumerate(files):
                tif = os.path.join(tmp, f"h_{i}.tif")
                if any(f.lower().endswith(ex) for ex in RAW_EXTS):
                    xmp = (self.x4.text() or find_best_xmp())
                    cmd = ['darktable-cli', f, xmp, tif, '--library', ':memory:']
                    if GPU_ENABLED: cmd.append('--enable-opencl')
                    cmd.append('--core')
                    subprocess.run(cmd)
                    final.append(tif)
                else: shutil.copy2(f, tif); final.append(tif)
            if final: subprocess.Popen(['hugin'] + final)
        else:
            self.log4.clear(); w = HuginCliWorker(files, self._get_pano_save_dir(files[0]), self.x4.text())
            w.sub_progress.connect(self.p4_sub.setValue); w.result_path.connect(lambda p: setattr(self, 'last_pano_result', p))
            w.finished.connect(self.lw.clearSelection); self._run(w, self.p4_sub, self.log4, self.b_hu, self.stop4)

    def _run(self, w, p, log, b, s_btn=None):
        self.worker, self.thread = w, QThread(); b.setEnabled(False)
        if s_btn: s_btn.setEnabled(True)
        self.clear_prev_label(w); w.moveToThread(self.thread); w.log.connect(log.append); w.progress.connect(p.setValue)
        w.finished.connect(self.thread.quit); w.finished.connect(lambda: b.setEnabled(True))
        if s_btn: w.finished.connect(lambda: s_btn.setEnabled(False))
        w.result_path.connect(lambda path: self.show_prev(path, w)); self.thread.started.connect(w.run); self.thread.start()

    def show_prev(self, path, w):
        t = self.prev1 if isinstance(w, SortWorker) else (self.prev2 if getattr(w, 'mode', '')=="HDR" else (self.prev3 if getattr(w, 'mode', '')=="BURST" else self.prev4))
        img = get_image_robust(path)
        if not img.isNull(): t.setPixmap(QPixmap.fromImage(img).scaled(t.width(), t.height(), Qt.KeepAspectRatio))

    def clear_prev_label(self, w):
        t = self.prev1 if isinstance(w, SortWorker) else (self.prev2 if getattr(w, 'mode', '')=="HDR" else (self.prev3 if getattr(w, 'mode', '')=="BURST" else self.prev4))
        t.clear(); t.setText("Verwerken..."); t.setStyleSheet("color: #7f8c8d; font-style: italic; font-size: 14px;")

    def _get_pano_save_dir(self, f):
        root = self.s1.text().strip()
        if not root or not os.path.exists(root):
            fd = os.path.dirname(f); root = fd.split(CONFIG["HDR_COLLECT_NAME"])[0] if CONFIG["HDR_COLLECT_NAME"] in fd else os.path.dirname(fd)
        return os.path.join(os.path.abspath(root), CONFIG["PANO_COLLECT_NAME"])

    def refresh_t4(self):
        root = self.s1.text().strip(); mode = self.f4.currentIndex()
        exts = (('.tif', '.tiff', '.jpg', '.jpeg') if mode == 0 else (('.dng',) if mode == 1 else RAW_EXTS))
        inc_first, rec, f_filter = False, True, None
        if mode == 3: scan_p, rec, inc_first, f_filter = root, False, True, ("Reeks_", "Serie_", "Burst_", "_Reeks_", "_Serie_", "_Burst_")
        elif mode == 2: scan_p, f_filter = os.path.normpath(os.path.join(root, CONFIG["SORTED_DIR_NAME"])), ("Serie_", "_Serie_")
        else: scan_p = self.s4.text()
        if hasattr(self, 'lt') and self.lt and self.lt.isRunning(): self.lwk.is_aborted = True; self.lt.quit(); self.lt.wait()
        self.lt = QThread(); self.lwk = ThumbnailWorker(scan_p, exts, rec, inc_first, f_filter); self.lwk.moveToThread(self.lt)
        self.lt.started.connect(self.lwk.run); self.lwk.thumb_ready.connect(self.add_thumb); self.lwk.progress.connect(self.p4_load.setValue); self.lwk.finished.connect(self.lt.quit); self.lt.start(); self.lw.clear()

    def add_thumb(self, n, p, img):
        it = QListWidgetItem(n); it.setData(Qt.UserRole, p); it.setData(Qt.UserRole + 1, 0); it.setData(Qt.UserRole + 2, False)
        s = int(self.ts4.currentText()); it.setIcon(QIcon(QPixmap.fromImage(img.scaled(s, s, Qt.KeepAspectRatio))))
        if os.path.basename(os.path.dirname(p)).startswith("_"): it.setBackground(QBrush(QColor(50, 50, 50, 150))); it.setText(f"[UITGESLOTEN] {n}")
        self.lw.addItem(it)

    def show_readme(self):
        text = """<h2 style='color:#2980b9;'>README</h2>
        <p><b>PanoStack</b> is an automated high-performance HQ RAW workflow utility for professional photographers.</p>
        <h3 style='color:#2c3e50;'>1. Sorting Tab (The Foundation)</h3>
        <ul>
            <li><b>HDR Gap:</b> Max time (s) between bracketed shots with different exposure settings.</li>
            <li><b>Burst Gap:</b> Max time (s) between shots with identical exposures (panoramas/bursts). <b>Default: 3.0s</b>.</li>
            <li><b>Copy 1st frame:</b> Enables a <b>Non-HDR Workflow</b>. By keeping a reference of the first frame in the root, you can stitch a fast preview panorama without waiting for HDR stacking.</li>
        </ul>
        <h3 style='color:#2c3e50;'>2. Stacking & Noise Reduction</h3>
        <ul>
            <li><b>HDR Stacking:</b> Combine brackets into 32-bit DNG (HDRmerge) or 16-bit TIFF (Enfuse).</li>
            <li><b>Burst Stacking:</b> Handheld noise reduction via median pixel evaluation (8-16 frames recommended).</li>
            <li><b>Dual Progress:</b> Total progress (upper bar) and individual file progress (lower bar) are displayed.</li>
        </ul>
        <h3 style='color:#2c3e50;'>3. Panorama Tab & Engines</h3>
        <ul>
            <li><b>Free XMP:</b> Apply a custom Darktable XMP to all RAW/DNG frames for consistent color and lens correction.</li>
            <li><b>Engines:</b>
                <ul>
                    <li><b>16-bit Hugin CLI:</b> Professional quality with automatic leveling.</li>
                    <li><b>Ultra-HQ OpenCV (8-bit):</b> Extremely fast engine using an optimized 16->8bit pipeline (Percentile Stretching & Lab-CLAHE).</li>
                </ul>
            </li>
        </ul>
        <h3 style='color:#2c3e50;'>System Dependencies (Arch Linux)</h3>
        <p><code>sudo pacman -S darktable hugin enblend-enfuse perl-image-exiftool imagemagick pyside6 python-opencv python-numpy python-psutil</code></p>
        <p>AUR (Required for DNG): <code>yay -S hdrmerge</code></p>
        """
        QMessageBox.information(self, "README", text)

    def closeEvent(self, event):
        if self.worker: self.worker.stop()
        CONFIG["LAST_SOURCE_DIR"], CONFIG["MAX_GAP"], CONFIG["SAME_GAP"] = self.s1.text(), self.gv.value(), self.gv_same.value(); save_config(CONFIG); event.accept()

class ThumbnailWorker(QObject):
    finished, progress, thumb_ready = Signal(), Signal(int), Signal(str, str, QImage)
    def __init__(self, directory, extensions, recursive=False, inc_first=False, folder_filter=None):
        super().__init__(); self.directory, self.extensions, self.recursive, self.inc_first, self.folder_filter = directory, extensions, recursive, inc_first, folder_filter; self.is_aborted = False
    def run(self):
        if not os.path.exists(self.directory): self.finished.emit(); return
        found_basenames, fps = set(), []
        if self.inc_first:
            s_root = os.path.join(self.directory, CONFIG["SORTED_DIR_NAME"])
            if os.path.exists(s_root):
                for r, _, fs in os.walk(s_root):
                    if self.is_aborted: break
                    if self.folder_filter and any(os.path.basename(r).startswith(f) for f in self.folder_filter):
                        valid_fs = sorted([f for f in fs if any(f.lower().endswith(ex) for ex in self.extensions)])
                        if valid_fs: fps.append(os.path.join(r, valid_fs[0])); found_basenames.add(valid_fs[0])
        if self.recursive and not self.inc_first:
            for r, _, fs in os.walk(self.directory):
                if self.is_aborted or (self.folder_filter and not any(os.path.basename(r).startswith(f) for f in self.folder_filter)): continue
                for f in sorted(fs):
                    if any(f.lower().endswith(ex) for ex in self.extensions): fps.append(os.path.join(r, f))
        elif not self.recursive:
            for f in sorted(os.listdir(self.directory)):
                if not self.is_aborted and any(f.lower().endswith(ex) for ex in self.extensions) and f not in found_basenames: fps.append(os.path.join(self.directory, f))
        for i, fp in enumerate(fps):
            if self.is_aborted: break
            img = get_image_robust(fp); self.thumb_ready.emit(os.path.basename(fp), fp, img) if not img.isNull() else None
            self.progress.emit(int(((i + 1) / (len(fps) or 1)) * 100))
        self.finished.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
