#!/usr/bin/env python3
"""
PanoStack Flow (v9.8.56)
- FIX: Volledige herstructurering van Panorama-tab voor stabiliteit.
- BEHOUDEN: Uitgebreide info in Tab 1 (inclusief Burst).
- BEHOUDEN: Dubbele voortgangsbalken in Tab 2.
- BEHOUDEN: Gedetailleerde stap-voor-stap logging (1/4, 2/4, etc).
- BEHOUDEN: Grote thumbnails (200x200) in Panorama Tab.
"""

import sys
import os
import shutil
import subprocess
from datetime import datetime
import glob
import time
import tempfile
import re
import gc

# --- CONFIGURATIE ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
}
REQUIRED_TOOLS = ['exiftool', 'darktable-cli', 'align_image_stack', 'enfuse', 'hdrmerge', 'mogrify']
SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG', '.tif', '.tiff']
VALID_EXTS = {ext.lower() for ext in SUPPORTED_EXTS}

cores = os.cpu_count() or 2
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# --- IMPORTS ---
try:
    import cv2
    import numpy as np
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
        QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox,
        QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea, QListView
    )
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QCursor, QImage
except ImportError as e:
    print(f"Fout: {e}")
    sys.exit(1)

# --- HELPERS ---
def smart_copy(src, dst):
    if sys.platform == "linux":
        try:
            subprocess.run(['cp', '--reflink=auto', src, dst], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except: pass
    try:
        shutil.copy2(src, dst)
        return True
    except: return False

def reset_and_copy_metadata(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    try:
        subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', '--Orientation', '-Orientation=1', '-n', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def copy_metadata_full(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    try:
        subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def get_image_robust(path):
    if not path or not os.path.exists(path): return QImage()
    ext = os.path.splitext(path)[1].lower()
    img = QImage()
    if ext == ".dng":
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            try:
                res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
                if res.stdout and len(res.stdout) > 5000:
                    img.loadFromData(res.stdout)
                    break
            except: continue
    if img.isNull(): img.load(path)
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

# --- WORKERS ---
class BaseWorker(QObject):
    finished = Signal()
    progress = Signal(int)
    log = Signal(str)
    result_path = Signal(str)
    def __init__(self):
        super().__init__()
        self._is_running = True
    def stop(self):
        self._is_running = False

class ThumbnailWorker(QObject):
    finished = Signal()
    progress = Signal(int)
    thumb_ready = Signal(str, str, QImage)
    def __init__(self, directory, extensions):
        super().__init__()
        self.directory = directory
        self.extensions = extensions
        self._is_running = True
    def stop(self): self._is_running = False
    def run(self):
        all_files = []
        for root, ds, fs in os.walk(self.directory):
            if not self._is_running: break
            for f in fs:
                if f.lower().endswith(self.extensions):
                    all_files.append(os.path.join(root, f))
        total = len(all_files)
        if total == 0:
            self.finished.emit()
            return
        for i, fp in enumerate(sorted(all_files)):
            if not self._is_running: break
            img = get_image_robust(fp)
            if not img.isNull():
                self.thumb_ready.emit(os.path.basename(fp), fp, img)
            self.progress.emit(int(((i + 1) / total) * 100))
        self.finished.emit()

class SortWorker(BaseWorker):
    def __init__(self, source_dir, stack_size, keep_first, max_gap):
        super().__init__()
        self.source_dir = source_dir
        self.stack_size = stack_size
        self.keep_first = keep_first
        self.max_gap = max_gap
    @Slot()
    def run(self):
        try:
            self.log.emit("Metadata analyseren...")
            cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            photo_list = []
            for line in filter(None, result.stdout.splitlines()):
                p = line.split('\t')
                ext = os.path.splitext(p[0])[1].lower()
                if len(p) < 6 or ext not in VALID_EXTS: continue
                dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S")
                model = p[4].strip().replace(' ', '_').replace('/', '-') if p[4] else "Onbekende_Camera"
                iso = int(re.sub(r"\D", "", p[5])) if p[5] else 0
                photo_list.append({'name': p[0], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[2]}A{p[3]}", 'model': model, 'iso': iso})
            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest_root, exist_ok=True)
            curr = []; seq = 0
            for i, photo in enumerate(photo_list):
                if not self._is_running: break
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap):
                    curr.append(photo)
                else:
                    seq = self._process_group(curr, dest_root, seq)
                    curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr: self._process_group(curr, dest_root, seq)
            self.log.emit("✓ Sorteren voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _process_group(self, group, dest_root, seq):
        if len(group) < 2: return seq
        is_hdr = len(set([p['exp'] for p in group])) > 1
        if is_hdr:
            for i in range(len(group) // self.stack_size):
                seq += 1
                self._target_folder(group[i*self.stack_size:(i+1)*self.stack_size], dest_root, "Reeks", seq)
        else:
            prefix = "Burst" if group[0]['iso'] > 800 else "Serie"
            seq += 1
            self._target_folder(group, dest_root, prefix, seq)
        return seq

    def _target_folder(self, subset, dest_root, type_prefix, seq):
        meta = subset[0]
        iso_label = f"_ISO{meta['iso']}" if meta['iso'] >= 1600 else ""
        target = os.path.join(dest_root, meta['model'], meta['date'], f"{type_prefix}_{seq:03d}{iso_label}")
        os.makedirs(target, exist_ok=True)
        for idx, f in enumerate(subset):
            src = os.path.join(self.source_dir, f['name'])
            if os.path.exists(src) and smart_copy(src, os.path.join(target, f['name'])):
                if not (self.keep_first and idx == 0): os.remove(src)

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, collect, cleanup, crop_percent, burst_limit=0):
        super().__init__()
        self.base_dir = base_dir
        self.mode = mode
        self.method = method.lower()
        self.bit_depth = bit_depth
        self.collect = collect
        self.cleanup = cleanup
        self.crop_percent = crop_percent
        self.burst_limit = burst_limit

    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = []
            for r, ds, fs in os.walk(self.base_dir):
                for d in ds:
                    if d.startswith(prefix): subdirs.append(os.path.join(r, d))
            if not subdirs:
                self.log.emit("Geen mappen gevonden.")
                self.finished.emit()
                return

            xmp = os.path.join(SCRIPT_DIR, CONFIG["DT_XMP_FILE"])
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            os.makedirs(coll_root, exist_ok=True)

            total_sets = len(subdirs)
            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: break
                name = os.path.basename(path)
                self.log.emit(f"--- <b>Set {i+1}/{total_sets}: {name}</b> ---")
                cfg = os.path.expanduser("~/.cache/panostack_temp")
                if os.path.exists(cfg): shutil.rmtree(cfg)
                os.makedirs(cfg)

                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method):
                    self.log.emit("  [Stap] HDRmerge DNG genereren...")
                    res_dng = self._do_hdrmerge(path, name)
                    if res_dng:
                        if self.collect:
                            d_dest = os.path.join(coll_root, "DNG")
                            os.makedirs(d_dest, exist_ok=True)
                            shutil.copy2(res_dng, os.path.join(d_dest, os.path.basename(res_dng)))
                        self.result_path.emit(res_dng)

                if (self.mode == "HDR" and ("enfuse" in self.method or "beide" in self.method)) or self.mode == "BURST":
                    res_tif = self._do_enfuse(path, name, cfg, xmp)
                    if res_tif:
                        if self.collect:
                            t_dest = os.path.join(coll_root, "TIFF")
                            os.makedirs(t_dest, exist_ok=True)
                            shutil.copy2(res_tif, os.path.join(t_dest, os.path.basename(res_tif)))
                        self.result_path.emit(res_tif)

                self.progress.emit(int(((i + 1) / total_sets) * 100))
                self.sub_progress.emit(0)

            self.log.emit("✓ Alle taken voltooid." if self._is_running else "⚠ Onderbroken.")
        except Exception as e: self.log.emit(f"Fout in worker: {e}")
        finally: self.finished.emit()

    def _do_enfuse(self, path, name, cfg, xmp):
        files = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].lower() in VALID_EXTS])
        num_files = len(files)
        if num_files < 2: return None
        tmp = os.path.join(path, ".tmp_hdr")
        if os.path.exists(tmp): shutil.rmtree(tmp)
        os.makedirs(tmp)
        tifs = []

        for idx, f in enumerate(files):
            if not self._is_running: return None
            self.sub_progress.emit(int(((idx) / (num_files + 2)) * 100))
            src, out = os.path.join(path, f), os.path.join(tmp, f"img_{idx:03d}.tif")
            if f.lower().endswith(('.tif', '.tiff')):
                self.log.emit(f"  [1/4] Kopiëren: {f} ({idx+1}/{num_files})")
                shutil.copy2(src, out)
                tifs.append(out)
            else:
                self.log.emit(f"  [1/4] Converteren: {f} ({idx+1}/{num_files})")
                cmd = ['darktable-cli', src]
                if os.path.exists(xmp): cmd.append(xmp)
                cmd.append(out)
                cmd.extend(['--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl'])
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(out): tifs.append(out)

        if len(tifs) < 2: return None

        self.sub_progress.emit(int(((num_files) / (num_files + 2)) * 100))
        self.log.emit("  [2/4] Beelden uitlijnen (align_image_stack)...")
        ali = os.path.join(tmp, "ali_")
        subprocess.run(['align_image_stack', '-m', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        alis = sorted(glob.glob(os.path.join(tmp, "ali_*.tif"))) or tifs

        self.sub_progress.emit(int(((num_files + 1) / (num_files + 2)) * 100))
        self.log.emit(f"  [3/4] Samenvoegen (Enfuse {self.bit_depth}-bit)...")
        out_h = os.path.join(path, f"{name}_HDR.tif")
        subprocess.run(['enfuse', f'--depth={self.bit_depth}', '--output', out_h] + alis, env=ENV_STABLE, stdout=subprocess.DEVNULL)

        if os.path.exists(out_h):
            self.log.emit("  [4/4] Metadata kopiëren en trimmen...")
            if self.crop_percent > 0:
                subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h], stdout=subprocess.DEVNULL)
            reset_and_copy_metadata(os.path.join(path, files[0]), out_h)
            self.sub_progress.emit(100)
            return out_h
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].lower() in ['.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng']])
        if len(raws) < 2: return None
        out_f = os.path.join(path, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-b', '16', '-o', out_f] + raws, stdout=subprocess.DEVNULL)
        if os.path.exists(out_f):
            copy_metadata_full(raws[0], out_f)
            return out_f
        return None

class PanoWorker(BaseWorker):
    def __init__(self, files):
        super().__init__()
        self.files = files
    @Slot()
    def run(self):
        temp_dir = tempfile.mkdtemp()
        imgs = []
        try:
            self.log.emit(f"Stitchen van {len(self.files)} beelden...")
            for i, f in enumerate(self.files):
                if not self._is_running: break
                if f.lower().endswith('.dng'):
                    tmp_tif = os.path.join(temp_dir, f"pano_tmp_{i}.tif")
                    subprocess.run(['darktable-cli', f, tmp_tif, '--library', ':memory:'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    img = cv2.imread(tmp_tif)
                else: img = cv2.imread(f)
                if img is not None: imgs.append(img)
            if len(imgs) >= 2 and self._is_running:
                status, res = cv2.Stitcher_create(cv2.Stitcher_PANORAMA).stitch(imgs)
                if status == cv2.Stitcher_OK:
                    out_p = os.path.join(os.path.dirname(self.files[0]), f"Pano_{datetime.now().strftime('%H%M%S')}.tif")
                    cv2.imwrite(out_p, res)
                    self.log.emit(f"✓ Klaar: {os.path.basename(out_p)}")
                    self.result_path.emit(out_p)
                else: self.log.emit(f"⚠ Stitchen mislukt: {status}")
        finally:
            imgs.clear(); gc.collect()
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PanoStack Flow v9.8.56")
        self.setGeometry(100, 100, 1400, 950)
        self.worker = None
        self.thread = None
        self.load_thread = None
        self.is_loading_thumbs = False
        self.active_preview_path = ""

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer")
        self.tabs.addTab(self.t2, "2. HDR")
        self.tabs.addTab(self.t3, "3. Burst")
        self.tabs.addTab(self.t4, "4. Panorama")

        self.setup_t1()
        self.setup_t2()
        self.setup_t3()
        self.setup_t4()

    def on_tab_changed(self, index):
        if index == 3: self.refresh_t4_threaded()

    def setup_t1(self):
        l = QVBoxLayout(self.t1)
        self.s1 = QLineEdit(os.path.expanduser("~"))
        h_src = QHBoxLayout()
        h_src.addWidget(QLabel("Bron RAW:"))
        h_src.addWidget(self.s1)
        b1_br = QPushButton("...")
        b1_br.setFixedWidth(40)
        b1_br.clicked.connect(lambda: self.sel(self.s1))
        h_src.addWidget(b1_br)
        b_info = QPushButton("ⓘ", clicked=self.show_info)
        b_info.setFixedWidth(40)
        h_src.addWidget(b_info)
        l.addLayout(h_src)

        h_all = QHBoxLayout()
        h_all.setAlignment(Qt.AlignLeft)
        h_all.setSpacing(10)
        h_all.addWidget(QLabel("Pauze (sec):"))
        self.gv = QDoubleSpinBox()
        self.gv.setValue(1.0)
        self.gv.setFixedWidth(60)
        h_all.addWidget(self.gv)
        h_all.addWidget(QLabel("Bracket:"))
        self.sc = QComboBox()
        self.sc.addItems(["3","5","7"])
        self.sc.setCurrentIndex(1)
        self.sc.setFixedWidth(50)
        h_all.addWidget(self.sc)
        self.b1 = QPushButton("Start Sorteren", clicked=self.go1)
        self.b1.setFixedWidth(150)
        h_all.addWidget(self.b1)
        l.addLayout(h_all)

        self.p1 = QProgressBar()
        l.addWidget(self.p1)
        self.log1 = QTextEdit()
        l.addWidget(self.log1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2)
        self.s2 = QLineEdit()
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Map:"))
        h2.addWidget(self.s2)
        b2_br = QPushButton("...")
        b2_br.setFixedWidth(40)
        b2_br.clicked.connect(lambda: self.sel(self.s2))
        h2.addWidget(b2_br)
        l.addLayout(h2)

        h_opts = QHBoxLayout()
        h_opts.setAlignment(Qt.AlignLeft)
        h_opts.setSpacing(10)
        self.m2 = QComboBox()
        self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Enfuse + HDRmerge"])
        h_opts.addWidget(self.m2)
        h_opts.addWidget(QLabel("Bit:"))
        self.bd2 = QComboBox()
        self.bd2.addItems(["8","16"])
        self.bd2.setCurrentIndex(1)
        self.bd2.setFixedWidth(50)
        h_opts.addWidget(self.bd2)
        h_opts.addWidget(QLabel("Randjes (%):"))
        self.cp2 = QDoubleSpinBox()
        self.cp2.setValue(1.5)
        self.cp2.setFixedWidth(60)
        h_opts.addWidget(self.cp2)
        l.addLayout(h_opts)

        self.b2 = QPushButton("Start HDR", clicked=lambda: self.go_proc("HDR"))
        l.addWidget(self.b2)

        l.addWidget(QLabel("Totaal proces:"))
        self.p2 = QProgressBar()
        l.addWidget(self.p2)

        l.addWidget(QLabel("Huidige map:"))
        h_sub = QHBoxLayout()
        self.p2_sub = QProgressBar()
        h_sub.addWidget(self.p2_sub)
        self.stop2 = QPushButton("Stop", clicked=self.stop_proc)
        self.stop2.setFixedWidth(80)
        self.stop2.setEnabled(False)
        h_sub.addWidget(self.stop2)
        l.addLayout(h_sub)

        h_split = QHBoxLayout()
        self.log2 = QTextEdit()
        self.scroll2 = QScrollArea()
        self.prev2 = QLabel()
        self.prev2.setAlignment(Qt.AlignCenter)
        self.scroll2.setWidget(self.prev2)
        self.scroll2.setWidgetResizable(True)
        h_split.addWidget(self.log2, 1)
        h_split.addWidget(self.scroll2, 1)
        l.addLayout(h_split)

    def setup_t3(self):
        l = QVBoxLayout(self.t3)
        self.s3 = QLineEdit()
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Map:"))
        h3.addWidget(self.s3)
        b3_br = QPushButton("...")
        b3_br.setFixedWidth(40)
        b3_br.clicked.connect(lambda: self.sel(self.s3))
        h3.addWidget(b3_br)
        l.addLayout(h3)
        self.b3 = QPushButton("Start Burst", clicked=lambda: self.go_proc("BURST"))
        l.addWidget(self.b3)
        self.p3 = QProgressBar()
        l.addWidget(self.p3)
        self.log3 = QTextEdit()
        l.addWidget(self.log3)

    def setup_t4(self):
        layout = QVBoxLayout(self.t4)

        h_path = QHBoxLayout()
        h_path.addWidget(QLabel("Verzamelmap:"))
        self.s4 = QLineEdit()
        h_path.addWidget(self.s4)
        b4_br = QPushButton("...")
        b4_br.setFixedWidth(40)
        b4_br.clicked.connect(lambda: self.sel(self.s4))
        h_path.addWidget(b4_br)
        layout.addLayout(h_path)

        h_ctrl = QHBoxLayout()
        self.f4 = QComboBox()
        self.f4.addItems(["TIFF/JPG", "DNG"])
        self.f4.currentIndexChanged.connect(self.refresh_t4_threaded)
        h_ctrl.addWidget(self.f4)
        h_ctrl.addWidget(QLabel("<i>Laden gebeurt automatisch.</i>"))
        layout.addLayout(h_ctrl)

        self.p4_load = QProgressBar()
        layout.addWidget(self.p4_load)

        self.lw = QListWidget()
        self.lw.setViewMode(QListWidget.IconMode)
        self.lw.setSelectionMode(QAbstractItemView.MultiSelection)
        self.lw.setResizeMode(QListView.Adjust)
        self.lw.setIconSize(QSize(200, 200))
        self.lw.setMinimumHeight(400)
        layout.addWidget(self.lw)

        self.b4_stitch = QPushButton("Start Panorama", clicked=self.go4)
        layout.addWidget(self.b4_stitch)

        h_split = QHBoxLayout()
        v_log = QVBoxLayout()
        self.p4 = QProgressBar()
        v_log.addWidget(self.p4)
        self.log4 = QTextEdit()
        v_log.addWidget(self.log4)
        h_split.addLayout(v_log, 1)

        v_prev = QVBoxLayout()
        self.scroll4 = QScrollArea()
        self.prev4 = QLabel()
        self.prev4.setAlignment(Qt.AlignCenter)
        self.scroll4.setWidget(self.prev4)
        self.scroll4.setWidgetResizable(True)
        v_prev.addWidget(self.scroll4)
        self.btn_dt = QPushButton("Open in Darktable", clicked=self.open_dt_from_preview)
        v_prev.addWidget(self.btn_dt)
        h_split.addLayout(v_prev, 1)
        layout.addLayout(h_split)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Selecteer Map", e.text())
        if d:
            e.setText(d)
            if e == self.s1:
                p = os.path.join(d, CONFIG["SORTED_DIR_NAME"])
                self.s2.setText(p)
                self.s3.setText(p)
                self.s4.setText(os.path.join(d, CONFIG["HDR_COLLECT_NAME"]))
            if e == self.s4 or (e == self.s1 and self.tabs.currentIndex() == 3):
                self.refresh_t4_threaded()

    def show_info(self):
        info_text = (
            "<h3>PanoStack Flow - Informatie & Workflow</h3>"
            "<p>Deze tool automatiseert het proces van RAW-sortering tot panorama-stitching.</p>"
            "<b>Stap 1: Sorteren</b>"
            "<ul>"
            "<li>Selecteer je bronmap met RAW-bestanden.</li>"
            "<li><b>Pauze:</b> Maximale tijd tussen foto's in één reeks.</li>"
            "<li><b>Bracket:</b> Aantal foto's per HDR-set (bijv. 3 of 5).</li>"
            "<li>Reeksen worden verplaatst naar de map <i>'geordend_op_reeks'</i>.</li>"
            "</ul>"
            "<b>Stap 2: HDR (High Dynamic Range)</b>"
            "<ul>"
            "<li><b>HDRmerge:</b> Creëert een 16-bit DNG (behoudt RAW-flexibiliteit).</li>"
            "<li><b>Enfuse:</b> Combineert verschillende belichtingen tot een TIFF.</li>"
            "</ul>"
            "<b>Stap 3: Burst (Ruisvermindering)</b>"
            "<ul>"
            "<li>Bedoeld voor reeksen met een hoge ISO-waarde (vaak gemarkeerd als 'Burst').</li>"
            "<li>Door meerdere opnames van hetzelfde onderwerp te 'stacken', wordt ruis weggemiddeld.</li>"
            "<li>Dit resulteert in een aanzienlijk schonere TIFF-afbeelding met meer behoud van detail.</li>"
            "</ul>"
            "<b>Stap 4: Panorama</b>"
            "<ul>"
            "<li>Selecteer de gewenste HDR/Burst resultaten en klik op 'Start Panorama'.</li>"
            "</ul>"
            "<p><i>Vereisten: exiftool, darktable-cli, hugin, hdrmerge.</i></p>"
        )
        QMessageBox.information(self, "Handleiding", info_text)

    def refresh_t4_threaded(self):
        if self.is_loading_thumbs: return
        if self.load_thread and self.load_thread.isRunning():
            self.load_worker.stop()
            self.load_thread.quit()
            self.load_thread.wait()
        map_p = self.s4.text()
        if not os.path.exists(map_p): return
        self.is_loading_thumbs = True
        self.lw.clear()
        exts = ('.tif', '.tiff', '.jpg') if self.f4.currentIndex() == 0 else ('.dng',)
        self.load_thread = QThread()
        self.load_worker = ThumbnailWorker(map_p, exts)
        self.load_worker.moveToThread(self.load_thread)
        self.load_thread.started.connect(self.load_worker.run)
        self.load_worker.thumb_ready.connect(self.add_thumb_item)
        self.load_worker.progress.connect(self.p4_load.setValue)
        self.load_worker.finished.connect(self.on_load_finished)
        self.load_thread.start()

    def on_load_finished(self):
        self.is_loading_thumbs = False
        self.load_thread.quit()

    def add_thumb_item(self, name, path, qimage):
        it = QListWidgetItem(name)
        it.setData(Qt.UserRole, path)
        it.setIcon(QIcon(QPixmap.fromImage(qimage.scaled(200, 200, Qt.KeepAspectRatio))))
        self.lw.addItem(it)

    def open_dt_from_preview(self):
        if self.active_preview_path and os.path.exists(self.active_preview_path):
            subprocess.Popen(['darktable', '--library', ':memory:', self.active_preview_path])

    def stop_proc(self):
        if self.worker:
            self.worker.stop()
            self.log2.append("<b>Wachten op stop...</b>")

    def go1(self): self._run(SortWorker(self.s1.text(), int(self.sc.currentText()), True, self.gv.value()), self.p1, self.log1, self.b1)

    def go_proc(self, mode):
        if mode == "HDR":
            w = HdrBurstWorker(self.s2.text(), "HDR", self.m2.currentText(), self.bd2.currentText(), True, False, self.cp2.value())
            w.sub_progress.connect(self.p2_sub.setValue)
            self._run(w, self.p2, self.log2, self.b2, self.stop2)
        else:
            self._run(HdrBurstWorker(self.s3.text(), "BURST", "enfuse", "16", True, False, 1.5, 8), self.p3, self.log3, self.b3)

    def go4(self):
        selected = [self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]
        if not selected:
            QMessageBox.warning(self, "Selectie", "Selecteer eerst beelden in de lijst.")
            return
        self._run(PanoWorker(selected), self.p4, self.log4, self.b4_stitch)

    def _run(self, w, p, log, b, s_btn=None):
        self.worker = w
        self.thread = QThread()
        b.setEnabled(False)
        if s_btn: s_btn.setEnabled(True)
        w.moveToThread(self.thread)
        w.log.connect(log.append)
        w.progress.connect(p.setValue)

        def on_fin():
            self.thread.quit()
            b.setEnabled(True)
            if s_btn: s_btn.setEnabled(False)
            if isinstance(w, PanoWorker): self.refresh_t4_threaded()

        w.finished.connect(on_fin)
        if hasattr(w, 'result_path'):
            if isinstance(w, PanoWorker): w.result_path.connect(self.show_prev_t4)
            else: w.result_path.connect(self.show_prev_t2)

        self.thread.started.connect(w.run)
        self.thread.start()

    def show_prev_t2(self, path): self.show_prev_generic(path, self.prev2, self.scroll2)
    def show_prev_t4(self, path): self.show_prev_generic(path, self.prev4, self.scroll4)
    def show_prev_generic(self, path, tp, ts):
        self.active_preview_path = path
        img = get_image_robust(path)
        if not img.isNull():
            tp.setPixmap(QPixmap.fromImage(img).scaled(ts.width()-20, 4000, Qt.KeepAspectRatio))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
