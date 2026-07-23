#!/usr/bin/env python3
"""
PanoStack (v0.1)
- FIX: Panorama startknop geblokkeerd tijdens inlezen.
- FIX: RAW(Serie) filtert nu strikt op 'Serie_' mappen.
- FIX: Auto-refresh bij selectie Panorama-tab.
- HERSTEL: Enfuse wegingen (Exp/Sat/Con) in Tab 2.
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

# --- CONFIGURATIE BEHEER ---
DEFAULT_CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
    "LAST_SOURCE_DIR": os.path.expanduser("~"),
    "MAX_GAP": 1.0
}

CONFIG_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "panostack_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except: return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except: pass

CONFIG = load_config()
VALID_EXTS = {ext.lower() for ext in ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG', '.tif', '.tiff', '.jpg', '.jpeg']}

cores = os.cpu_count() or 2
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# --- HELPERS ---

def smart_copy(src, dst):
    try:
        subprocess.run(['cp', '--reflink=auto', src, dst], check=True, capture_output=True)
        return True
    except:
        try: shutil.copy2(src, dst); return True
        except: return False

def reset_and_copy_metadata(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', '--Orientation', '-Orientation=1', '-n', dst_hdr], capture_output=True)

def copy_metadata_full(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', dst_hdr], capture_output=True)

def get_image_robust(path):
    if not path or not os.path.exists(path): return QImage()
    img = QImage()
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.dng', '.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf']:
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
            if res.stdout and len(res.stdout) > 5000:
                img.loadFromData(res.stdout)
                if not img.isNull(): break
        if img.isNull(): return QImage()
    else: img.load(path)
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

# --- IMPORTS ---
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
        QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox,
        QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea,
        QSplitter, QSizePolicy
    )
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QImage
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Fout: {e}"); sys.exit(1)

# --- WORKERS ---

class BaseWorker(QObject):
    finished, progress, log, result_path = Signal(), Signal(int), Signal(str), Signal(str)
    def __init__(self):
        super().__init__()
        self._is_running = True; self.active_proc = None
    def stop(self):
        self._is_running = False
        if self.active_proc:
            try: self.active_proc.terminate(); self.active_proc.wait(timeout=2)
            except:
                try: self.active_proc.kill()
                except: pass
        self.log.emit("<br><b style='color:red;'>[STOP] Proces afgebroken.</b>")
    def safe_run(self, cmd, env=None):
        if not self._is_running: return 1
        try:
            self.active_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            return self.active_proc.wait()
        except: return 1

class SortWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, source_dir, max_gap):
        super().__init__(); self.source_dir, self.max_gap = source_dir, max_gap
    @Slot()
    def run(self):
        try:
            self.log.emit(f"<b>Start sorteren:</b> {self.source_dir}")
            all_files = sorted([f for f in os.listdir(self.source_dir) if any(f.lower().endswith(ext) for ext in VALID_EXTS) and not f.lower().endswith('.xmp') and f != CONFIG["SORTED_DIR_NAME"]])
            if not all_files: self.log.emit("Geen bestanden."); self.finished.emit(); return
            photos = []
            for i in range(0, len(all_files), 40):
                if not self._is_running: break
                batch = all_files[i:i + 40]; batch_paths = [os.path.join(self.source_dir, f) for f in batch]
                self.result_path.emit(batch_paths[0])
                res = subprocess.run(['exiftool', '-q', '-f', '-S3', '-T', '-n', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO'] + batch_paths, capture_output=True, text=True)
                for idx, line in enumerate(res.stdout.strip().splitlines()):
                    p = line.split('\t')
                    if len(p) >= 5:
                        try:
                            dt = datetime.strptime(p[0].split('.')[0].split('+')[0].strip(), "%Y:%m:%d %H:%M:%S")
                            photos.append({'name': batch[idx], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[1]}A{p[2]}", 'iso': int(re.sub(r"\D", "", p[4])) if p[4] != "-" else 0, 'model': p[3].strip().replace(' ','_')})
                        except: continue
                self.sub_progress.emit(int(((i + len(batch)) / len(all_files)) * 100))
            photos.sort(key=lambda x: x['ts']); dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest_root, exist_ok=True)
            curr, seq = [], 0
            for idx, p in enumerate(photos):
                if not self._is_running: break
                is_same = curr and (p['exp'] == curr[-1]['exp'] and p['iso'] == curr[-1]['iso'])
                if not curr or (p['ts'] - curr[-1]['ts'] <= (5.0 if is_same else self.max_gap)): curr.append(p)
                else: seq = self._process_group(curr, dest_root, seq); curr = [p]
                self.progress.emit(int(((idx + 1) / len(photos)) * 100))
            if curr: self._process_group(curr, dest_root, seq)
            self.log.emit("<br>✓ Sorteerproces voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

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
        for f in group:
            try: shutil.move(os.path.join(self.source_dir, f['name']), os.path.join(target, f['name']))
            except: pass
        return seq

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, crop_percent, burst_limit=0, weights=(1.0, 0.2, 0.1)):
        super().__init__(); self.base_dir, self.mode, self.method, self.bit_depth, self.crop_percent, self.burst_limit, self.weights = base_dir, mode, method.lower(), bit_depth, crop_percent, burst_limit, weights
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
            if not subdirs: self.log.emit(f"Geen mappen gevonden voor {prefix}."); self.finished.emit(); return
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            os.makedirs(os.path.join(coll_root, "DNG"), exist_ok=True); os.makedirs(os.path.join(coll_root, "TIFF"), exist_ok=True)
            for i, path in enumerate(subdirs):
                if not self._is_running: break
                name = os.path.basename(path); self.log.emit(f"<b>Verwerken:</b> {name}"); xmp = find_best_xmp(path)
                coll_dng, coll_tif = os.path.join(coll_root, "DNG", f"{name}_HDR.dng"), os.path.join(coll_root, "TIFF", f"{name}_HDR.tif")
                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method) and not os.path.exists(coll_dng):
                    res = self._do_hdrmerge(path, name)
                    if res: smart_copy(res, coll_dng); self.result_path.emit(coll_dng)
                if ((self.mode == "HDR" and ("enfuse" in self.method or "beide" in self.method)) or self.mode == "BURST") and not os.path.exists(coll_tif):
                    res = self._do_enfuse(path, name, xmp)
                    if res: smart_copy(res, coll_tif); self.result_path.emit(coll_tif)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            self.log.emit("<br>✓ Proces voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

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
                if self.safe_run(cmd) == 0: tifs.append(out)
                self.sub_progress.emit(int(((idx + 1) / len(files)) * 80))
            if len(tifs) < 2: return None
            ali = os.path.join(tmp_dir, "ali_"); self.safe_run(['align_image_stack', '-m', '10', '-a', ali, '-c', '20', '-z', '-x', '-y'] + tifs)
            alis = sorted(glob.glob(os.path.join(tmp_dir, "ali_*.tif")))
            for a in alis: self.safe_run(['mogrify', '-alpha', 'off', '-type', 'truecolor', '+matte', a])
            out_h = os.path.join(tmp_dir, "result.tif")
            self.safe_run(['enfuse', f'--depth={self.bit_depth}', f'--exposure-weight={self.weights[0]}', f'--saturation-weight={self.weights[1]}', f'--contrast-weight={self.weights[2]}', '--output', out_h] + alis, env=ENV_STABLE)
            if os.path.exists(out_h):
                final = os.path.join(path, f"{name}_HDR.tif")
                if self.crop_percent > 0: self.safe_run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h])
                shutil.copy2(out_h, final); reset_and_copy_metadata(os.path.join(path, files[0]), final); return final
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(('.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng')) and "_HDR" not in f])
        if len(raws) < 2: return None
        out = os.path.join(path, f"{name}_HDR.dng")
        if self.safe_run(['hdrmerge', '-b', '16', '-o', out] + raws) == 0:
            if os.path.exists(out): copy_metadata_full(raws[0], out); return out
        return None

class PanoWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, custom_xmp=None):
        super().__init__(); self.files, self.custom_xmp = files, custom_xmp
    @Slot()
    def run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            imgs = []
            try:
                for i, f in enumerate(self.files):
                    if not self._is_running: break
                    if f.lower().endswith(('.dng', '.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf')):
                        t = os.path.join(tmp_dir, f"p_{i}.tif"); xmp = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp(os.path.dirname(f))
                        cmd = ['darktable-cli', f, t, '--core', '--library', ':memory:', '--disable-opencl']
                        if xmp: cmd.insert(2, xmp)
                        self.safe_run(cmd); read_f = t
                    else: read_f = f
                    img = cv2.imread(read_f, cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        if img.dtype == np.uint16: img = (img / 256).astype(np.uint8)
                        if img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        imgs.append(img); del img
                    self.sub_progress.emit(int(((i + 1) / len(self.files)) * 80))
                if len(imgs) > 1 and self._is_running:
                    self.log.emit("<b>Samenvoegen...</b>"); stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                    status, res = stitcher.stitch(imgs)
                    if status != cv2.Stitcher_OK: status, res = cv2.Stitcher_create(cv2.Stitcher_SCANS).stitch(imgs)
                    if status == cv2.Stitcher_OK:
                        out = os.path.abspath(os.path.join(os.path.dirname(self.files[0]), f"Pano_{datetime.now().strftime('%H%M%S')}.tif"))
                        cv2.imwrite(out, res); self.log.emit(f"✓ Klaar: {os.path.basename(out)}"); self.result_path.emit(out)
                imgs.clear(); self.progress.emit(100)
            except Exception as e: self.log.emit(f"Fout: {e}")
            finally: self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack v0.1"); self.resize(1300, 900)
        self.worker, self.thread, self.lt, self.last_pano_result = None, None, None, None
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Burst"); self.tabs.addTab(self.t4, "4. Panorama")
        self.setup_t1(); self.setup_t2(); self.setup_t3(); self.setup_t4()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self._sync_paths()

    def on_tab_changed(self, index):
        if index == 3: # Panorama tab
            self.refresh_t4()

    def closeEvent(self, event):
        if self.worker: self.worker.stop()
        CONFIG["LAST_SOURCE_DIR"], CONFIG["MAX_GAP"] = self.s1.text(), self.gv.value(); save_config(CONFIG); event.accept()

    def _sync_paths(self):
        p = self.s1.text().strip()
        if p and os.path.exists(p):
            sorted_p = os.path.join(p, CONFIG["SORTED_DIR_NAME"])
            self.s2.setText(sorted_p); self.s3.setText(sorted_p); self.s4.setText(os.path.join(p, CONFIG["HDR_COLLECT_NAME"]))

    def _make_thin_bar(self):
        pb = QProgressBar(); pb.setFixedHeight(8); pb.setTextVisible(False); pb.setStyleSheet("QProgressBar { border: 1px solid #bbb; background: #eee; } QProgressBar::chunk { background: #05B8CC; }")
        pb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); return pb

    def setup_t1(self):
        l = QVBoxLayout(self.t1); self.s1 = QLineEdit(CONFIG["LAST_SOURCE_DIR"])
        self.s1.textChanged.connect(self._sync_paths)
        h = QHBoxLayout(); h.addWidget(QLabel("Bron:")); h.addWidget(self.s1); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s1)); h.addWidget(b); btn_i = QPushButton("ⓘ"); btn_i.clicked.connect(self.show_info); btn_i.setFixedWidth(40); h.addWidget(btn_i); l.addLayout(h)
        hc = QHBoxLayout(); hc.addWidget(QLabel("Pauze (sec):")); self.gv = QDoubleSpinBox(); self.gv.setValue(CONFIG["MAX_GAP"]); hc.addWidget(self.gv); hc.addStretch(); l.addLayout(hc)
        self.b1 = QPushButton("Start Sorteren", clicked=self.go1); l.addWidget(self.b1); self.p1 = self._make_thin_bar(); l.addWidget(self.p1)
        split = QSplitter(Qt.Horizontal); self.log1 = QTextEdit(); self.log1.setReadOnly(True); self.prev1 = QLabel(); self.prev1.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev1); sc.setWidgetResizable(True); split.addWidget(self.log1); split.addWidget(sc); l.addWidget(split); split.setSizes([300, 900])

    def setup_t2(self):
        l = QVBoxLayout(self.t2); h_p = QHBoxLayout(); h_p.addWidget(QLabel("Map:")); self.s2 = QLineEdit(); h_p.addWidget(self.s2); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s2)); h_p.addWidget(b); l.addLayout(h_p)
        ho = QHBoxLayout(); self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); ho.addWidget(self.m2)
        ho.addWidget(QLabel("Crop:")); self.cp2 = QDoubleSpinBox(); self.cp2.setValue(1.5); ho.addWidget(self.cp2)
        # Herstel Enfuse wegingen
        ho.addWidget(QLabel("Exp:")); self.ew2 = QDoubleSpinBox(); self.ew2.setRange(0,1); self.ew2.setValue(1.0); self.ew2.setSingleStep(0.1); ho.addWidget(self.ew2)
        ho.addWidget(QLabel("Sat:")); self.sw2 = QDoubleSpinBox(); self.sw2.setRange(0,1); self.sw2.setValue(0.2); self.sw2.setSingleStep(0.1); ho.addWidget(self.sw2)
        ho.addWidget(QLabel("Con:")); self.cw2 = QDoubleSpinBox(); self.cw2.setRange(0,1); self.cw2.setValue(0.1); self.cw2.setSingleStep(0.1); ho.addWidget(self.cw2)
        ho.addStretch(); l.addLayout(ho)
        self.b2 = QPushButton("Start HDR", clicked=lambda: self.go_proc("HDR")); l.addWidget(self.b2)
        v_prog = QWidget(); v_prog.setFixedHeight(60); vp_l = QVBoxLayout(v_prog); vp_l.setContentsMargins(0,0,0,0); vp_l.setSpacing(1)
        vp_l.addWidget(QLabel("Totaal:")); self.p2 = self._make_thin_bar(); vp_l.addWidget(self.p2); vp_l.addWidget(QLabel("Huidig:"))
        h_sub = QHBoxLayout(); self.p2_sub = self._make_thin_bar(); h_sub.addWidget(self.p2_sub); self.stop2 = QPushButton("Stop", clicked=self.stop_proc); self.stop2.setFixedWidth(50); self.stop2.setFixedHeight(18); h_sub.addWidget(self.stop2); vp_l.addLayout(h_sub); l.addWidget(v_prog)
        self.h_split2 = QSplitter(Qt.Horizontal); self.log2 = QTextEdit(); self.log2.setReadOnly(True); self.prev2 = QLabel(); self.prev2.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev2); sc.setWidgetResizable(True); self.h_split2.addWidget(self.log2); self.h_split2.addWidget(sc); self.h_split2.setSizes([325, 975]); l.addWidget(self.h_split2)

    def setup_t3(self):
        l = QVBoxLayout(self.t3); h = QHBoxLayout(); h.addWidget(QLabel("Map:")); self.s3 = QLineEdit(); h.addWidget(self.s3); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s3)); h.addWidget(b); l.addLayout(h)
        hb = QHBoxLayout(); self.bl3 = QComboBox(); self.bl3.addItems(["8", "16", "32"]); hb.addWidget(QLabel("Limiet:")); hb.addWidget(self.bl3); hb.addStretch(); l.addLayout(hb)
        self.b3 = QPushButton("Start Burst", clicked=lambda: self.go_proc("BURST")); l.addWidget(self.b3)
        v_prog3 = QWidget(); v_prog3.setFixedHeight(60); vp3_l = QVBoxLayout(v_prog3); vp3_l.setContentsMargins(0,0,0,0); vp3_l.setSpacing(1)
        vp3_l.addWidget(QLabel("Totaal:")); self.p3 = self._make_thin_bar(); vp3_l.addWidget(self.p3); vp3_l.addWidget(QLabel("Huidig:"))
        h_sub3 = QHBoxLayout(); self.p3_sub = self._make_thin_bar(); h_sub3.addWidget(self.p3_sub); self.stop3 = QPushButton("Stop", clicked=self.stop_proc); self.stop3.setFixedWidth(50); self.stop3.setFixedHeight(18); h_sub3.addWidget(self.stop3); vp3_l.addLayout(h_sub3); l.addWidget(v_prog3)
        self.h_split3 = QSplitter(Qt.Horizontal); self.log3 = QTextEdit(); self.log3.setReadOnly(True); self.prev3 = QLabel(); self.prev3.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev3); sc.setWidgetResizable(True); self.h_split3.addWidget(self.log3); self.h_split3.addWidget(sc); self.h_split3.setSizes([325, 975]); l.addWidget(self.h_split3)

    def setup_t4(self):
        main_l = QVBoxLayout(self.t4); h1 = QHBoxLayout(); h1.addWidget(QLabel("Verzamelmap:")); self.s4 = QLineEdit(); h1.addWidget(self.s4); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s4)); h1.addWidget(b); main_l.addLayout(h1)
        h2 = QHBoxLayout(); h2.addWidget(QLabel("Custom XMP:")); self.x4 = QLineEdit(); h2.addWidget(self.x4); b_x = QPushButton("Kies"); b_x.clicked.connect(self.sel_xmp4); h2.addWidget(b_x); main_l.addLayout(h2)
        h3 = QHBoxLayout(); self.f4 = QComboBox(); self.f4.addItems(["TIFF/JPG", "DNG", "RAW (Serie)"]); self.f4.currentIndexChanged.connect(self.refresh_t4); h3.addWidget(self.f4); h3.addWidget(QLabel("Grootte:")); self.ts4 = QComboBox(); self.ts4.addItems(["100", "200", "300"]); self.ts4.setCurrentText("200"); self.ts4.currentIndexChanged.connect(self.refresh_t4); h3.addWidget(self.ts4); self.p4_load = self._make_thin_bar(); h3.addWidget(self.p4_load); main_l.addLayout(h3)
        self.v_split = QSplitter(Qt.Vertical); self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(200, 200)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.v_split.addWidget(self.lw)
        bot_w = QWidget(); bot_l = QVBoxLayout(bot_w); btn_h = QHBoxLayout(); self.b4 = QPushButton("Start Panorama", clicked=self.go4); btn_h.addWidget(self.b4); b_dt = QPushButton("Darktable", clicked=self.open_last_pano_in_dt); btn_h.addWidget(b_dt); bot_l.addLayout(btn_h)
        h_s4 = QHBoxLayout(); self.p4_sub = self._make_thin_bar(); h_s4.addWidget(self.p4_sub); self.stop4 = QPushButton("Stop", clicked=self.stop_proc); self.stop4.setFixedWidth(50); self.stop4.setFixedHeight(18); h_s4.addWidget(self.stop4); bot_l.addLayout(h_s4)
        self.h_split4 = QSplitter(Qt.Horizontal); self.log4 = QTextEdit(); self.log4.setReadOnly(True); self.prev4 = QLabel(); self.prev4.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev4); sc.setWidgetResizable(True); self.h_split4.addWidget(self.log4); self.h_split4.addWidget(sc); self.h_split4.setSizes([325, 975]); bot_l.addWidget(self.h_split4); self.v_split.addWidget(bot_w); main_l.addWidget(self.v_split)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Map", e.text());
        if d:
            p = os.path.abspath(d); e.setText(p)
            self._sync_paths()
            self.refresh_t4()

    def open_last_pano_in_dt(self):
        if self.last_pano_result and os.path.exists(self.last_pano_result): subprocess.Popen(['darktable', '--new-instance', self.last_pano_result])
    def show_info(self): QMessageBox.information(self, "Info", "PanoStack v0.1\nLinux RAW Workflow.")
    def sel_xmp4(self):
        f, _ = QFileDialog.getOpenFileName(self, "XMP", "", "XMP (*.xmp)");
        if f: self.x4.setText(f)
    def refresh_t4(self):
        path = self.s4.text();
        if not os.path.exists(path): return
        self.b4.setEnabled(False) # Blokkeer startknop tijdens inlezen
        mode = self.f4.currentIndex();
        exts = ('.tif', '.tiff', '.jpg', '.jpeg') if mode == 0 else (('.dng',) if mode == 1 else ('.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng'))
        sub, rec = ("TIFF" if mode == 0 else ("DNG" if mode == 1 else "")), mode == 2

        base_sorted = os.path.join(os.path.dirname(path.rstrip(os.sep)), CONFIG["SORTED_DIR_NAME"])
        scan_p = base_sorted if (rec and os.path.exists(base_sorted)) else (os.path.join(path, sub) if (sub and os.path.exists(os.path.join(path, sub))) else path)

        if self.lt and self.lt.isRunning(): self.lt.quit(); self.lt.wait()
        self.lt = QThread(); self.lwk = ThumbnailWorker(scan_p, exts, rec); self.lwk.moveToThread(self.lt); self.lt.started.connect(self.lwk.run); self.lwk.thumb_ready.connect(self.add_thumb); self.lwk.progress.connect(self.p4_load.setValue)
        self.lwk.finished.connect(self.lt.quit); self.lwk.finished.connect(lambda: self.b4.setEnabled(True)) # Deblokkeer na inlezen
        self.lt.start(); self.lw.clear()

    def add_thumb(self, n, p, img):
        it = QListWidgetItem(n); it.setData(Qt.UserRole, p); it.setIcon(QIcon(QPixmap.fromImage(img.scaled(int(self.ts4.currentText()), int(self.ts4.currentText()), Qt.KeepAspectRatio)))); self.lw.addItem(it)
    def stop_proc(self):
        if self.worker: self.worker.stop()
    def go1(self): self.log1.clear(); self._run(SortWorker(self.s1.text(), self.gv.value()), self.p1, self.log1, self.b1)
    def go_proc(self, mode):
        p, log, b, stop = (self.s2.text(), self.log2, self.b2, self.stop2) if mode == "HDR" else (self.s3.text(), self.log3, self.b3, self.stop3); log.clear()
        weights = (self.ew2.value(), self.sw2.value(), self.cw2.value()) if mode == "HDR" else (1.0, 0.2, 0.1)
        w = HdrBurstWorker(p, mode, self.m2.currentText(), "16", self.cp2.value(), int(self.bl3.currentText()) if mode == "BURST" else 0, weights=weights)
        w.sub_progress.connect(self.p2_sub.setValue if mode == "HDR" else self.p3_sub.setValue); self._run(w, self.p2 if mode == "HDR" else self.p3, log, b, stop)
    def go4(self):
        files = [self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]
        if files:
            self.log4.clear(); w = PanoWorker(files, self.x4.text()); w.sub_progress.connect(self.p4_sub.setValue); w.result_path.connect(lambda p: setattr(self, 'last_pano_result', p))
            w.finished.connect(self.lw.clearSelection); self._run(w, self.p4_sub, self.log4, self.b4, self.stop4)
    def _run(self, w, p, log, b, s_btn=None):
        self.worker, self.thread = w, QThread(); b.setEnabled(False);
        if s_btn: s_btn.setEnabled(True)
        w.moveToThread(self.thread); w.log.connect(log.append); w.progress.connect(p.setValue); w.finished.connect(self.thread.quit); w.finished.connect(lambda: (b.setEnabled(True), s_btn.setEnabled(False) if s_btn else None))
        if hasattr(w, 'result_path'): w.result_path.connect(lambda path: self.show_prev(path, w))
        self.thread.started.connect(w.run); self.thread.start()
    def show_prev(self, path, w):
        t = self.prev1 if isinstance(w, SortWorker) else (self.prev2 if (hasattr(w, 'mode') and w.mode == "HDR") else (self.prev3 if (hasattr(w, 'mode') and w.mode == "BURST") else self.prev4))
        img = get_image_robust(path);
        if not img.isNull(): t.setPixmap(QPixmap.fromImage(img).scaled(t.width(), t.height(), Qt.KeepAspectRatio))

class ThumbnailWorker(QObject):
    finished, progress, thumb_ready = Signal(), Signal(int), Signal(str, str, QImage)
    def __init__(self, directory, extensions, recursive=False): super().__init__(); self.directory, self.extensions, self.recursive = directory, extensions, recursive
    def run(self):
        if not os.path.exists(self.directory): self.finished.emit(); return
        fps = []
        if self.recursive:
            for r, _, fs in os.walk(self.directory):
                # Alleen Serie_ mappen tonen in RAW mode
                if "Serie_" in r:
                    for f in sorted(fs):
                        if f.lower().endswith(self.extensions): fps.append(os.path.join(r, f))
        else:
            fps = [os.path.join(self.directory, f) for f in sorted(os.listdir(self.directory)) if f.lower().endswith(self.extensions)]
            for sub in ["DNG", "TIFF"]:
                subp = os.path.join(self.directory, sub)
                if os.path.exists(subp):
                    fps += [os.path.join(subp, f) for f in sorted(os.listdir(subp)) if f.lower().endswith(self.extensions)]
        for i, fp in enumerate(fps):
            img = get_image_robust(fp)
            if not img.isNull(): self.thumb_ready.emit(os.path.basename(fp), fp, img)
            self.progress.emit(int(((i + 1) / (len(fps) or 1)) * 100))
        self.finished.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
