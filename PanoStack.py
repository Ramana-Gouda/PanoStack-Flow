#!/usr/bin/env python3
"""
PanoStack Flow (v1.2)
- VERSION: Updated to v1.2.
- TRANSLATED: Info button content is fully preserved in English.
- FIX: Sorting now strictly respects Camera Model + Timestamp + Filename order.
- FIX: Only the true 1st photo of a sequence remains in the source folder.
- FEATURE: Panorama tab supports TIFF, DNG, and RAW (Source) correctly.
- BEHOUDEN: Alle eerdere functionele verbeteringen (stitching, uitlijning, etc.).
"""

import sys; import os; import shutil; import subprocess; from datetime import datetime; import glob; import time; import tempfile; import re; import gc

# --- CONFIGURATIE ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
}
SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG', '.tif', '.tiff', '.jpg', '.jpeg']
VALID_EXTS = {ext.lower() for ext in SUPPORTED_EXTS}
RAW_EXTS = {'.rw2', '.arw', '.cr2', '.cr3', '.nef', '.orf', '.raf', '.dng'}

cores = os.cpu_count() or 2
ENV_STABLE = os.environ.copy(); ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# --- IMPORTS ---
try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox, QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea, QSplitter)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QImage
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Fout: {e}"); sys.exit(1)

