#!/usr/bin/env python3
"""
PanoStack (v2.2)
- FIX: Hugin GUI 'File not found' opgelost door temp-mappen NIET te verwijderen tijdens sessie.
- FIX: Hugin GUI opent TIF/JPG direct (v1.1 stijl) en convert alleen RAW/DNG (v1.4+ stijl).
- FIX: RAW (enkel) toont nu losse RAW's + eerste foto van iedere gesorteerde groep.
- FIX: RAW (Serie) toont nu strikt alleen de 'Serie_' mappen.
- UI: Crop veld uitgeschakeld bij HDRmerge.
- UI: Uitgebreide log-informatie toegevoegd aan alle processen.
- NEW: Burst Gap instelbaar in Sorter (vervangt hardgecodeerde 5s voor gelijke belichtingen).
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

# --- CONFIGURATIE ---
DEFAULT_CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "PANO_COLLECT_NAME": "Verzamelde_Panoramas",
    "DT_XMP_FILE": "oppepper.xmp",
    "LAST_SOURCE_DIR": os.path.expanduser("~"),
    "MAX_GAP": 1.0,
    "SAME_GAP": 2.5,
    "COPY_FIRST_TO_ROOT": False
}

CONFIG_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "panostack_config.json")

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
VALID_EXTS = {ext.lower() for ext in ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG', '.tif', '.tiff', '.jpg', '.jpeg']}

cores = os.cpu_count() or 2
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# --- IMPORTS ---
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
        QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox,
        QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea,
        QSplitter, QSizePolicy, QCheckBox
    )
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QImage
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
    except:
        pass
    return img

def find_best_xmp(folder_path):
    check_path = folder_path
    for _ in range(3):
        local_xmps = glob.glob(os.path.join(check_path, "*.xmp"))
        if local_xmps:
            return sorted(local_xmps, key=len)[0]
        parent = os.path.dirname(check_path)
        if parent == check_path:
            break
        check_path = parent
    global_xmp = os.path.join(SCRIPT_DIR, CONFIG["DT_XMP_FILE"])
    return global_xmp if os.path.exists(global_xmp) else None

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
            try:
                self.active_proc.terminate()
                self.active_proc.wait(timeout=2)
            except:
                try: self.active_proc.kill()
                except: pass
        self.log.emit("<br><b style='color:#e74c3c;'>[STOP] Proces afgebroken.</b>")

    def safe_run(self, cmd, env=None):
        if not self._is_running:
            return 1
        try:
            self.active_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            return self.active_proc.wait()
        except:
            return 1

class SortWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, source_dir, max_gap, same_gap, copy_first=False):
        super().__init__()
        self.source_dir = source_dir
        self.max_gap = max_gap
        self.same_gap = same_gap
        self.copy_first = copy_first

    @Slot()
    def run(self):
        try:
            self.log.emit(f"<b style='color:#2980b9;'>Sorteren gestart in:</b> {self.source_dir}")
            all_files = sorted([f for f in os.listdir(self.source_dir) if any(f.lower().endswith(ext) for ext in VALID_EXTS) and not f.lower().endswith('.xmp') and f != CONFIG["SORTED_DIR_NAME"]])

            if not all_files:
                self.log.emit("<i style='color:#e67e22;'>Geen ondersteunde bestanden gevonden.</i>")
                self.finished.emit()
                return

            self.log.emit(f"<i>Analyse van {len(all_files)} bestanden op tijd en belichting...</i>")
            photos = []
            for i in range(0, len(all_files), 40):
                if not self._is_running: break
                batch = all_files[i:i + 40]
                batch_paths = [os.path.join(self.source_dir, f) for f in batch]
                self.result_path.emit(batch_paths[0])
                res = subprocess.run(['exiftool', '-q', '-f', '-S3', '-T', '-n', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO'] + batch_paths, capture_output=True, text=True)
                for idx, line in enumerate(res.stdout.strip().splitlines()):
                    p = line.split('\t')
                    if len(p) >= 5:
                        try:
                            dt = datetime.strptime(p[0].split('.')[0].split('+')[0].strip(), "%Y:%m:%d %H:%M:%S")
                            photos.append({'name': batch[idx], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[1]}A{p[2]}", 'iso': int(re.sub(r"\D", "", p[4])) if p[4] != "-" else 0, 'model': p[3].strip().replace(' ','_')})
                        except:
                            continue
                self.sub_progress.emit(int(((i + len(batch)) / len(all_files)) * 100))

            photos.sort(key=lambda x: x['ts'])
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest_root, exist_ok=True)

            self.log.emit(f"<i>Groeperen met marges: HDR={self.max_gap}s, Burst={self.same_gap}s...</i>")
            curr, seq = [], 0
            for idx, p in enumerate(photos):
                if not self._is_running: break
                is_same = curr and (p['exp'] == curr[-1]['exp'] and p['iso'] == curr[-1]['iso'])

                limit = self.same_gap if is_same else self.max_gap

                if not curr or (p['ts'] - curr[-1]['ts'] <= limit):
                    curr.append(p)
                else:
                    seq = self._process_group(curr, dest_root, seq)
                    curr = [p]
                self.progress.emit(int(((idx + 1) / len(photos)) * 100))
            if curr:
                seq = self._process_group(curr, dest_root, seq)

            self.log.emit(f"<br><b style='color:#27ae60;'>✓ Sorteren voltooid. Totaal {seq} groepen aangemaakt.</b>")
        except Exception as e:
            self.log.emit(f"<b style='color:#e74c3c;'>Fout bij sorteren: {e}</b>")
        finally:
            self.finished.emit()

    def _process_group(self, group, dest_root, seq):
        if len(group) < 2: return seq
        exposures = {p['exp'] for p in group}
        if len(exposures) > 1:
            type_p = "Reeks"
        else:
            duration = group[-1]['ts'] - group[0]['ts']
            avg_gap = duration / (len(group) - 1)
            type_p = "Burst" if avg_gap < 1.2 else "Serie"
        seq += 1
        target = os.path.join(dest_root, group[0]['model'], group[0]['date'], f"{type_p}_{seq:03d}")
        os.makedirs(target, exist_ok=True)
        self.log.emit(f"  -> <span style='color:#34495e;'>{type_p}_{seq:03d}</span>: {len(group)} foto's in <small>{group[0]['date']}</small>")

        for f in group:
            try:
                shutil.move(os.path.join(self.source_dir, f['name']), os.path.join(target, f['name']))
            except:
                pass

        if self.copy_first and group:
            try:
                target_f = os.path.join(target, group[0]['name'])
                root_f = os.path.join(self.source_dir, group[0]['name'])
                shutil.copy2(target_f, root_f)
            except:
                pass
        return seq

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, crop_percent, burst_limit=0, weights=(1.0, 0.2, 0.1)):
        super().__init__()
        self.base_dir = base_dir
        self.mode = mode
        self.method = method.lower()
        self.bit_depth = bit_depth
        self.crop_percent = crop_percent
        self.burst_limit = burst_limit
        self.weights = weights

    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = []
            if os.path.basename(self.base_dir).startswith(prefix):
                subdirs.append(self.base_dir)
            for r, ds, _ in os.walk(self.base_dir):
                for d in ds:
                    if d.startswith(prefix):
                        subdirs.append(os.path.join(r, d))
            subdirs = sorted(list(set(subdirs)))
            if not subdirs:
                self.log.emit(f"<b style='color:#e67e22;'>Geen mappen gevonden die starten met {prefix}.</b>")
                self.finished.emit()
                return

            self.log.emit(f"<b style='color:#2980b9;'>Verwerken:</b> {len(subdirs)} mappen gevonden.")
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            os.makedirs(os.path.join(coll_root, "DNG"), exist_ok=True)
            os.makedirs(os.path.join(coll_root, "TIFF"), exist_ok=True)

            for i, path in enumerate(subdirs):
                if not self._is_running: break
                name = os.path.basename(path)
                self.log.emit(f"<b>Actief:</b> {name}")
                xmp = find_best_xmp(path)
                if xmp:
                    self.log.emit(f"  <i>Gebruik instellingen: {os.path.basename(xmp)}</i>")

                coll_dng = os.path.join(coll_root, "DNG", f"{name}_HDR.dng")
                coll_tif = os.path.join(coll_root, "TIFF", f"{name}_HDR.tif")

                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method) and not os.path.exists(coll_dng):
                    self.log.emit(f"  -> HDRmerge start...")
                    res = self._do_hdrmerge(path, name)
                    if res:
                        smart_copy(res, coll_dng)
                        self.log.emit(f"  <span style='color:#27ae60;'>+ DNG opgeslagen in verzamelmap.</span>")
                        self.result_path.emit(coll_dng)

                if ((self.mode == "HDR" and ("enfuse" in self.method or "beide" in self.method)) or self.mode == "BURST") and not os.path.exists(coll_tif):
                    self.log.emit(f"  -> {'Enfuse' if self.mode == 'HDR' else 'Burst-median'} start...")
                    res = self._do_enfuse(path, name, xmp)
                    if res:
                        smart_copy(res, coll_tif)
                        self.log.emit(f"  <span style='color:#27ae60;'>+ TIFF opgeslagen in verzamelmap.</span>")
                        self.result_path.emit(coll_tif)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))

            self.log.emit("<br><b style='color:#27ae60;'>✓ HDR/Burst verwerking voltooid.</b>")
        except Exception as e:
            self.log.emit(f"<b style='color:#e74c3c;'>Fout: {e}</b>")
        finally:
            self.finished.emit()

    def _do_enfuse(self, path, name, xmp):
        all_f = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].lower() in VALID_EXTS and "_HDR" not in f])
        files = all_f[:self.burst_limit] if (self.mode == "BURST" and self.burst_limit > 0) else all_f
        if len(files) < 2: return None
        with tempfile.TemporaryDirectory() as tmp_dir:
            tifs = []
            for idx, f in enumerate(files):
                if not self._is_running: return None
                out = os.path.join(tmp_dir, f"img_{idx:03d}.tif")
                cmd = ['darktable-cli', os.path.join(path, f), out, '--core', '--library', ':memory:', '--disable-opencl']
                if xmp: cmd.insert(2, xmp)
                if self.safe_run(cmd) == 0:
                    tifs.append(out)
                self.sub_progress.emit(int(((idx + 1) / len(files)) * 70))

            if len(tifs) < 2: return None
            self.log.emit(f"    - Uitlijnen van {len(tifs)} foto's...")
            ali = os.path.join(tmp_dir, "ali_")
            self.safe_run(['align_image_stack', '-m', '10', '-a', ali, '-c', '20', '-z', '-x', '-y'] + tifs)

            alis = sorted(glob.glob(os.path.join(tmp_dir, "ali_*.tif")))
            for a in alis:
                self.safe_run(['mogrify', '-alpha', 'off', '-type', 'truecolor', '+matte', a])

            out_h = os.path.join(tmp_dir, "result.tif")
            if self.mode == "BURST":
                self.log.emit(f"    - Mediaan berekenen (ruisonderdrukking)...")
                self.safe_run(['convert'] + alis + ['-evaluate-sequence', 'median', out_h])
            else:
                self.log.emit(f"    - Enfuse stitchen...")
                self.safe_run(['enfuse', f'--depth={self.bit_depth}', f'--exposure-weight={self.weights[0]}', f'--saturation-weight={self.weights[1]}', f'--contrast-weight={self.weights[2]}', '--output', out_h] + alis, env=ENV_STABLE)

            if os.path.exists(out_h):
                final = os.path.join(path, f"{name}_HDR.tif")
                if self.crop_percent > 0:
                    self.safe_run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h])
                shutil.copy2(out_h, final)
                return final
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(('.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng')) and "_HDR" not in f])
        if len(raws) < 2: return None
        out = os.path.join(path, f"{name}_HDR.dng")
        if self.safe_run(['hdrmerge', '-b', '16', '-o', out] + raws) == 0:
            if os.path.exists(out):
                return out
        return None

class PanoWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, custom_xmp=None, output_dir="."):
        super().__init__()
        self.files = files
        self.custom_xmp = custom_xmp
        self.output_dir = output_dir

    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            imgs = []
            try:
                self.log.emit(f"<b style='color:#2980b9;'>OpenCV Panorama (8-bit) gestart</b>")
                self.log.emit(f"<i>Bestanden: {len(self.files)} foto's.</i>")

                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    if f.lower().endswith(('.dng', '.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf')):
                        t = os.path.join(tmp_dir, f"p_{i}.tif")
                        xmp = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp(os.path.dirname(f))
                        self.log.emit(f"  -> Converteren: {os.path.basename(f)} (XMP: {os.path.basename(xmp) if xmp else 'Standaard'})")
                        cmd = ['darktable-cli', f, t, '--core', '--library', ':memory:', '--disable-opencl']
                        if xmp: cmd.insert(2, xmp)
                        self.safe_run(cmd)
                        read_f = t
                    else:
                        read_f = f

                    img = cv2.imread(read_f, cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        if img.dtype == np.uint16: img = (img / 256).astype(np.uint8)
                        if img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        imgs.append(img)
                        del img
                    self.sub_progress.emit(int(((i + 1) / len(self.files)) * 80))

                if len(imgs) > 1 and self._is_running:
                    self.log.emit(f"<i>Stitchen met OpenCV Stitcher (Model: Panorama)...</i>")
                    stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                    status, res = stitcher.stitch(imgs)
                    if status != cv2.Stitcher_OK:
                        self.log.emit(f"<i>Panorama mislukt, probeer Scans mode...</i>")
                        status, res = cv2.Stitcher_create(cv2.Stitcher_SCANS).stitch(imgs)

                    if status == cv2.Stitcher_OK:
                        os.makedirs(self.output_dir, exist_ok=True)
                        fname = f"Pano_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif"
                        out = os.path.join(self.output_dir, fname)
                        cv2.imwrite(out, res)
                        self.log.emit(f"<b style='color:#27ae60;'>✓ Panorama gereed:</b> {fname}")
                        self.log.emit(f"<i>Locatie: {self.output_dir}</i>")
                        self.result_path.emit(out)
                    else:
                        self.log.emit("<b style='color:#e74c3c;'>Fout: OpenCV kon de beelden niet stitchen.</b>")
                imgs.clear()
                self.progress.emit(100)
            except Exception as e:
                self.log.emit(f"<b style='color:#e74c3c;'>Fout tijdens panorama: {e}</b>")
            finally:
                self.finished.emit()

class HuginCliWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, output_dir, custom_xmp=None):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.custom_xmp = custom_xmp

    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                self.log.emit("<b style='color:#2980b9;'>Hugin CLI (16-bit) gestart</b>")
                tiffs = []
                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    if f.lower().endswith(('.dng', '.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf')):
                        t = os.path.join(tmp_dir, f"h_{i}.tif")
                        xmp = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp(os.path.dirname(f))
                        self.log.emit(f"  -> Darktable export: {os.path.basename(f)}")
                        cmd = ['darktable-cli', f, t, '--core', '--library', ':memory:', '--disable-opencl']
                        if xmp: cmd.insert(2, xmp)
                        self.safe_run(cmd)
                        tiffs.append(t)
                    else:
                        t = os.path.join(tmp_dir, f"h_{i}{os.path.splitext(f)[1]}")
                        shutil.copy2(f, t)
                        tiffs.append(t)
                    self.sub_progress.emit(int(((i+1)/len(self.files))*20))

                if not self._is_running or not tiffs: return
                pto = os.path.join(tmp_dir, "project.pto")
                prefix = os.path.join(tmp_dir, "output")

                self.log.emit("<i> -> Project genereren (pto_gen)...</i>")
                self.safe_run(['pto_gen', '-o', pto] + tiffs)
                self.sub_progress.emit(30)

                self.log.emit("<i> -> Controlepunten zoeken (cpfind)...</i>")
                self.safe_run(['cpfind', '--multirow', '-o', pto, pto])
                self.sub_progress.emit(50)

                self.log.emit("<i> -> Project optimaliseren (autooptimiser)...</i>")
                self.safe_run(['autooptimiser', '-a', '-m', '-p', '-s', '-o', pto, pto])
                self.log.emit("<i> -> Canvas en crop instellen (pano_modify)...</i>")
                self.safe_run(['pano_modify', '--canvas=AUTO', '--crop=AUTO', '--center', '-o', pto, pto])
                self.sub_progress.emit(70)

                self.log.emit("<i> -> Stitchen final 16-bit TIFF (hugin_executor)...</i>")
                self.safe_run(['hugin_executor', '--stitching', f'--prefix={prefix}', pto])

                res_tif = prefix + ".tif"
                if os.path.exists(res_tif):
                    os.makedirs(self.output_dir, exist_ok=True)
                    fname = f"Pano_Hugin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif"
                    out = os.path.join(self.output_dir, fname)
                    shutil.move(res_tif, out)
                    self.log.emit(f"<b style='color:#27ae60;'>✓ Hugin CLI voltooid:</b> {fname}")
                    self.result_path.emit(out)
                else:
                    self.log.emit("<b style='color:#e74c3c;'>Fout: Hugin CLI heeft geen resultaat gegenereerd.</b>")
            except Exception as e:
                self.log.emit(f"<b style='color:#e74c3c;'>Fout tijdens Hugin CLI: {e}</b>")
            finally:
                self.progress.emit(100)
                self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PanoStack v2.2")
        self.resize(1300, 900)

        missing, deps = check_dependencies()
        if missing:
            msg = "<b>Ontbrekende programma's:</b><br>" + "<br>".join([f"- {m} ({deps[m]})" for m in missing])
            QMessageBox.warning(self, "Systeem Readiness", msg)

        self.worker, self.thread, self.lt, self.last_pano_result = None, None, None, None
        self.active_temp_dirs = []

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorter")
        self.tabs.addTab(self.t2, "2. HDR")
        self.tabs.addTab(self.t3, "3. Burst")
        self.tabs.addTab(self.t4, "4. Panorama")

        self.setup_t1()
        self.setup_t2()
        self.setup_t3()
        self.setup_t4()

        self.tabs.currentChanged.connect(self.on_tab_changed)
        self._sync_paths()

    def on_tab_changed(self, index):
        if index == 3:
            self.refresh_t4()

    def update_enfuse_visibility(self):
        is_enf = self.m2.currentText() != "HDRmerge (DNG)"
        self.ew2.setEnabled(is_enf)
        self.sw2.setEnabled(is_enf)
        self.cw2.setEnabled(is_enf)
        self.cp2.setEnabled(is_enf)

    def update_pano_xmp_visibility(self):
        is_raw_mode = self.f4.currentIndex() != 0
        self.x4.setEnabled(is_raw_mode)
        self.b_xmp4.setEnabled(is_raw_mode)
        self.lbl_x4.setEnabled(is_raw_mode)

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
        CONFIG["LAST_SOURCE_DIR"] = self.s1.text()
        CONFIG["MAX_GAP"] = self.gv.value()
        CONFIG["SAME_GAP"] = self.gv_same.value()
        CONFIG["COPY_FIRST_TO_ROOT"] = self.cb_copy_first.isChecked()
        save_config(CONFIG)
        for d in self.active_temp_dirs:
            try: shutil.rmtree(d)
            except: pass
        event.accept()

    def _sync_paths(self):
        p = self.s1.text().strip()
        if p and os.path.exists(p):
            sp = os.path.join(p, CONFIG["SORTED_DIR_NAME"])
            self.s2.setText(sp)
            self.s3.setText(sp)
            self.s4.setText(os.path.join(p, CONFIG["HDR_COLLECT_NAME"]))

    def _make_thin_bar(self):
        pb = QProgressBar()
        pb.setFixedHeight(8)
        pb.setTextVisible(False)
        pb.setStyleSheet("QProgressBar { border: 1px solid #bbb; background: #eee; } QProgressBar::chunk { background: #05B8CC; }")
        pb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return pb

    def setup_t1(self):
        l = QVBoxLayout(self.t1)
        self.s1 = QLineEdit(CONFIG["LAST_SOURCE_DIR"])
        self.s1.textChanged.connect(self._sync_paths)

        h = QHBoxLayout()
        h.addWidget(QLabel("Bron:"))
        h.addWidget(self.s1)
        b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s1))
        h.addWidget(b)

        h.addWidget(QLabel("HDR Gap:"))
        self.gv = QDoubleSpinBox()
        self.gv.setRange(0.5, 2.5)
        self.gv.setSingleStep(0.5)
        self.gv.setValue(CONFIG["MAX_GAP"])
        h.addWidget(self.gv)

        h.addWidget(QLabel("Burst Gap:"))
        self.gv_same = QDoubleSpinBox()
        self.gv_same.setRange(1.0, 10.0)
        self.gv_same.setSingleStep(0.5)
        self.gv_same.setValue(CONFIG.get("SAME_GAP", 2.5))
        h.addWidget(self.gv_same)

        self.cb_copy_first = QCheckBox("Kopieer 1e naar hoofd")
        self.cb_copy_first.setChecked(CONFIG.get("COPY_FIRST_TO_ROOT", False))
        h.addWidget(self.cb_copy_first)

        btn_i = QPushButton("ⓘ")
        btn_i.clicked.connect(self.show_info)
        btn_i.setFixedWidth(40)
        h.addWidget(btn_i)
        l.addLayout(h)

        self.b1 = QPushButton("Start Sorteren")
        self.b1.clicked.connect(self.go1)
        l.addWidget(self.b1)

        self.p1 = self._make_thin_bar()
        l.addWidget(self.p1)

        split = QSplitter(Qt.Horizontal)
        self.log1 = QTextEdit()
        self.log1.setReadOnly(True)
        self.prev1 = QLabel()
        self.prev1.setAlignment(Qt.AlignCenter)
        sc = QScrollArea()
        sc.setWidget(self.prev1)
        sc.setWidgetResizable(True)
        split.addWidget(self.log1)
        split.addWidget(sc)
        l.addWidget(split)
        split.setSizes([300, 900])

    def setup_t2(self):
        l = QVBoxLayout(self.t2)
        h_main = QHBoxLayout()
        h_main.addWidget(QLabel("Map:"))
        self.s2 = QLineEdit()
        h_main.addWidget(self.s2)
        b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s2))
        h_main.addWidget(b)

        self.m2 = QComboBox()
        h_main.addWidget(self.m2)

        h_main.addWidget(QLabel("Crop:"))
        self.cp2 = QDoubleSpinBox()
        self.cp2.setValue(1.5)
        h_main.addWidget(self.cp2)

        h_main.addWidget(QLabel("Exp:"))
        self.ew2 = QDoubleSpinBox()
        self.ew2.setRange(0,1)
        self.ew2.setValue(1.0)
        self.ew2.setSingleStep(0.1)
        h_main.addWidget(self.ew2)

        h_main.addWidget(QLabel("Sat:"))
        self.sw2 = QDoubleSpinBox()
        self.sw2.setRange(0,1)
        self.sw2.setValue(0.2)
        self.sw2.setSingleStep(0.1)
        h_main.addWidget(self.sw2)

        h_main.addWidget(QLabel("Con:"))
        self.cw2 = QDoubleSpinBox()
        self.cw2.setRange(0,1)
        self.cw2.setValue(0.1)
        self.cw2.setSingleStep(0.1)
        h_main.addWidget(self.cw2)
        l.addLayout(h_main)

        self.b2 = QPushButton("Start HDR")
        self.b2.clicked.connect(lambda: self.go_proc("HDR"))
        l.addWidget(self.b2)

        v_prog = QWidget()
        v_prog.setFixedHeight(60)
        vp_l = QVBoxLayout(v_prog)
        vp_l.setContentsMargins(0,0,0,0)
        vp_l.setSpacing(1)
        vp_l.addWidget(QLabel("Totaal:"))
        self.p2 = self._make_thin_bar()
        vp_l.addWidget(self.p2)
        vp_l.addWidget(QLabel("Huidig:"))

        h_sub = QHBoxLayout()
        self.p2_sub = self._make_thin_bar()
        h_sub.addWidget(self.p2_sub)
        self.stop2 = QPushButton("Stop")
        self.stop2.clicked.connect(self.stop_proc)
        self.stop2.setFixedWidth(50)
        self.stop2.setFixedHeight(18)
        h_sub.addWidget(self.stop2)
        vp_l.addLayout(h_sub)
        l.addWidget(v_prog)

        self.h_split2 = QSplitter(Qt.Horizontal)
        self.log2 = QTextEdit()
        self.log2.setReadOnly(True)
        self.prev2 = QLabel()
        self.prev2.setAlignment(Qt.AlignCenter)
        sc = QScrollArea()
        sc.setWidget(self.prev2)
        sc.setWidgetResizable(True)
        self.h_split2.addWidget(self.log2)
        self.h_split2.addWidget(sc)
        self.h_split2.setSizes([325, 975])
        l.addWidget(self.h_split2)

        self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"])
        self.m2.currentIndexChanged.connect(self.update_enfuse_visibility)
        self.update_enfuse_visibility()

    def setup_t3(self):
        l = QVBoxLayout(self.t3)
        h = QHBoxLayout()
        h.addWidget(QLabel("Map:"))
        self.s3 = QLineEdit()
        h.addWidget(self.s3)
        b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s3))
        h.addWidget(b)

        self.bl3 = QComboBox()
        self.bl3.addItems(["8", "16", "32"])
        h.addWidget(QLabel("Limiet:"))
        h.addWidget(self.bl3)
        l.addLayout(h)

        self.b3 = QPushButton("Start Burst")
        self.b3.clicked.connect(lambda: self.go_proc("BURST"))
        l.addWidget(self.b3)

        v_prog3 = QWidget()
        v_prog3.setFixedHeight(60)
        vp3_l = QVBoxLayout(v_prog3)
        vp3_l.setContentsMargins(0,0,0,0)
        vp3_l.setSpacing(1)
        vp3_l.addWidget(QLabel("Totaal:"))
        self.p3 = self._make_thin_bar()
        vp3_l.addWidget(self.p3)
        vp3_l.addWidget(QLabel("Huidig:"))

        h_sub3 = QHBoxLayout()
        self.p3_sub = self._make_thin_bar()
        h_sub3.addWidget(self.p3_sub)
        self.stop3 = QPushButton("Stop")
        self.stop3.clicked.connect(self.stop_proc)
        self.stop3.setFixedWidth(50)
        self.stop3.setFixedHeight(18)
        h_sub3.addWidget(self.stop3)
        vp3_l.addLayout(h_sub3)
        l.addWidget(v_prog3)

        self.h_split3 = QSplitter(Qt.Horizontal)
        self.log3 = QTextEdit()
        self.log3.setReadOnly(True)
        self.prev3 = QLabel()
        self.prev3.setAlignment(Qt.AlignCenter)
        sc = QScrollArea()
        sc.setWidget(self.prev3)
        sc.setWidgetResizable(True)
        self.h_split3.addWidget(self.log3)
        self.h_split3.addWidget(sc)
        self.h_split3.setSizes([325, 975])
        l.addWidget(self.h_split3)

    def setup_t4(self):
        main_l = QVBoxLayout(self.t4)
        h_paths = QHBoxLayout()
        h_paths.addWidget(QLabel("Verzamelmap:"))
        self.s4 = QLineEdit()
        h_paths.addWidget(self.s4)
        b1 = QPushButton("...")
        b1.clicked.connect(lambda: self.sel(self.s4))
        h_paths.addWidget(b1)

        self.lbl_x4 = QLabel("Vrije XMP:")
        h_paths.addWidget(self.lbl_x4)
        self.x4 = QLineEdit()
        h_paths.addWidget(self.x4)

        self.b_xmp4 = QPushButton("Kies")
        self.b_xmp4.clicked.connect(self.sel_xmp4)
        h_paths.addWidget(self.b_xmp4)
        main_l.addLayout(h_paths)

        h_opts = QHBoxLayout()
        self.f4 = QComboBox()
        h_opts.addWidget(self.f4)
        h_opts.addWidget(QLabel("Grootte:"))
        self.ts4 = QComboBox()
        self.ts4.addItems(["100", "200", "300"])
        self.ts4.setCurrentText("200")
        h_opts.addWidget(self.ts4)

        self.p4_load = self._make_thin_bar()
        h_opts.addWidget(self.p4_load)
        main_l.addLayout(h_opts)

        self.v_split = QSplitter(Qt.Vertical)
        self.lw = QListWidget()
        self.lw.setViewMode(QListWidget.IconMode)
        self.lw.setIconSize(QSize(200, 200))
        self.lw.setSelectionMode(QAbstractItemView.MultiSelection)
        self.v_split.addWidget(self.lw)

        bot_w = QWidget()
        bot_l = QVBoxLayout(bot_w)
        btn_h = QHBoxLayout()
        self.b4 = QPushButton("Start Panorama (8 bit)")
        self.b4.clicked.connect(self.go4)
        btn_h.addWidget(self.b4)

        self.b_dt = QPushButton("Darktable")
        self.b_dt.clicked.connect(self.open_in_darktable)
        self.b_dt.setFixedWidth(90)
        btn_h.addWidget(self.b_dt)

        self.b_hu = QPushButton("Start Hugin (16 Bit)")
        self.b_hu.clicked.connect(self.open_in_hugin)
        self.b_hu.setFixedWidth(130)
        btn_h.addWidget(self.b_hu)

        self.cb_hugin_gui = QCheckBox("Open GUI")
        self.cb_hugin_gui.setFixedWidth(90)
        btn_h.addWidget(self.cb_hugin_gui)
        bot_l.addLayout(btn_h)

        h_s4 = QHBoxLayout()
        self.p4_sub = self._make_thin_bar()
        h_s4.addWidget(self.p4_sub)
        self.stop4 = QPushButton("Stop")
        self.stop4.clicked.connect(self.stop_proc)
        self.stop4.setFixedWidth(50)
        self.stop4.setFixedHeight(18)
        h_s4.addWidget(self.stop4)
        bot_l.addLayout(h_s4)

        self.h_split4 = QSplitter(Qt.Horizontal)
        self.log4 = QTextEdit()
        self.log4.setReadOnly(True)
        self.prev4 = QLabel()
        self.prev4.setAlignment(Qt.AlignCenter)
        sc = QScrollArea()
        sc.setWidget(self.prev4)
        sc.setWidgetResizable(True)
        self.h_split4.addWidget(self.log4)
        self.h_split4.addWidget(sc)
        self.h_split4.setSizes([325, 975])
        bot_l.addWidget(self.h_split4)
        self.v_split.addWidget(bot_w)
        main_l.addWidget(self.v_split)

        self.f4.addItems(["TIFF/JPG", "DNG", "RAW (Serie)", "RAW (enkel)"])
        self.f4.currentIndexChanged.connect(self.refresh_t4)
        self.f4.currentIndexChanged.connect(self.update_pano_xmp_visibility)
        self.ts4.currentIndexChanged.connect(self.refresh_t4)
        self.update_pano_xmp_visibility()

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Kies Map", e.text())
        if d:
            p = os.path.abspath(d)
            e.setText(p)
            self._sync_paths()
            self.refresh_t4()

    def _get_pano_save_dir(self, first_file):
        base_root = self.s1.text().strip()
        if not base_root or not os.path.exists(base_root):
            file_dir = os.path.dirname(first_file)
            if CONFIG["HDR_COLLECT_NAME"] in file_dir:
                base_root = file_dir.split(CONFIG["HDR_COLLECT_NAME"])[0]
            else:
                base_root = os.path.dirname(file_dir)
        return os.path.join(os.path.abspath(base_root), CONFIG["PANO_COLLECT_NAME"])

    def open_in_darktable(self):
        if hasattr(self, 'last_pano_result') and self.last_pano_result and os.path.exists(self.last_pano_result):
            subprocess.Popen(['darktable', self.last_pano_result])
        else:
            QMessageBox.warning(self, "Darktable", "Geen panorama resultaat gevonden.")

    def open_in_hugin(self):
        items = self.lw.selectedItems()
        if not items:
            QMessageBox.warning(self, "Selectie", "Selecteer eerst foto's.")
            return

        files = [it.data(Qt.UserRole) for it in items]

        if self.cb_hugin_gui.isChecked():
            tmp_root = os.path.expanduser("~/panostack_h_gui_temp")
            os.makedirs(tmp_root, exist_ok=True)
            session_id = datetime.now().strftime("%H%M%S")
            tmp_h = os.path.join(tmp_root, session_id)
            os.makedirs(tmp_h, exist_ok=True)
            self.active_temp_dirs.append(tmp_h)

            final_abs_paths = []
            raw_exts = ('.dng', '.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf')

            self.log4.append(f"<i>Hugin GUI sessie gestart ({session_id})...</i>")

            for i, f in enumerate(files):
                if f.lower().endswith(raw_exts):
                    tif_path = os.path.join(tmp_h, f"h_ready_{i}.tif")
                    xmp = self.x4.text() if (self.x4.text() and os.path.exists(self.x4.text())) else find_best_xmp(os.path.dirname(f))
                    cmd = ['darktable-cli', f, tif_path, '--core', '--library', ':memory:', '--disable-opencl']
                    if xmp: cmd.insert(2, xmp)
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(tif_path):
                        final_abs_paths.append(tif_path)
                else:
                    final_abs_paths.append(os.path.abspath(f))

            if final_abs_paths:
                subprocess.Popen(['hugin'] + final_abs_paths)
        else:
            self.log4.clear()
            p_dir = self._get_pano_save_dir(files[0])
            w = HuginCliWorker(files, output_dir=p_dir, custom_xmp=self.x4.text())
            w.sub_progress.connect(self.p4_sub.setValue)
            w.result_path.connect(lambda p: setattr(self, 'last_pano_result', p))
            w.finished.connect(self.lw.clearSelection)
            self._run(w, self.p4_sub, self.log4, self.b_hu, self.stop4)

    def show_info(self):
        info = "<h2>PanoStack v2.2</h2><p>RAW workflow tool.</p><ul><li>Hugin GUI fix: Temp bestanden blijven behouden.</li><li><b>Burst Gap:</b> Voor foto's met gelijke instellingen.</li><li><b>HDR Gap:</b> Voor foto's met verschillende instellingen.</li><li>Uitgebreide proces-informatie in de logschermen.</li></ul>"
        QMessageBox.information(self, "Over PanoStack", info)

    def sel_xmp4(self):
        f, _ = QFileDialog.getOpenFileName(self, "Kies XMP", "", "XMP (*.xmp)")
        if f: self.x4.setText(f)

    def refresh_t4(self):
        source_root = self.s1.text().strip()
        if not os.path.exists(source_root): return

        path = self.s4.text()
        self.b4.setEnabled(False)
        mode = self.f4.currentIndex()
        exts = ('.tif', '.tiff', '.jpg', '.jpeg') if mode == 0 else (('.dng',) if mode == 1 else (('.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng')))

        base_s = os.path.join(source_root, CONFIG["SORTED_DIR_NAME"])

        include_sorted_first = False
        if mode == 3: # RAW (enkel)
            scan_p = source_root
            rec = False
            include_sorted_first = True
        elif mode == 2: # RAW (serie)
            scan_p = base_s
            rec = True
        else: # TIFF of DNG
            sub = "TIFF" if mode == 0 else "DNG"
            scan_p = os.path.join(path, sub) if os.path.exists(os.path.join(path, sub)) else path
            rec = False

        if hasattr(self, 'lt') and self.lt and self.lt.isRunning():
            self.lt.quit()
            self.lt.wait()

        self.lt = QThread()
        self.lwk = ThumbnailWorker(scan_p, exts, rec, include_sorted_first=include_sorted_first)
        self.lwk.moveToThread(self.lt)
        self.lt.started.connect(self.lwk.run)
        self.lwk.thumb_ready.connect(self.add_thumb)
        self.lwk.progress.connect(self.p4_load.setValue)
        self.lwk.finished.connect(self.lt.quit)
        self.lwk.finished.connect(lambda: self.b4.setEnabled(True))
        self.lt.start()
        self.lw.clear()

    def add_thumb(self, n, p, img):
        it = QListWidgetItem(n)
        it.setData(Qt.UserRole, p)
        size = int(self.ts4.currentText())
        it.setIcon(QIcon(QPixmap.fromImage(img.scaled(size, size, Qt.KeepAspectRatio))))
        self.lw.addItem(it)

    def stop_proc(self):
        if self.worker:
            self.worker.stop()

    def go1(self):
        self.log1.clear()
        w = SortWorker(self.s1.text(), self.gv.value(), self.gv_same.value(), self.cb_copy_first.isChecked())
        w.finished.connect(self.refresh_t4)
        self._run(w, self.p1, self.log1, self.b1)

    def go_proc(self, mode):
        p, log, b, stop = (self.s2.text(), self.log2, self.b2, self.stop2) if mode == "HDR" else (self.s3.text(), self.log3, self.b3, self.stop3)
        log.clear()
        w = HdrBurstWorker(p, mode, self.m2.currentText(), "16", self.cp2.value(), int(self.bl3.currentText()) if mode == "BURST" else 0, weights=(self.ew2.value(), self.sw2.value(), self.cw2.value()) if mode=="HDR" else (1.0,0.2,0.1))
        prog_bar = self.p2 if mode == "HDR" else self.p3
        sub_prog = self.p2_sub if mode == "HDR" else self.p3_sub
        w.sub_progress.connect(sub_prog.setValue)
        self._run(w, prog_bar, log, b, stop)

    def go4(self):
        items = self.lw.selectedItems()
        if items:
            files = [it.data(Qt.UserRole) for it in items]
            self.log4.clear()
            p_dir = self._get_pano_save_dir(files[0])
            w = PanoWorker(files, self.x4.text(), output_dir=p_dir)
            w.sub_progress.connect(self.p4_sub.setValue)
            w.result_path.connect(lambda p: setattr(self, 'last_pano_result', p))
            w.finished.connect(self.lw.clearSelection)
            self._run(w, self.p4_sub, self.log4, self.b4, self.stop4)

    def _run(self, w, p, log, b, s_btn=None):
        self.worker = w
        self.thread = QThread()
        b.setEnabled(False)
        if s_btn:
            s_btn.setEnabled(True)
        self.clear_prev_label(w)
        w.moveToThread(self.thread)
        w.log.connect(log.append)
        w.progress.connect(p.setValue)
        w.finished.connect(self.thread.quit)
        w.finished.connect(lambda: b.setEnabled(True))
        if s_btn:
            w.finished.connect(lambda: s_btn.setEnabled(False))
        if hasattr(w, 'result_path'):
            w.result_path.connect(lambda path: self.show_prev(path, w))
        self.thread.started.connect(w.run)
        self.thread.start()

    def clear_prev_label(self, w):
        if isinstance(w, SortWorker):
            target = self.prev1
        elif hasattr(w, 'mode') and w.mode == "HDR":
            target = self.prev2
        elif hasattr(w, 'mode') and w.mode == "BURST":
            target = self.prev3
        else:
            target = self.prev4
        target.clear()
        target.setText("Verwerken...")
        target.setStyleSheet("color: #7f8c8d; font-style: italic; font-size: 14px;")

    def show_prev(self, path, w):
        if isinstance(w, SortWorker):
            target = self.prev1
        elif hasattr(w, 'mode') and w.mode == "HDR":
            target = self.prev2
        elif hasattr(w, 'mode') and w.mode == "BURST":
            target = self.prev3
        else:
            target = self.prev4
        img = get_image_robust(path)
        if not img.isNull():
            target.setStyleSheet("")
            target.setPixmap(QPixmap.fromImage(img).scaled(target.width(), target.height(), Qt.KeepAspectRatio))

class ThumbnailWorker(QObject):
    finished, progress, thumb_ready = Signal(), Signal(int), Signal(str, str, QImage)
    def __init__(self, directory, extensions, recursive=False, include_sorted_first=False):
        super().__init__()
        self.directory = directory
        self.extensions = extensions
        self.recursive = recursive
        self.include_sorted_first = include_sorted_first

    def run(self):
        if not os.path.exists(self.directory):
            self.finished.emit()
            return

        found_paths = set()
        fps = []

        if self.recursive:
            for r, _, fs in os.walk(self.directory):
                folder_name = os.path.basename(r)
                if folder_name.startswith("Serie_"):
                    for f in sorted(fs):
                        if f.lower().endswith(self.extensions):
                            full_path = os.path.join(r, f)
                            if full_path not in found_paths:
                                fps.append(full_path)
                                found_paths.add(full_path)
        else:
            for f in sorted(os.listdir(self.directory)):
                if f.lower().endswith(self.extensions):
                    full_path = os.path.join(self.directory, f)
                    if full_path not in found_paths:
                        fps.append(full_path)
                        found_paths.add(full_path)

            if self.include_sorted_first:
                sorted_root = os.path.join(self.directory, CONFIG["SORTED_DIR_NAME"])
                if os.path.exists(sorted_root):
                    for r, ds, fs in os.walk(sorted_root):
                        folder_name = os.path.basename(r)
                        if folder_name.startswith(("Serie_", "Reeks_", "Burst_")):
                            valid_fs = sorted([f for f in fs if f.lower().endswith(self.extensions)])
                            if valid_fs:
                                full_path = os.path.join(r, valid_fs[0])
                                if full_path not in found_paths:
                                    fps.append(full_path)
                                    found_paths.add(full_path)

        for i, fp in enumerate(fps):
            img = get_image_robust(fp)
            if not img.isNull():
                self.thumb_ready.emit(os.path.basename(fp), fp, img)
            self.progress.emit(int(((i + 1) / (len(fps) or 1)) * 100))
        self.finished.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
