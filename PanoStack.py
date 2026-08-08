#!/usr/bin/env python3
"""
PanoStack (v3.5.0)
- INFO: FULL DETAILED COMPREHENSIVE USER MANUAL restored under the ⓘ button.
- FIX: Panorama-tab hanging during mode switch resolved (Abort flag added to worker).
- FIX: Thumbnail size 300 works correctly (dynamic ListWidget IconSize).
- NEW: EV-correction options: +1 EV, -1 EV, -2 EV, -3 EV via right-click.
- FIX: EV correction + Free XMP integration via history injection.
- FIX: Darktable-CLI command order: <input> <xmp> <output>.
- FIX: Binary package path doubling resolved via os.path.normpath.
- UI: Buttons in Tab 4 equal size, distributed, with GUI checkbox next to Hugin.
- UI: Sorter defaults (5.0s Gap, Copy 1st ON).
- PROTECT: Sorter skips existing _HDR/_Pano files.
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
from datetime import datetime

# --- PADEN VOOR PYINSTALLER (INPAKKEN) ---
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".panostack_config.json")

# --- CONFIGURATIE ---
DEFAULT_CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "PANO_COLLECT_NAME": "Verzamelde_Panoramas",
    "DT_XMP_FILE": "oppepper.xmp",
    "LAST_SOURCE_DIR": os.path.expanduser("~"),
    "MAX_GAP": 1.0,
    "SAME_GAP": 5.0,
    "COPY_FIRST_TO_ROOT": True
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except:
        pass

CONFIG = load_config()
VALID_EXTS = {ext.lower() for ext in ['.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng', '.tif', '.tiff', '.jpg', '.jpeg']}

cores = os.cpu_count() or 2
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))

# --- IMPORTS ---
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
        QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox,
        QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea,
        QSplitter, QSizePolicy, QCheckBox, QMenu
    )
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QImage, QColor, QBrush, QAction
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Fout: {e}")
    sys.exit(1)

# --- HELPERS ---

def check_dependencies():
    deps = {
        "darktable-cli": "darktable",
        "enfuse": "enblend-enfuse",
        "hdrmerge": "hdrmerge",
        "exiftool": "perl-image-exiftool",
        "align_image_stack": "hugin",
        "hugin": "hugin",
        "mogrify": "imagemagick",
        "convert": "imagemagick",
        "darktable": "darktable"
    }
    missing = [cmd for cmd, pkg in deps.items() if shutil.which(cmd) is None]
    return missing, deps

def smart_copy(src, dst):
    try:
        subprocess.run(['cp', '--reflink=auto', src, dst], check=True, capture_output=True)
        return True
    except:
        try:
            shutil.copy2(src, dst)
            return True
        except:
            return False

def get_image_robust(path):
    if not path or not os.path.exists(path):
        return QImage()
    img = QImage()
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.dng', '.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf']:
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
            if res.stdout and len(res.stdout) > 5000:
                img.loadFromData(res.stdout)
                if not img.isNull():
                    break
        if img.isNull():
            return QImage()
    else:
        img.load(path)
    if img.isNull():
        return QImage()
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
        date_str = res.stdout.strip()
        if date_str and len(date_str) == 8: return date_str
    except: pass
    return datetime.now().strftime("%Y%m%d")

def find_best_xmp(folder_path):
    check_path = folder_path
    for _ in range(3):
        local_xmps = glob.glob(os.path.join(check_path, "*.xmp"))
        if local_xmps: return sorted(local_xmps, key=len)[0]
        parent = os.path.dirname(check_path)
        if parent == check_path: break
        check_path = parent
    global_xmp = os.path.join(SCRIPT_DIR, CONFIG["DT_XMP_FILE"])
    return global_xmp if os.path.exists(global_xmp) else None

def create_exposure_xmp(ev_value, base_xmp=None):
    """Maakt een tijdelijk XMP bestand aan met de gewenste belichtingscorrectie,
    gecombineerd met de bestaande geschiedenis van de basis-XMP."""
    tmp_xmp = tempfile.NamedTemporaryFile(suffix=".xmp", delete=False).name
    # Mapping van EV naar Darktable Float Hex
    ev_map = { 1: "0000803f", -1: "000080bf", -2: "000000c0", -3: "000040c0" }
    ev_param = ev_map.get(ev_value, "00000000")

    if base_xmp and os.path.exists(base_xmp):
        try:
            with open(base_xmp, 'r') as f:
                content = f.read()
            if "<darktable:history>" in content and "</rdf:Seq>" in content:
                new_li = f"""     <rdf:li
      darktable:num="999"
      darktable:module="exposure"
      darktable:operation="exposure"
      darktable:enabled="1"
      darktable:modversion="6"
      darktable:params="0000000000000000{ev_param}0000803f0000803f"
      darktable:multi_priority="0"
      darktable:multi_name=""
      darktable:iop_order="21.0000000000000"/>
    </rdf:Seq>"""
                content = content.replace("</rdf:Seq>", new_li)
                content = re.sub(r'darktable:history_end="\d+"', 'darktable:history_end="1000"', content)
                with open(tmp_xmp, "w") as f: f.write(content)
                return tmp_xmp
        except: pass

    xmp_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:darktable="http://darktable.sf.net/" darktable:xmp_version="3" darktable:history_end="1">
   <darktable:history>
    <rdf:Seq>
     <rdf:li darktable:num="0" darktable:module="exposure" darktable:operation="exposure" darktable:enabled="1" darktable:modversion="6"
      darktable:params="0000000000000000{ev_param}0000803f0000803f" darktable:multi_priority="0" darktable:multi_name="" darktable:iop_order="21.0000000000000"/>
    </rdf:Seq>   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""
    with open(tmp_xmp, "w") as f: f.write(xmp_content)
    return tmp_xmp

# --- WORKERS ---

class BaseWorker(QObject):
    finished, progress, log, result_path = Signal(), Signal(int), Signal(str), Signal(str)
    def __init__(self):
        super().__init__()
        self._is_running = True
        self.active_proc = None
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
        super().__init__()
        self.source_dir, self.max_gap, self.same_gap, self.copy_first = source_dir, max_gap, same_gap, copy_first
    @Slot()
    def run(self):
        try:
            self.log.emit(f"<b style='color:#2980b9;'>Analyse start in:</b> {self.source_dir}")
            all_paths = []
            res_skipped = 0
            for root, _, files in os.walk(self.source_dir):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in VALID_EXTS) and not f.lower().endswith('.xmp'):
                        if "_HDR" in f or "_Pano" in f:
                            res_skipped += 1; continue
                        all_paths.append(os.path.join(root, f))
            all_paths.sort()
            if res_skipped > 0: self.log.emit(f"<i>-> {res_skipped} resultaten (_HDR/_Pano) behouden in hoofdmap.</i>")
            if not all_paths: self.log.emit("Geen bestanden."); self.finished.emit(); return
            photos = []
            for i in range(0, len(all_paths), 40):
                if not self._is_running: break
                batch = all_paths[i:i + 40]
                self.result_path.emit(batch[0])
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
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest_root, exist_ok=True)
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
        if len(exposures) > 1: type_p = "Reeks"
        else:
            avg_gap = (group[-1]['ts'] - group[0]['ts']) / (len(group) - 1)
            type_p = "Burst" if (avg_gap < 1.2 and group[0]['iso'] > 800) else "Serie"
        seq += 1
        target = os.path.join(dest_root, group[0]['model'], group[0]['date'], f"{type_p}_{seq:03d}")
        os.makedirs(target, exist_ok=True)
        self.log.emit(f"  -> {type_p}_{seq:03d}: {len(group)} foto's")
        for f in group:
            dest = os.path.join(target, f['name'])
            if f['full_path'] != dest: shutil.move(f['full_path'], dest)
        if self.copy_first:
            try: shutil.copy2(os.path.join(target, group[0]['name']), os.path.join(self.source_dir, group[0]['name']))
            except: pass
        return seq

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, crop_percent, burst_limit=0, weights=(1.0, 0.2, 0.1)):
        super().__init__()
        self.base_dir, self.mode, self.method, self.bit_depth = base_dir, mode, method.lower(), bit_depth
        self.crop_percent, self.burst_limit, self.weights = crop_percent, burst_limit, weights
    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = []
            if os.path.basename(self.base_dir).startswith(prefix): subdirs.append(self.base_dir)
            for r, ds, _ in os.walk(self.base_dir):
                for d in ds:
                    if d.startswith(prefix): subdirs.append(os.path.join(r, d))
            subdirs = sorted(list(set(subdirs)))
            if not subdirs: self.log.emit(f"<b style='color:#e67e22;'>Geen {prefix} mappen gevonden.</b>"); self.finished.emit(); return
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            os.makedirs(os.path.join(coll_root, "DNG"), exist_ok=True); os.makedirs(os.path.join(coll_root, "TIFF"), exist_ok=True)
            self.log.emit(f"<b style='color:#2980b9;'>Stacking gestart:</b> {len(subdirs)} mappen.")
            for i, path in enumerate(subdirs):
                if not self._is_running: break
                name, xmp = os.path.basename(path), find_best_xmp(path)
                self.log.emit(f"<b>Actief:</b> {name}")
                coll_dng, coll_tif = os.path.join(coll_root, "DNG", f"{name}_HDR.dng"), os.path.join(coll_root, "TIFF", f"{name}_HDR.tif")
                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method) and not os.path.exists(coll_dng):
                    raws = sorted([os.path.join(path, f) for f in os.listdir(path) if any(f.lower().endswith(ex) for ex in ['.dng','.rw2','.arw','.cr2','.cr3','.nef']) and "_HDR" not in f])
                    out = os.path.join(path, f"{name}_HDR.dng")
                    self.log.emit(f"  -> HDRmerge (DNG)...")
                    if self.safe_run(['hdrmerge', '-b', '16', '-o', out] + raws) == 0:
                        smart_copy(out, coll_dng); self.result_path.emit(out)
                if (self.mode == "BURST" or "enfuse" in self.method or "beide" in self.method) and not os.path.exists(coll_tif):
                    self.log.emit(f"  -> Enfuse/Median (TIFF)...")
                    res = self._do_enfuse(path, name, xmp)
                    if res: smart_copy(res, coll_tif); self.result_path.emit(res)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            self.log.emit("<br><b style='color:#27ae60;'>✓ HDR/Burst voltooid.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()
    def _do_enfuse(self, path, name, xmp):
        all_f = sorted([f for f in os.listdir(path) if any(f.lower().endswith(ex) for ex in VALID_EXTS) and "_HDR" not in f])
        files = all_f[:self.burst_limit] if (self.mode == "BURST" and self.burst_limit > 0) else all_f
        if len(files) < 2: return None
        with tempfile.TemporaryDirectory() as tmp_dir:
            tifs = []
            for idx, f in enumerate(files):
                out = os.path.join(tmp_dir, f"img_{idx:03d}.tif")
                cmd = ['darktable-cli', os.path.join(path, f)]
                if xmp: cmd.append(xmp)
                cmd.extend([out, '--core', '--library', ':memory:', '--disable-opencl'])
                if self.safe_run(cmd) == 0: tifs.append(out)
                self.sub_progress.emit(int(((idx + 1) / len(files)) * 70))
            if len(tifs) < 2: return None
            ali = os.path.join(tmp_dir, "ali_")
            self.safe_run(['align_image_stack', '-m', '10', '-a', ali, '-c', '20', '-z', '-x', '-y'] + tifs)
            alis = sorted(glob.glob(os.path.join(tmp_dir, "ali_*.tif")))
            for a in alis: self.safe_run(['mogrify', '-alpha', 'off', '-type', 'truecolor', '+matte', a])
            out_h = os.path.join(tmp_dir, "result.tif")
            if self.mode == "BURST": self.safe_run(['convert'] + alis + ['-evaluate-sequence', 'median', out_h])
            else: self.safe_run(['enfuse', f'--depth={self.bit_depth}', f'--exposure-weight={self.weights[0]}', '--output', out_h] + alis, env=ENV_STABLE)
            if os.path.exists(out_h):
                final = os.path.join(path, f"{name}_HDR.tif")
                if self.crop_percent > 0: self.safe_run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h])
                shutil.copy2(out_h, final); return final
        return None

class PanoWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, custom_xmp=None, output_dir=".", ev_map=None):
        super().__init__()
        self.files, self.custom_xmp, self.output_dir, self.ev_map = files, custom_xmp, output_dir, ev_map or {}
    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            imgs = []
            try:
                self.log.emit(f"<b style='color:#2980b9;'>OpenCV Ultra-HQ Panorama gestart</b>")
                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    ev = self.ev_map.get(f, 0)
                    if f.lower().endswith(('.dng','.rw2','.arw','.cr2','.cr3','.nef','.orf','.raf')) or ev != 0:
                        t = os.path.join(tmp_dir, f"p_{i}.tif")
                        xmp = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp(os.path.dirname(f))
                        if ev != 0: xmp = create_exposure_xmp(ev, xmp)
                        cmd = ['darktable-cli', f]
                        if xmp: cmd.append(xmp)
                        cmd.extend([t, '--core', '--library', ':memory:', '--disable-opencl'])
                        self.safe_run(cmd); read_f = t
                    else: read_f = f
                    img = cv2.imread(read_f, cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        if img.dtype == np.uint16: img = (img / 256).astype(np.uint8)
                        if img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        imgs.append(img)
                    self.sub_progress.emit(int(((i + 1) / len(self.files)) * 80))
                if len(imgs) > 1 and self._is_running:
                    st = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                    try:
                        st.setRegistrationResol(0.8); st.setCompositingResol(-1); st.setFeaturesFinder(cv2.SIFT_create())
                        st.setExposureCompensator(cv2.detail_ExposureCompensator_createDefault(cv2.detail_ExposureCompensator_BLOCKS))
                        st.setSeamFinder(cv2.detail_GraphCutSeamFinder('COST_COLOR'))
                        st.setWaveCorrection(True); st.setWaveCorrectKind(cv2.detail_WAVE_CORRECT_HORIZ)
                    except: pass
                    status, res = st.stitch(imgs)
                    if status == cv2.Stitcher_OK:
                        os.makedirs(self.output_dir, exist_ok=True)
                        fname = f"{os.path.splitext(os.path.basename(self.files[0]))[0]}_Pano.tif"
                        out = os.path.join(self.output_dir, fname)
                        cv2.imwrite(out, res); self.log.emit("✓ Ready."); self.result_path.emit(out)
                self.progress.emit(100)
            except Exception as e: self.log.emit(f"Fout: {e}")
            finally: self.finished.emit()

class HuginCliWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, output_dir, custom_xmp=None, ev_map=None):
        super().__init__()
        self.files, self.output_dir, self.custom_xmp, self.ev_map = files, output_dir, custom_xmp, ev_map or {}
    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                self.log.emit("<b style='color:#2980b9;'>Hugin CLI HQ (16-bit) gestart</b>")
                tiffs = []
                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    ev = self.ev_map.get(f, 0)
                    if f.lower().endswith(('.dng','.rw2','.arw','.cr2','.cr3','.nef', '.orf', '.raf')) or ev != 0:
                        t = os.path.join(tmp, f"h_{i}.tif")
                        xmp = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp(os.path.dirname(f))
                        if ev != 0: xmp = create_exposure_xmp(ev, xmp)
                        cmd = ['darktable-cli', f]
                        if xmp: cmd.append(xmp)
                        cmd.extend([t, '--core', '--library', ':memory:', '--disable-opencl'])
                        self.safe_run(cmd); tiffs.append(t)
                    else: t = os.path.join(tmp, f"h_{i}{os.path.splitext(f)[1]}"); shutil.copy2(f, t); tiffs.append(t)
                    self.sub_progress.emit(int(((i+1)/len(self.files))*20))
                if not tiffs: return
                pto, prefix = os.path.join(tmp, "p.pto"), os.path.join(tmp, "out")
                self.safe_run(['pto_gen', '-o', pto] + tiffs)
                self.safe_run(['cpfind', '--multirow', '--celeste', '-o', pto, pto])
                self.safe_run(['cpclean', '-o', pto, pto])
                lf = shutil.which("hugin_linefind") or shutil.which("linefind")
                if lf: self.safe_run([lf, '-o', pto, pto])
                self.safe_run(['autooptimiser', '-a', '-m', '-p', '-s', '-l', '-o', pto, pto])
                self.safe_run(['pano_modify', '--straighten', '--canvas=AUTO', '--crop=AUTO', '--center', '-o', pto, pto])
                self.safe_run(['hugin_executor', '--stitching', f'--prefix={prefix}', pto])
                res = prefix + ".tif"
                if os.path.exists(res):
                    os.makedirs(self.output_dir, exist_ok=True)
                    out = os.path.join(self.output_dir, f"Pano_Hugin_{get_capture_date_compact(self.files[0])}.tif")
                    shutil.move(res, out); self.log.emit("✓ Gereed."); self.result_path.emit(out)
            except Exception as e: self.log.emit(f"Fout: {e}")
            finally: self.progress.emit(100); self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PanoStack v3.5.0")
        self.resize(1300, 900)
        missing, deps = check_dependencies()
        if missing: QMessageBox.warning(self, "Readiness", f"Missing: {missing}")
        self.worker, self.thread, self.lt, self.last_pano_result = None, None, None, None
        self.active_temp_dirs = []
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteren"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Burst"); self.tabs.addTab(self.t4, "4. Panorama")
        self.setup_t1(); self.setup_t2(); self.setup_t3(); self.setup_t4()
        self.tabs.currentChanged.connect(lambda i: self.refresh_t4() if i == 3 else None)
        self._sync_paths()
    def _sync_paths(self):
        p = self.s1.text().strip()
        if p and os.path.exists(p):
            sp = os.path.normpath(os.path.join(p, CONFIG["SORTED_DIR_NAME"]))
            self.s2.setText(sp); self.s3.setText(sp); self.s4.setText(os.path.normpath(os.path.join(p, CONFIG["HDR_COLLECT_NAME"])))
    def _make_thin_bar(self):
        pb = QProgressBar(); pb.setFixedHeight(8); pb.setTextVisible(False); pb.setStyleSheet("QProgressBar { border: 1px solid #bbb; background: #eee; } QProgressBar::chunk { background: #05B8CC; }")
        pb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); return pb
    def setup_t1(self):
        l = QVBoxLayout(self.t1); h = QHBoxLayout(); self.s1 = QLineEdit(CONFIG["LAST_SOURCE_DIR"])
        self.s1.textChanged.connect(self._sync_paths); h.addWidget(QLabel("Bron:")); h.addWidget(self.s1)
        b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s1)); h.addWidget(b)
        h.addWidget(QLabel("HDR Gap:")); self.gv = QDoubleSpinBox(); self.gv.setRange(0.5, 2.5); self.gv.setValue(1.0); h.addWidget(self.gv)
        h.addWidget(QLabel("Burst Gap:")); self.gv_same = QDoubleSpinBox(); self.gv_same.setRange(1.0, 20.0); self.gv_same.setValue(5.0); h.addWidget(self.gv_same)
        self.cb_copy_first = QCheckBox("Kopie 1e van reeks"); self.cb_copy_first.setChecked(True); h.addWidget(self.cb_copy_first)
        btn_i = QPushButton("ⓘ"); btn_i.setFixedWidth(40); btn_i.clicked.connect(self.show_readme); h.addWidget(btn_i)
        l.addLayout(h); self.b1 = QPushButton("Start Sorteren"); self.b1.clicked.connect(self.go1); l.addWidget(self.b1)
        self.p1 = self._make_thin_bar(); l.addWidget(self.p1)
        split = QSplitter(Qt.Horizontal); self.log1 = QTextEdit(); self.log1.setReadOnly(True); self.prev1 = QLabel(); self.prev1.setAlignment(Qt.AlignCenter)
        sc = QScrollArea(); sc.setWidget(self.prev1); sc.setWidgetResizable(True); split.addWidget(self.log1); split.addWidget(sc); split.setSizes([400, 800]); l.addWidget(split)
    def setup_t2(self):
        l = QVBoxLayout(self.t2); h_main = QHBoxLayout(); h_main.addWidget(QLabel("Map:")); self.s2 = QLineEdit(); h_main.addWidget(self.s2)
        b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s2)); h_main.addWidget(b); self.m2 = QComboBox(); h_main.addWidget(self.m2)
        h_main.addWidget(QLabel("Crop:")); self.cp2 = QDoubleSpinBox(); self.cp2.setValue(1.5); h_main.addWidget(self.cp2)
        h_main.addWidget(QLabel("Exp:")); self.ew2 = QDoubleSpinBox(); self.ew2.setRange(0,1); self.ew2.setValue(1.0); h_main.addWidget(self.ew2)
        h_main.addWidget(QLabel("Sat:")); self.sw2 = QDoubleSpinBox(); self.sw2.setRange(0,1); self.sw2.setValue(0.2); h_main.addWidget(self.sw2)
        h_main.addWidget(QLabel("Con:")); self.cw2 = QDoubleSpinBox(); self.cw2.setRange(0,1); self.cw2.setValue(0.1); h_main.addWidget(self.cw2); l.addLayout(h_main)
        h_ctrl = QHBoxLayout(); self.b2 = QPushButton("Start HDR"); self.b2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b2.clicked.connect(lambda: self.go_proc("HDR")); h_ctrl.addWidget(self.b2)
        self.stop2 = QPushButton("Stop"); self.stop2.setFixedWidth(80); self.stop2.clicked.connect(self.stop_proc); h_ctrl.addWidget(self.stop2); l.addLayout(h_ctrl)
        v_prog = QWidget(); v_prog.setFixedHeight(60); vp_l = QVBoxLayout(v_prog); vp_l.setContentsMargins(0,0,0,0);
        vp_l.addWidget(QLabel("Totaal:")); self.p2 = self._make_thin_bar(); vp_l.addWidget(self.p2)
        vp_l.addWidget(QLabel("Huidig:")); self.p2_sub = self._make_thin_bar(); vp_l.addWidget(self.p2_sub); l.addWidget(v_prog)
        h_split2 = QSplitter(Qt.Horizontal); self.log2 = QTextEdit(); self.log2.setReadOnly(True); self.prev2 = QLabel(); self.prev2.setAlignment(Qt.AlignCenter)
        sc = QScrollArea(); sc.setWidget(self.prev2); sc.setWidgetResizable(True); h_split2.addWidget(self.log2); h_split2.addWidget(sc); h_split2.setSizes([325, 975]); l.addWidget(h_split2)
        self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); self.m2.currentIndexChanged.connect(self.update_enfuse_visibility); self.update_enfuse_visibility()
    def setup_t3(self):
        l = QVBoxLayout(self.t3); h = QHBoxLayout(); h.addWidget(QLabel("Map:")); self.s3 = QLineEdit(); h.addWidget(self.s3); b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s3)); h.addWidget(b)
        self.bl3 = QComboBox(); self.bl3.addItems(["8", "16", "32"]); h.addWidget(QLabel("Limiet:")); h.addWidget(self.bl3); l.addLayout(h)
        h_ctrl = QHBoxLayout(); self.b3 = QPushButton("Start Burst"); self.b3.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b3.clicked.connect(lambda: self.go_proc("BURST")); h_ctrl.addWidget(self.b3)
        self.stop3 = QPushButton("Stop"); self.stop3.setFixedWidth(80); self.stop3.clicked.connect(self.stop_proc); h_ctrl.addWidget(self.stop3); l.addLayout(h_ctrl)
        v_prog = QWidget(); v_prog.setFixedHeight(60); vp_l = QVBoxLayout(v_prog); vp_l.setContentsMargins(0,0,0,0);
        vp_l.addWidget(QLabel("Totaal:")); self.p3 = self._make_thin_bar(); vp_l.addWidget(self.p3)
        vp_l.addWidget(QLabel("Huidig:")); self.p3_sub = self._make_thin_bar(); vp_l.addWidget(self.p3_sub); l.addWidget(v_prog)
        h_split3 = QSplitter(Qt.Horizontal); self.log3 = QTextEdit(); self.log3.setReadOnly(True); self.prev3 = QLabel(); self.prev3.setAlignment(Qt.AlignCenter)
        sc = QScrollArea(); sc.setWidget(self.prev3); sc.setWidgetResizable(True); h_split3.addWidget(self.log3); h_split3.addWidget(sc); h_split3.setSizes([325, 975]); l.addWidget(h_split3)
    def setup_t4(self):
        main_l = QVBoxLayout(self.t4); h_paths = QHBoxLayout(); h_paths.addWidget(QLabel("Verzamelmap:")); self.s4 = QLineEdit(); h_paths.addWidget(self.s4)
        b = QPushButton("..."); b.clicked.connect(lambda: self.sel_dir(self.s4)); h_paths.addWidget(b); self.lbl_x4 = QLabel("Vrije XMP:"); h_paths.addWidget(self.lbl_x4); self.x4 = QLineEdit(); h_paths.addWidget(self.x4)
        self.b_xmp4 = QPushButton("Kies"); self.b_xmp4.clicked.connect(self.sel_xmp); h_paths.addWidget(self.b_xmp4); main_l.addLayout(h_paths)
        h_opts = QHBoxLayout(); self.f4 = QComboBox(); self.f4.addItems(["TIFF/JPG", "DNG", "RAW (Serie)", "RAW (enkel)"]); self.f4.currentIndexChanged.connect(lambda idx: self.update_refresh_all()); h_opts.addWidget(self.f4)
        self.ts4 = QComboBox(); self.ts4.addItems(["100", "200", "300"]); self.ts4.setCurrentText("200"); self.ts4.currentIndexChanged.connect(lambda idx: self.update_refresh_all()); h_opts.addWidget(self.ts4); self.p4_load = self._make_thin_bar(); h_opts.addWidget(self.p4_load); main_l.addLayout(h_opts)
        self.v_split = QSplitter(Qt.Vertical); self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(200, 200)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.lw.setContextMenuPolicy(Qt.CustomContextMenu); self.lw.customContextMenuRequested.connect(self.show_context)
        self.v_split.addWidget(self.lw); bot_w = QWidget(); bot_l = QVBoxLayout(bot_w); btn_h = QHBoxLayout()
        self.b4 = QPushButton("Start openCV (8 bit)"); self.b4.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b4.clicked.connect(self.go4); btn_h.addWidget(self.b4)
        self.b_hu = QPushButton("Start Hugin (16 bit)"); self.b_hu.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b_hu.clicked.connect(self.go_hugin)
        btn_h.addWidget(self.b_hu); self.cb_hugin_gui = QCheckBox("Open GUI"); self.cb_hugin_gui.setFixedWidth(90); btn_h.addWidget(self.cb_hugin_gui)
        self.b_dt = QPushButton("Start Darktable"); self.b_dt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.b_dt.clicked.connect(self.open_dt); btn_h.addWidget(self.b_dt); bot_l.addLayout(btn_h)
        h_s4 = QHBoxLayout(); self.p4_sub = self._make_thin_bar(); h_s4.addWidget(self.p4_sub); self.stop4 = QPushButton("Stop"); self.stop4.setFixedWidth(50); self.stop4.setFixedHeight(18); self.stop4.clicked.connect(self.stop_proc); h_s4.addWidget(self.stop4); bot_l.addLayout(h_s4)
        h_split4 = QSplitter(Qt.Horizontal); self.log4 = QTextEdit(); self.log4.setReadOnly(True); self.prev4 = QLabel(); self.prev4.setAlignment(Qt.AlignCenter)
        sc = QScrollArea(); sc.setWidget(self.prev4); sc.setWidgetResizable(True); h_split4.addWidget(self.log4); h_split4.addWidget(sc); h_split4.setSizes([325, 975]); bot_l.addWidget(h_split4); self.v_split.addWidget(bot_w); main_l.addWidget(self.v_split); self.update_pano_xmp_visibility()
    def show_context(self, pos):
        item = self.lw.itemAt(pos)
        if not item: return
        menu = QMenu(); a_p1 = QAction("+1 Stop (EV)", self); a0 = QAction("Normal (0 EV)", self); a_m1 = QAction("-1 Stop (EV)", self); a_m2 = QAction("-2 Stops (EV)", self); a_m3 = QAction("-3 Stops (EV)", self); menu.addActions([a_p1, a0, a_m1, a_m2, a_m3])
        action = menu.exec(self.lw.mapToGlobal(pos)); path = item.data(Qt.UserRole)
        if action == a0: item.setData(Qt.UserRole + 1, 0); item.setText(os.path.basename(path)); item.setBackground(QBrush(Qt.transparent))
        elif action == a_p1: item.setData(Qt.UserRole + 1, 1); item.setText(f"{os.path.basename(path)} [+1 EV]"); item.setBackground(QBrush(QColor(230, 255, 230)))
        elif action == a_m1: item.setData(Qt.UserRole + 1, -1); item.setText(f"{os.path.basename(path)} [-1 EV]"); item.setBackground(QBrush(QColor(255, 230, 230)))
        elif action == a_m2: item.setData(Qt.UserRole + 1, -2); item.setText(f"{os.path.basename(path)} [-2 EV]"); item.setBackground(QBrush(QColor(255, 200, 200)))
        elif action == a_m3: item.setData(Qt.UserRole + 1, -3); item.setText(f"{os.path.basename(path)} [-3 EV]"); item.setBackground(QBrush(QColor(255, 150, 150)))
    def show_readme(self):
        text = """<h2 style='color:#2980b9;'>PanoStack v3.5.0 - User Manual</h2>
        <p><b>PanoStack</b> is an automated high-performance HQ RAW workflow utility for professional photographers.</p>

        <h3 style='color:#2c3e50;'>1. Sorting Tab (The Foundation)</h3>
        <ul>
            <li><b>HDR Gap:</b> Max time (s) between bracketed shots with different exposure settings.</li>
            <li><b>Burst Gap:</b> Max time (s) between shots with identical exposures (panoramas/bursts). <b>Default: 5.0s</b>.</li>
            <li><b>Copy 1st frame:</b> Enables a <b>Non-HDR Workflow</b>. By keeping a reference of the first frame in the root, you can stitch a fast preview panorama without waiting for HDR stacking.</li>
            <li><b>Protection:</b> Existing <i>_HDR</i> and <i>_Pano</i> files are ignored during sorting to prevent them from being moved.</li>
        </ul>

        <h3 style='color:#2c3e50;'>2. Stacking & Noise Reduction</h3>
        <ul>
            <li><b>HDR Stacking:</b> Combine brackets into 32-bit DNG (HDRmerge) or 16-bit TIFF (Enfuse).</li>
            <li><b>Burst Stacking:</b> Handheld noise reduction via median pixel evaluation (8-32 frames recommended).</li>
            <li><b>Dual Progress:</b> Total progress (upper bar) and individual file progress (lower bar) are displayed.</li>
        </ul>

        <h3 style='color:#2c3e50;'>3. Panorama Tab & Exposure Fix</h3>
        <ul>
            <li><b>Free XMP:</b> Apply a custom Darktable XMP to all frames for consistent color and lens correction. <i>Lens correction is highly recommended for perfect stitching.</i></li>
            <li><b>Exposure Fix:</b> HDRmerge results can sometimes show baseline jumps. <u>Right-click</u> any thumbnail to adjust brightness (+1 to -3 EV). This is automatically <i>injected</i> into your XMP history, preserving all other settings.</li>
            <li><b>Engines:</b> 16-bit Hugin CLI (auto-leveling) or fast Ultra-HQ OpenCV.</li>
        </ul>

        <h3 style='color:#2c3e50;'>System Dependencies (Arch Linux)</h3>
        <p><code>sudo pacman -S darktable hugin enblend-enfuse perl-image-exiftool imagemagick python-pyside6 python-opencv python-numpy</code></p>
        <p>AUR (Required for DNG): <code>yay -S hdrmerge</code></p>
        """
        QMessageBox.information(self, "User Manual", text)
    def sel_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Kies Map", edit.text(), QFileDialog.Option.DontUseNativeDialog)
        if d: edit.setText(os.path.normpath(d)); self._sync_paths(); self.refresh_t4()
    def sel_xmp(self):
        f, _ = QFileDialog.getOpenFileName(self, "Kies XMP", "", "XMP (*.xmp)", options=QFileDialog.Option.DontUseNativeDialog)
        if f: self.x4.setText(f)
    def update_refresh_all(self):
        sz = int(self.ts4.currentText()); self.lw.setIconSize(QSize(sz, sz)); self.refresh_t4()
    def update_enfuse_visibility(self):
        is_enf = self.m2.currentText() != "HDRmerge (DNG)"
        for w in [self.ew2, self.sw2, self.cw2, self.cp2]: w.setEnabled(is_enf)
    def update_pano_xmp_visibility(self):
        is_raw = self.f4.currentIndex() != 0
        for w in [self.x4, self.b_xmp4, self.lbl_x4]: w.setEnabled(is_raw)
    def closeEvent(self, event):
        if self.worker: self.worker.stop()
        CONFIG["LAST_SOURCE_DIR"], CONFIG["MAX_GAP"], CONFIG["SAME_GAP"], CONFIG["COPY_FIRST_TO_ROOT"] = self.s1.text(), self.gv.value(), self.gv_same.value(), self.cb_copy_first.isChecked()
        save_config(CONFIG); event.accept()
    def refresh_t4(self):
        root = self.s1.text().strip()
        if not os.path.exists(root): return
        mode, path = self.f4.currentIndex(), self.s4.text()
        exts = (('.tif', '.tiff', '.jpg', '.jpeg') if mode == 0 else (('.dng',) if mode == 1 else (('.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng'))))
        inc_first, f_filter, rec = False, None, True
        if mode == 3: scan_p, rec, inc_first, f_filter = root, False, True, ("Serie_", "Reeks_", "Burst_")
        elif mode == 2: scan_p, f_filter = os.path.normpath(os.path.join(root, CONFIG["SORTED_DIR_NAME"])), ("Serie_",)
        else: sub = "TIFF" if mode == 0 else "DNG"; scan_p = os.path.normpath(os.path.join(path, sub)) if os.path.exists(os.path.join(path, sub)) else path
        if hasattr(self, 'lt') and self.lt and self.lt.isRunning():
            if hasattr(self, 'lwk') and self.lwk: self.lwk.is_aborted = True
            self.lt.quit(); self.lt.wait()
        self.lt = QThread(); self.lwk = ThumbnailWorker(scan_p, exts, rec, inc_first, f_filter)
        self.lwk.moveToThread(self.lt); self.lt.started.connect(self.lwk.run); self.lwk.thumb_ready.connect(self.add_thumb)
        self.lwk.progress.connect(self.p4_load.setValue); self.lwk.finished.connect(self.lt.quit); self.lt.start(); self.lw.clear()
    def add_thumb(self, n, p, img):
        it = QListWidgetItem(n); it.setData(Qt.UserRole, p); it.setData(Qt.UserRole + 1, 0)
        s = int(self.ts4.currentText()); it.setIcon(QIcon(QPixmap.fromImage(img.scaled(s, s, Qt.KeepAspectRatio)))); self.lw.addItem(it)
    def stop_proc(self):
        if self.worker: self.worker.stop()
    def go1(self):
        self.log1.clear(); w = SortWorker(self.s1.text(), self.gv.value(), self.gv_same.value(), self.cb_copy_first.isChecked())
        w.finished.connect(self.refresh_t4); self._run(w, self.p1, self.log1, self.b1)
    def go_proc(self, mode):
        p, log, b, stop = (self.s2.text(), self.log2, self.b2, self.stop2) if mode == "HDR" else (self.s3.text(), self.log3, self.b3, self.stop3)
        log.clear(); meth = self.m2.currentText() if mode == "HDR" else "Median"
        w = HdrBurstWorker(p, mode, meth, "16", 1.5, 0, (1.0, 0.2, 0.1))
        pb, ps = (self.p2, self.p2_sub) if mode == "HDR" else (self.p3, self.p3_sub)
        w.sub_progress.connect(ps.setValue); self._run(w, pb, log, b, stop)
    def go4(self):
        items = self.lw.selectedItems()
        if items:
            files, ev_map = [it.data(Qt.UserRole) for it in items], {it.data(Qt.UserRole): it.data(Qt.UserRole + 1) or 0 for it in items}
            self.log4.clear(); p_dir = self._get_pano_save_dir(files[0])
            w = PanoWorker(files, self.x4.text(), p_dir, ev_map); w.sub_progress.connect(self.p4_sub.setValue)
            w.result_path.connect(lambda p: setattr(self, 'last_pano_result', p)); w.finished.connect(self.lw.clearSelection); self._run(w, self.p4_sub, self.log4, self.b4, self.stop4)
    def open_dt(self):
        try:
            sel = self.lw.selectedItems(); target = sel[0].data(Qt.UserRole) if len(sel) == 1 else self.last_pano_result
            if target and os.path.exists(target): subprocess.Popen(['darktable', '--library', ':memory:', target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: pass
    def go_hugin(self):
        items = self.lw.selectedItems()
        if not items: return
        files, ev_map = [it.data(Qt.UserRole) for it in items], {it.data(Qt.UserRole): it.data(Qt.UserRole + 1) or 0 for it in items}
        if self.cb_hugin_gui.isChecked():
            tmp_root = os.path.expanduser("~/ps_h_temp"); os.makedirs(tmp_root, exist_ok=True); tmp_h = os.path.join(tmp_root, datetime.now().strftime("%H%M%S"))
            os.makedirs(tmp_h, exist_ok=True); self.active_temp_dirs.append(tmp_h); final_p = []
            for i, f in enumerate(files):
                ev = ev_map.get(f, 0)
                if f.lower().endswith(('.dng','.rw2','.arw','.cr2','.cr3','.nef', '.orf', '.raf')) or ev != 0:
                    tif, xmp = os.path.join(tmp_h, f"h_{i}.tif"), (self.x4.text() or find_best_xmp(os.path.dirname(f)))
                    if ev != 0: xmp = create_exposure_xmp(ev, xmp)
                    cmd = ['darktable-cli', f];
                    if xmp: cmd.append(xmp)
                    cmd.extend([tif, '--core', '--library', ':memory:', '--disable-opencl'])
                    subprocess.run(cmd, stdout=subprocess.DEVNULL); final_p.append(tif)
                else: final_p.append(os.path.abspath(f))
            if final_p: subprocess.Popen(['hugin'] + final_p)
        else:
            self.log4.clear(); p_dir = self._get_pano_save_dir(files[0])
            w = HuginCliWorker(files, p_dir, self.x4.text(), ev_map)
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
    def _get_pano_save_dir(self, first_file):
        base_root = self.s1.text().strip()
        if not base_root or not os.path.exists(base_root):
            file_dir = os.path.dirname(first_file)
            if CONFIG["HDR_COLLECT_NAME"] in file_dir: base_root = file_dir.split(CONFIG["HDR_COLLECT_NAME"])[0]
            else: base_root = os.path.dirname(file_dir)
        return os.path.join(os.path.abspath(base_root), CONFIG["PANO_COLLECT_NAME"])

class ThumbnailWorker(QObject):
    finished, progress, thumb_ready = Signal(), Signal(int), Signal(str, str, QImage)
    def __init__(self, directory, extensions, recursive=False, inc_first=False, folder_filter=None):
        super().__init__()
        self.directory, self.extensions, self.recursive, self.inc_first, self.folder_filter = directory, extensions, recursive, inc_first, folder_filter
        self.is_aborted = False
    def run(self):
        if not os.path.exists(self.directory): self.finished.emit(); return
        found, fps = set(), []
        if self.recursive:
            for r, _, fs in os.walk(self.directory):
                if self.is_aborted: break
                if self.folder_filter and not os.path.basename(r).startswith(self.folder_filter): continue
                for f in sorted(fs):
                    if f.lower().endswith(self.extensions):
                        p = os.path.join(r, f)
                        if p not in found: fps.append(p); found.add(p)
        else:
            for f in sorted(os.listdir(self.directory)):
                if self.is_aborted: break
                if f.lower().endswith(self.extensions):
                    p = os.path.join(self.directory, f); fps.append(p); found.add(p)
            if self.inc_first:
                s_root = os.path.join(self.directory, CONFIG["SORTED_DIR_NAME"])
                if os.path.exists(s_root):
                    for r, ds, fs in os.walk(s_root):
                        if self.is_aborted: break
                        if os.path.basename(r).startswith(("Serie_", "Reeks_", "Burst_")):
                            v_fs = sorted([f for f in fs if f.lower().endswith(self.extensions)])
                            if v_fs:
                                p = os.path.join(r, v_fs[0])
                                if p not in found: fps.append(p); found.add(p)
        for i, fp in enumerate(fps):
            if self.is_aborted: break
            img = get_image_robust(fp)
            if not img.isNull(): self.thumb_ready.emit(os.path.basename(fp), fp, img)
            self.progress.emit(int(((i + 1) / (len(fps) or 1)) * 100))
        self.finished.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