# --- HELPERS ---
def smart_copy(src, dst):
    try:
        if sys.platform == "linux":
            subprocess.run(['cp', '--reflink=auto', src, dst], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        shutil.copy2(src, dst); return True
    except: return False

def reset_and_copy_metadata(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    try: subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', '--Orientation', '-Orientation=1', '-n', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def copy_metadata_full(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    try: subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def get_image_robust(path):
    if not path or not os.path.exists(path): return QImage()
    img = QImage()
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS or ext == ".dng":
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            try:
                res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
                if res.stdout and len(res.stdout) > 5000:
                    img.loadFromData(res.stdout); break
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

# --- WORKERS ---
class BaseWorker(QObject):
    finished, progress, log, result_path = Signal(), Signal(int), Signal(str), Signal(str)
    def __init__(self): super().__init__(); self._is_running = True
    def stop(self): self._is_running = False

class SortWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, source_dir, stack_size, max_gap):
        super().__init__(); self.source_dir = source_dir; self.stack_size, self.max_gap = stack_size, max_gap
    @Slot()
    def run(self):
        try:
            self.log.emit(f"<b>Start scannen:</b> {os.path.basename(self.source_dir)}")
            all_files = [f for f in os.listdir(self.source_dir) if any(f.lower().endswith(ext) for ext in VALID_EXTS) and not f.lower().endswith('.xmp')]
            if not all_files: self.log.emit("Geen bestanden gevonden."); self.finished.emit(); return
            photos = []
            cmd = ['exiftool', '-q', '-f', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO']
            for i in range(0, len(all_files), 40):
                if not self._is_running: break
                batch = all_files[i:i + 40]
                res = subprocess.run(cmd + batch, capture_output=True, text=True, cwd=self.source_dir)
                for line in filter(None, res.stdout.splitlines()):
                    p = line.split('\t')
                    if len(p) < 6: continue
                    try:
                        dt = datetime.strptime(p[1].split('.')[0].split('+')[0].strip(), "%Y:%m:%d %H:%M:%S")
                        photos.append({'name': p[0], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[2]}A{p[3]}", 'model': p[4].strip().replace(' ','_') if p[4] != "-" else "Onbekend", 'iso': int(re.sub(r"\D", "", p[5])) if p[5] != "-" else 0})
                    except: continue
                if batch: self.result_path.emit(os.path.join(self.source_dir, batch[-1]))
                self.sub_progress.emit(int(((i + len(batch)) / len(all_files)) * 100))

            # CRUCIAL: Sort by Model, then Timestamp, then Filename to ensure sequence order
            photos.sort(key=lambda x: (x['model'], x['ts'], x['name']))

            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest_root, exist_ok=True)
            self.log.emit("<b>Bestanden indelen in reeksen...</b>")
            curr, seq, total = [], 0, 0
            for idx, p in enumerate(photos):
                if not self._is_running: break
                # Start new group if gap is too large OR camera model changes
                if not curr or (p['ts'] - curr[-1]['ts'] <= self.max_gap and p['model'] == curr[-1]['model']):
                    curr.append(p)
                else:
                    new_seq = self._process_group(curr, dest_root, seq)
                    if new_seq > seq: total += 1; seq = new_seq
                    curr = [p]
                self.progress.emit(int(((idx + 1) / len(photos)) * 100))
            if curr:
                if self._process_group(curr, dest_root, seq) > seq: total += 1
                self.progress.emit(100)
            self.log.emit(f"<br>✓ Sorteren voltooid: {total} groepen aangemaakt.")
            self.finished.emit()
        except Exception as e: self.log.emit(f"Fout: {e}"); self.finished.emit()

    def _process_group(self, group, dest_root, seq):
        if len(group) < 2: return seq
        is_hdr = len(set([p['exp'] for p in group])) > 1
        type_p = "Reeks" if is_hdr else ("Burst" if group[0]['iso'] > 800 else "Serie")
        seq += 1; target_folder = f"{type_p}_{seq:03d}"
        target_path = os.path.join(dest_root, group[0]['model'], group[0]['date'], target_folder)
        self.log.emit(f"  [Groep] {target_folder}: {len(group)} foto's ({group[0]['model']})")
        os.makedirs(target_path, exist_ok=True)

        # In a sequence, ONLY the first sorted photo remains in source
        for idx, f in enumerate(group):
            src = os.path.join(self.source_dir, f['name'])
            dst = os.path.join(target_path, f['name'])
            if smart_copy(src, dst):
                if idx > 0: # Not the first photo of the sequence
                    try: os.remove(src)
                    except: pass
        self.result_path.emit(os.path.join(target_path, group[0]['name']))
        return seq

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, crop_percent, burst_limit=0):
        super().__init__(); self.base_dir, self.mode, self.method, self.bit_depth, self.crop_percent, self.burst_limit = base_dir, mode, method.lower(), bit_depth, crop_percent, burst_limit
    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = [os.path.join(r, d) for r, ds, _ in os.walk(self.base_dir) for d in ds if d.startswith(prefix) or (self.mode == "BURST" and d.startswith("Serie_"))]
            if not subdirs: self.log.emit("Geen mappen gevonden."); self.finished.emit(); return
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            os.makedirs(os.path.join(coll_root, "DNG"), exist_ok=True); os.makedirs(os.path.join(coll_root, "TIFF"), exist_ok=True)
            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: break
                name = os.path.basename(path); self.log.emit(f"--- <b>Set {i+1}: {name}</b> ---"); xmp = find_best_xmp(path)
                self.sub_progress.emit(0)
                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method):
                    self.log.emit("  [Status] DNG genereren..."); res = self._do_hdrmerge(path, name)
                    if res: shutil.copy2(res, os.path.join(coll_root, "DNG", os.path.basename(res))); self.result_path.emit(res)
                if (self.mode == "HDR" and ("enfuse" in self.method or "beide" in self.method)) or self.mode == "BURST":
                    res = self._do_enfuse(path, name, xmp)
                    if res: shutil.copy2(res, os.path.join(coll_root, "TIFF", os.path.basename(res))); self.result_path.emit(res)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            self.log.emit("✓ Klaar."); self.finished.emit()
        except Exception as e: self.log.emit(f"Fout: {e}"); self.finished.emit()

    def _do_enfuse(self, path, name, xmp):
        all_f = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].lower() in VALID_EXTS and "_HDR" not in f])
        files = all_f[:self.burst_limit] if (self.mode == "BURST" and self.burst_limit > 0) else all_f
        if len(files) < 2: return None
        tmp = os.path.join(path, ".tmp_proc"); os.makedirs(tmp, exist_ok=True); tifs = []
        self.log.emit(f"  [Status] {len(files)} beelden exporteren...");
        for idx, f in enumerate(files):
            if not self._is_running: return None
            self.sub_progress.emit(int((idx / (len(files) + 1)) * 100))
            src, out = os.path.join(path, f), os.path.join(tmp, f"img_{idx:03d}.tif")
            cmd = ['darktable-cli', src, out, '--core', '--library', ':memory:', '--disable-opencl']
            if xmp: cmd.insert(2, xmp)
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(out): tifs.append(out)
        self.sub_progress.emit(90)
        if len(tifs) < 2: return None
        self.log.emit("  [Status] Uitlijnen (Smart Sync voor XMP)..."); ali = os.path.join(tmp, "ali_")
        subprocess.run(['align_image_stack', '-m', '10', '-a', ali, '-c', '20', '-z', '-x', '-y'] + tifs, stdout=subprocess.DEVNULL)
        alis = sorted(glob.glob(os.path.join(tmp, "ali_*.tif"))) or tifs
        out_h = os.path.join(path, f"{name}_HDR.tif")
        subprocess.run(['enfuse', f'--depth={self.bit_depth}', '--output', out_h] + alis, env=ENV_STABLE, stdout=subprocess.DEVNULL)
        if os.path.exists(out_h):
            if self.crop_percent > 0: subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h], stdout=subprocess.DEVNULL)
            reset_and_copy_metadata(os.path.join(path, files[0]), out_h); shutil.rmtree(tmp, ignore_errors=True); self.sub_progress.emit(100); return out_h
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].lower() in VALID_EXTS and not f.lower().endswith(('.tif', '.tiff', '.jpg', '.jpeg')) and "_HDR" not in f])
        if len(raws) < 2: return None
        self.sub_progress.emit(20)
        out = os.path.join(path, f"{name}_HDR.dng"); subprocess.run(['hdrmerge', '-b', '16', '-o', out] + raws, stdout=subprocess.DEVNULL)
        self.sub_progress.emit(80)
        if os.path.exists(out): copy_metadata_full(raws[0], out); self.sub_progress.emit(100); return out
        return None

class PanoWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, custom_xmp=None): super().__init__(); self.files = files; self.custom_xmp = custom_xmp
    @Slot()
    def run(self):
        tmp_dir = tempfile.mkdtemp(); imgs = []
        try:
            for i, f in enumerate(self.files):
                if not self._is_running: break
                self.log.emit(f"Laden {i+1}/{len(self.files)}: {os.path.basename(f)}")
                ext = os.path.splitext(f)[1].lower()
                if ext in RAW_EXTS or ext == ".dng":
                    t = os.path.join(tmp_dir, f"p_{i}.tif")
                    xmp = self.custom_xmp if (self.custom_xmp and os.path.exists(self.custom_xmp)) else find_best_xmp(os.path.dirname(f))
                    cmd = ['darktable-cli', f, t, '--core', '--library', ':memory:', '--disable-opencl']
                    if xmp: cmd.insert(2, xmp)
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    img = cv2.imread(t, cv2.IMREAD_COLOR)
                else:
                    img = cv2.imread(f, cv2.IMREAD_COLOR)
                if img is not None:
                    if img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    imgs.append(img)
                self.sub_progress.emit(int(((i + 1) / len(self.files)) * 100))
            if len(imgs) > 1 and self._is_running:
                self.log.emit("Samenvoegen...")
                stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                stitcher.setPanoConfidenceThresh(0.1)
                status, res = stitcher.stitch(imgs)
                if status != cv2.Stitcher_OK:
                    self.log.emit(f"Panorama mode mislukt (Status {status}), probeer Scan mode...")
                    stitcher = cv2.Stitcher_create(cv2.Stitcher_SCANS)
                    stitcher.setPanoConfidenceThresh(0.1)
                    status, res = stitcher.stitch(imgs)
                if status == cv2.Stitcher_OK:
                    out = os.path.join(os.path.dirname(self.files[0]), f"Pano_{datetime.now().strftime('%H%M%S')}.tif")
                    cv2.imwrite(out, res); self.log.emit(f"✓ Klaar: {os.path.basename(out)}"); self.result_path.emit(out)
                else:
                    self.log.emit(f"Fout: Status {status}. Geen match gevonden.")
            self.progress.emit(100)
        finally: shutil.rmtree(tmp_dir, ignore_errors=True); self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack Flow v1.1"); self.resize(1300, 900)
        self.worker = None; self.thread = None; self.lt = None
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Burst"); self.tabs.addTab(self.t4, "4. Panorama")
        self.setup_t1(); self.setup_t2(); self.setup_t3(); self.setup_t4()
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, idx):
        if idx == 3: self.refresh_t4()

    def _make_thin_bar(self):
        pb = QProgressBar(); pb.setFixedHeight(8); pb.setTextVisible(False); pb.setStyleSheet("QProgressBar { border: 1px solid #bbb; background: #eee; margin: 0; } QProgressBar::chunk { background: #05B8CC; }")
        return pb

    def setup_t1(self):
        l = QVBoxLayout(self.t1); self.s1 = QLineEdit(os.path.expanduser("~"))
        h = QHBoxLayout(); h.addWidget(QLabel("Bron:")); h.addWidget(self.s1); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s1)); h.addWidget(b); btn_i = QPushButton("ⓘ"); btn_i.clicked.connect(self.show_info); btn_i.setFixedWidth(40); h.addWidget(btn_i); l.addLayout(h)
        hc = QHBoxLayout(); hc.setSpacing(5); hc.addWidget(QLabel("Pauze:")); self.gv = QDoubleSpinBox(); self.gv.setValue(1.0); hc.addWidget(self.gv); hc.addSpacing(20); hc.addWidget(QLabel("Bracket:")); self.sc = QComboBox(); self.sc.addItems(["3","5","7"]); self.sc.setCurrentIndex(1); hc.addWidget(self.sc); hc.addStretch(); l.addLayout(hc)
        self.b1 = QPushButton("Start Sorteren", clicked=self.go1); l.addWidget(self.b1)
        v_p1 = QVBoxLayout(); v_p1.setSpacing(0); v_p1.setContentsMargins(0, 0, 0, 0)
        l_tot1 = QLabel("Totaal:"); l_tot1.setFixedHeight(14); v_p1.addWidget(l_tot1)
        h_s1 = QHBoxLayout(); h_s1.setSpacing(5); self.p1 = self._make_thin_bar(); h_s1.addWidget(self.p1)
        self.stop1 = QPushButton("Stop", clicked=self.stop_proc); self.stop1.setFixedWidth(50); self.stop1.setFixedHeight(18); self.stop1.setStyleSheet("font-size: 10px;"); self.stop1.setEnabled(False); h_s1.addWidget(self.stop1); v_p1.addLayout(h_s1); l.addLayout(v_p1)
        split = QSplitter(Qt.Horizontal); self.log1 = QTextEdit(); self.prev1 = QLabel(); self.prev1.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev1); sc.setWidgetResizable(True); split.addWidget(self.log1); split.addWidget(sc); l.addWidget(split); split.setSizes([300, 900])

    def setup_t2(self):
        l = QVBoxLayout(self.t2); h_p = QHBoxLayout(); self.s2 = QLineEdit(); h_p.addWidget(QLabel("Map:")); h_p.addWidget(self.s2); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s2)); h_p.addWidget(b); l.addLayout(h_p)
        ho = QHBoxLayout(); ho.setSpacing(5); self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); ho.addWidget(self.m2); ho.addSpacing(20); ho.addWidget(QLabel("Bit:")); self.bd2 = QComboBox(); self.bd2.addItems(["8","16"]); self.bd2.setCurrentIndex(0); ho.addWidget(self.bd2); ho.addSpacing(20); ho.addWidget(QLabel("Crop:")); self.cp2 = QDoubleSpinBox(); self.cp2.setValue(1.5); ho.addWidget(self.cp2); ho.addStretch(); l.addLayout(ho)
        self.b2 = QPushButton("Start HDR", clicked=lambda: self.go_proc("HDR")); l.addWidget(self.b2)
        v_p = QVBoxLayout(); v_p.setSpacing(0); v_p.setContentsMargins(0, 0, 0, 0)
        l_tot = QLabel("Totaal:"); l_tot.setFixedHeight(14); v_p.addWidget(l_tot); self.p2 = self._make_thin_bar(); v_p.addWidget(self.p2)
        l_sub = QLabel("Huidig:"); l_sub.setFixedHeight(14); v_p.addWidget(l_sub);
        h_s = QHBoxLayout(); h_s.setSpacing(5); self.p2_sub = self._make_thin_bar(); h_s.addWidget(self.p2_sub)
        self.stop2 = QPushButton("Stop", clicked=self.stop_proc); self.stop2.setFixedWidth(50); self.stop2.setFixedHeight(18); self.stop2.setStyleSheet("font-size: 10px;"); self.stop2.setEnabled(False); h_s.addWidget(self.stop2); v_p.addLayout(h_s); l.addLayout(v_p)
        split = QSplitter(Qt.Horizontal); self.log2 = QTextEdit(); self.prev2 = QLabel(); self.prev2.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev2); sc.setWidgetResizable(True); split.addWidget(self.log2); split.addWidget(sc); l.addWidget(split); split.setSizes([300, 900])

    def setup_t3(self):
        l = QVBoxLayout(self.t3); h = QHBoxLayout(); self.s3 = QLineEdit(); h.addWidget(QLabel("Map:")); h.addWidget(self.s3); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s3)); h.addWidget(b); l.addLayout(h)
        hb = QHBoxLayout(); hb.setSpacing(5); hb.addWidget(QLabel("Limiet:")); self.bl3 = QComboBox(); self.bl3.addItems(["8", "16"]); hb.addWidget(self.bl3); hb.addStretch(); l.addLayout(hb)
        self.b3 = QPushButton("Start Burst", clicked=lambda: self.go_proc("BURST")); l.addWidget(self.b3)
        v_p3 = QVBoxLayout(); v_p3.setSpacing(0); v_p3.setContentsMargins(0, 0, 0, 0)
        l_tot3 = QLabel("Totaal:"); l_tot3.setFixedHeight(14); v_p3.addWidget(l_tot3); self.p3 = self._make_thin_bar(); v_p3.addWidget(self.p3)
        l_sub3 = QLabel("Huidig:"); l_sub3.setFixedHeight(14); v_p3.addWidget(l_sub3);
        h_s3 = QHBoxLayout(); h_s3.setSpacing(5); self.p3_sub = self._make_thin_bar(); h_s3.addWidget(self.p3_sub)
        self.stop3 = QPushButton("Stop", clicked=self.stop_proc); self.stop3.setFixedWidth(50); self.stop3.setFixedHeight(18); self.stop3.setStyleSheet("font-size: 10px;"); self.stop3.setEnabled(False); h_s3.addWidget(self.stop3); v_p3.addLayout(h_s3); l.addLayout(v_p3)
        split = QSplitter(Qt.Horizontal); self.log3 = QTextEdit(); self.prev3 = QLabel(); self.prev3.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev3); sc.setWidgetResizable(True); split.addWidget(self.log3); split.addWidget(sc); l.addWidget(split); split.setSizes([300, 900])

    def setup_t4(self):
        main_l = QVBoxLayout(self.t4)
        top_w = QWidget(); top_l = QVBoxLayout(top_w); top_l.setContentsMargins(0,0,0,0)
        h1 = QHBoxLayout(); self.s4 = QLineEdit(); h1.addWidget(QLabel("Map:")); h1.addWidget(self.s4); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s4)); h1.addWidget(b); top_l.addLayout(h1)
        h2 = QHBoxLayout(); h2.addWidget(QLabel("Custom XMP:")); self.x4 = QLineEdit(); h2.addWidget(self.x4); self.bx4 = QPushButton("Kies"); self.bx4.clicked.connect(self.sel_xmp4); h2.addWidget(self.bx4); self.bc4 = QPushButton("Wis"); self.bc4.clicked.connect(lambda: self.x4.clear()); h2.addWidget(self.bc4); top_l.addLayout(h2)
        h3 = QHBoxLayout(); h3.setSpacing(10); self.f4 = QComboBox(); self.f4.addItems(["TIFF/JPG", "DNG", "RAW (Bronmap)"]); self.f4.currentIndexChanged.connect(self.refresh_t4); h3.addWidget(self.f4)
        h3.addWidget(QLabel("Grootte:")); self.ts4 = QComboBox(); self.ts4.addItems(["100", "150", "200", "250", "300"]); self.ts4.setCurrentText("200"); self.ts4.currentIndexChanged.connect(self.refresh_t4); h3.addWidget(self.ts4)
        self.p4_load = self._make_thin_bar(); h3.addWidget(self.p4_load); top_l.addLayout(h3)
        main_l.addWidget(top_w)
        self.v_split = QSplitter(Qt.Vertical)
        self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(200, 200)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.v_split.addWidget(self.lw)
        bot_w = QWidget(); bot_l = QVBoxLayout(bot_w); bot_l.setContentsMargins(0,0,0,0)
        self.b4 = QPushButton("Start Panorama", clicked=self.go4); bot_l.addWidget(self.b4)
        v_p4 = QVBoxLayout(); v_p4.setSpacing(0); v_p4.setContentsMargins(0, 0, 0, 0)
        l_sub4 = QLabel("Huidig:"); l_sub4.setFixedHeight(14); v_p4.addWidget(l_sub4)
        h_s4 = QHBoxLayout(); h_s4.setSpacing(5); self.p4_sub = self._make_thin_bar(); h_s4.addWidget(self.p4_sub)
        self.stop4 = QPushButton("Stop", clicked=self.stop_proc); self.stop4.setFixedWidth(50); self.stop4.setFixedHeight(18); self.stop4.setStyleSheet("font-size: 10px;"); self.stop4.setEnabled(False); h_s4.addWidget(self.stop4); v_p4.addLayout(h_s4); bot_l.addLayout(v_p4)
        h_split = QSplitter(Qt.Horizontal); self.log4 = QTextEdit(); h_split.addWidget(self.log4); self.prev4 = QLabel(); self.prev4.setAlignment(Qt.AlignCenter); sc = QScrollArea(); sc.setWidget(self.prev4); sc.setWidgetResizable(True); h_split.addWidget(sc); bot_l.addWidget(h_split); h_split.setSizes([300, 900]); self.v_split.addWidget(bot_w); main_l.addWidget(self.v_split)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Map", e.text())
        if d:
            p = os.path.abspath(d); e.setText(p)
            if e == self.s1: p_sort = os.path.join(p, CONFIG["SORTED_DIR_NAME"]); self.s2.setText(p_sort); self.s3.setText(p_sort); self.s4.setText(os.path.join(p, CONFIG["HDR_COLLECT_NAME"]))
            self.refresh_t4()

    def sel_xmp4(self):
        f, _ = QFileDialog.getOpenFileName(self, "Kies XMP bestand", "", "XMP Bestanden (*.xmp)")
        if f: self.x4.setText(f)

    def show_info(self):
        text = """
        <h2 style='color: #05B8CC;'>PanoStack Flow v1.0</h2>
        <p>This script provides a complete workflow for sorting and processing RAW photos into HDR, Bursts, and Panoramas.</p>

        <h3 style='color: #05B8CC;'>1. Sorting</h3>
        <ul>
            <li><b>Pause:</b> The maximum time (in sec) between photos to group them into the same sequence.</li>
            <li><b>Bracket:</b> The number of shots per HDR set (e.g., 3, 5, or 7).</li>
        </ul>

        <h3 style='color: #05B8CC;'>2. HDR & Burst</h3>
        <ul>
            <li><b>Alignment:</b> Uses refined control points to perfectly stack photos with active XMP corrections (such as AgX, Lens Correction, and Noise Reduction).</li>
            <li><b>Enfuse:</b> Blends exposures into a natural 8-bit or 16-bit TIFF.</li>
        </ul>

        <h3 style='color: #05B8CC;'>3. Panorama</h3>
        <ul>
            <li><b>Sensitivity (0.1):</b> Highly sensitive setting to allow stitching even with low-detail areas (like clear skies).</li>
            <li><b>Deselection:</b> Images are automatically deselected from the list after a successful stitch.</li>
        </ul>

        <p><i>Requirements: ExifTool, Darktable-cli, Enfuse, Align_image_stack, HDRmerge.</i></p>
        """
        QMessageBox.information(self, "System Information", text)

    def refresh_t4(self):
        path_collect = self.s4.text()
        path_source = self.s1.text()
        idx = self.f4.currentIndex()
        is_tif, is_dng, is_raw = (idx == 0), (idx == 1), (idx == 2)
        self.x4.setEnabled(not is_tif); self.bx4.setEnabled(not is_tif); self.bc4.setEnabled(not is_tif)

        if is_raw:
            scan_p = path_source; exts = tuple(RAW_EXTS)
        elif is_tif:
            exts = ('.tif', '.tiff', '.jpg', '.jpeg'); sub = os.path.join(path_collect, "TIFF"); scan_p = sub if os.path.exists(sub) else path_collect
        else: # DNG mode
            exts = ('.dng',); sub = os.path.join(path_collect, "DNG"); scan_p = sub if os.path.exists(sub) else path_collect

        if not scan_p or not os.path.exists(scan_p): self.lw.clear(); return
        self.lw.clear(); size = int(self.ts4.currentText()); self.lw.setIconSize(QSize(size, size))
        if self.lt and self.lt.isRunning(): self.lt.quit(); self.lt.wait()
        self.lt = QThread(); self.lwk = ThumbnailWorker(scan_p, exts); self.lwk.moveToThread(self.lt); self.lt.started.connect(self.lwk.run); self.lwk.thumb_ready.connect(self.add_thumb); self.lwk.progress.connect(self.p4_load.setValue); self.lwk.finished.connect(self.lt.quit); self.lt.start()

    def add_thumb(self, n, p, img):
        size = int(self.ts4.currentText())
        it = QListWidgetItem(n); it.setData(Qt.UserRole, p); it.setIcon(QIcon(QPixmap.fromImage(img.scaled(size, size, Qt.KeepAspectRatio)))); self.lw.addItem(it)

    def stop_proc(self):
        if self.worker: self.worker.stop(); self.log1.append("<b>Stop...</b>"); self.log2.append("<b>Stop...</b>"); self.log3.append("<b>Stop...</b>"); self.log4.append("<b>Stop...</b>")

    def go1(self):
        self.p1.setValue(0)
        w = SortWorker(self.s1.text(), int(self.sc.currentText()), self.gv.value())
        self._run(w, self.p1, self.log1, self.b1, self.stop1)

    def go_proc(self, mode):
        p = self.s2.text() if mode == "HDR" else self.s3.text()
        w = HdrBurstWorker(p, mode, self.m2.currentText(), self.bd2.currentText(), self.cp2.value(), int(self.bl3.currentText()) if mode == "BURST" else 0)
        if mode == "HDR": w.sub_progress.connect(self.p2_sub.setValue)
        else: w.sub_progress.connect(self.p3_sub.setValue)
        self._run(w, self.p2 if mode == "HDR" else self.p3, self.log2 if mode == "HDR" else self.log3, self.b2 if mode == "HDR" else self.b3, (self.stop2 if mode == "HDR" else self.stop3))

    def go4(self):
        files = [self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]
        if files:
            self.p4_sub.setValue(0)
            is_raw_handling = self.f4.currentIndex() in [1, 2]
            w = PanoWorker(files, self.x4.text() if (is_raw_handling and self.x4.text()) else None)
            w.sub_progress.connect(self.p4_sub.setValue)
            w.finished.connect(self.lw.clearSelection)
            self._run(w, self.p4_sub, self.log4, self.b4, self.stop4)

    def _run(self, w, p, log, b, s_btn=None):
        self.worker = w; self.thread = QThread(); b.setEnabled(False); (s_btn.setEnabled(True) if s_btn else None)
        w.moveToThread(self.thread); w.log.connect(log.append); w.progress.connect(p.setValue); w.finished.connect(self.thread.quit); w.finished.connect(lambda: (b.setEnabled(True), (s_btn.setEnabled(False) if s_btn else None)))
        if hasattr(w, 'result_path'): w.result_path.connect(lambda path: self.show_prev(path, w))
        self.thread.started.connect(w.run); self.thread.start()

    def show_prev(self, path, w):
        target = self.prev1 if isinstance(w, SortWorker) else (self.prev2 if (hasattr(w, 'mode') and w.mode == "HDR") else (self.prev3 if (hasattr(w, 'mode') and w.mode == "BURST") else self.prev4))
        img = get_image_robust(path)
        if not img.isNull(): target.setPixmap(QPixmap.fromImage(img).scaled(target.width(), target.height(), Qt.KeepAspectRatio))

class ThumbnailWorker(QObject):
    finished, progress, thumb_ready = Signal(), Signal(int), Signal(str, str, QImage)
    def __init__(self, directory, extensions): super().__init__(); self.directory, self.extensions = directory, extensions
    def run(self):
        if not os.path.exists(self.directory): self.finished.emit(); return
        ext_tuple = tuple(e.lower() for e in self.extensions)
        files = [os.path.join(self.directory, f) for f in sorted(os.listdir(self.directory)) if f.lower().endswith(ext_tuple)]
        for i, fp in enumerate(files):
            img = get_image_robust(fp);
            if not img.isNull(): self.thumb_ready.emit(os.path.basename(fp), fp, img)
            self.progress.emit(int(((i + 1) / (len(files) or 1)) * 100))
        self.finished.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
