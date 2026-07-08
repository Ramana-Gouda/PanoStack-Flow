#!/usr/bin/env python3
"""
PanoStack Flow (v8.9.1)
-----------------------
BASIS: Volledig behoud van v6.1.4 logica voor Tab 1 en 2.
FIX: "Beide" verwerking in Tab 2 hersteld (koppeling worker-logic).
FIX: Preview-rotatie in de GUI hersteld (bestanden op schijf blijven ongewijzigd).
-----------------------
"""

import sys; import os; import shutil; import subprocess; from datetime import datetime; import glob; import tempfile

# --- CONFIGURATIE (v6.1.4) ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
    "SAFE_MARKER": ".safe_to_delete"
}
REQUIRED_TOOLS = ['exiftool', 'darktable-cli', 'align_image_stack', 'enfuse', 'hdrmerge', 'mogrify']
SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG']
cores = os.cpu_count() or 2; ENV_STABLE = os.environ.copy(); ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))

# --- HELPERS (v6.1.4) ---
def smart_copy(src, dst):
    if sys.platform == "linux":
        try: subprocess.run(['cp', '--reflink=auto', src, dst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return
        except: pass
    shutil.copy2(src, dst)

def reset_and_copy_metadata(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    try: subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', '--Orientation', '-Orientation=1', '-n', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def copy_metadata_full(src_raw, dst_hdr):
    if not os.path.exists(dst_hdr): return
    try: subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

# --- IMPORTS ---
try:
    import cv2
    import numpy as np
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QCheckBox, QMessageBox, QDoubleSpinBox, QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform
except ImportError as e:
    print(f"Fout bij laden bibliotheken: {e}")
    sys.exit(1)

# --- EXTRA HELPER VOOR GUI PREVIEW ROTATIE ---
def get_pixmap_robust(path):
    """Laadt een Pixmap en draait deze rechtop in het geheugen voor de preview."""
    if not path or not os.path.exists(path): return QPixmap()
    try:
        out = subprocess.run(['exiftool', '-S3', '-Orientation', '-n', path], capture_output=True, text=True)
        orient = int(out.stdout.strip()) if out.stdout.strip() else 1
    except: orient = 1
    pix = QPixmap()
    ext = os.path.splitext(path)[1].upper()
    if ext == ".DNG":
        try:
            res = subprocess.run(['exiftool', '-b', '-PreviewImage', path], capture_output=True)
            if res.stdout: pix.loadFromData(res.stdout)
        except: pass
    else: pix.load(path)
    if pix.isNull(): return QPixmap()
    transform = QTransform()
    if orient == 6: transform.rotate(90)
    elif orient == 8: transform.rotate(270)
    elif orient == 3: transform.rotate(180)
    if not transform.isIdentity(): pix = pix.transformed(transform, Qt.SmoothTransformation)
    return pix

# --- BASE WORKER ---
class BaseWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    result_path = Signal(str)
    def __init__(self): super().__init__(); self._is_running = True
    def stop(self): self._is_running = False

# --- WORKER 1: SORTEREN (v6.1.4) ---
class SortWorker(BaseWorker):
    def __init__(self, source_dir, stack_size, keep_first, max_gap):
        super().__init__(); self.source_dir, self.stack_size, self.keep_first, self.max_gap = source_dir, stack_size, keep_first, max_gap
        self.sequence_count = 0
    @Slot()
    def run(self):
        try:
            self.log.emit("PanoStack Flow: Metadata analyseren...")
            cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True); photo_list = []
            for line in filter(None, result.stdout.splitlines()):
                p = line.split('\t')
                if len(p) < 6 or os.path.splitext(p[0])[1].upper() not in SUPPORTED_EXTS: continue
                dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S")
                model = p[4].strip().replace(' ', '_').replace('/', '-') if p[4] else "Onbekende_Camera"
                iso = int(float(p[5])) if p[5] else 0
                photo_list.append({'name': p[0], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[2]}A{p[3]}", 'model': model, 'iso': iso})
            if not photo_list: self.log.emit("Geen RAW bestanden gevonden."); self.finished.emit(); return
            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest_root, exist_ok=True)
            with open(os.path.join(dest_root, CONFIG["SAFE_MARKER"]), 'w') as f: f.write("OK")
            curr = []
            for i, photo in enumerate(photo_list):
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap): curr.append(photo)
                else: self._process_group(curr, dest_root); curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr: self._process_group(curr, dest_root)
            self.progress.emit(100); self.log.emit(f"✓ Klaar! {self.sequence_count} items gesorteerd.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()
    def _process_group(self, group, dest_root):
        if len(group) < 2: return
        if len(set([p['exp'] for p in group])) > 1:
            s = self.stack_size
            if len(group) >= s:
                for i in range(len(group) // s): self._create_target_folder(group[i*s:(i+1)*s], dest_root, "Reeks")
        else: self._create_target_folder(group, dest_root, "Burst")
    def _create_target_folder(self, photo_subset, dest_root, type_prefix):
        self.sequence_count += 1; meta = photo_subset[0]
        iso_label = f"_ISO{meta['iso']}" if meta['iso'] >= 1600 else ""
        target = os.path.join(dest_root, meta['model'], meta['date'], f"{type_prefix}_{self.sequence_count:03d}{iso_label}")
        os.makedirs(target, exist_ok=True)
        for idx, f in enumerate(photo_subset):
            src = os.path.join(self.source_dir, f['name'])
            if os.path.exists(src):
                smart_copy(src, os.path.join(target, f['name']))
                if not (self.keep_first and idx == 0):
                    try: os.remove(src)
                    except: pass

# --- WORKER 2: HDR & BURST (v6.1.4) ---
class HdrWorker(BaseWorker):
    def __init__(self, base_dir, method, bit_depth, collect, cleanup, crop_percent):
        super().__init__(); self.base_dir, self.method, self.bit_depth, self.collect, self.cleanup, self.crop_percent = os.path.abspath(base_dir), method, bit_depth, collect, cleanup, crop_percent
    @Slot()
    def run(self):
        try:
            subdirs = [os.path.join(r, d) for r, ds, fs in os.walk(self.base_dir) for d in ds if d.startswith(("Reeks_", "Burst_"))]
            if not subdirs: self.finished.emit(); return
            xmp = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG["DT_XMP_FILE"])
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: break
                name = os.path.basename(path); is_burst = name.startswith("Burst_")
                self.log.emit(f"<br><b>--- Verwerken: {name} ---</b>")
                cfg = os.path.expanduser("~/.cache/panostack_temp"); (shutil.rmtree(cfg) if os.path.exists(cfg) else None); os.makedirs(cfg)

                # De logica accepteert nu "both" (Engels) of "beide" (Nederlands)
                if self.method in ["hdrmerge", "both", "beide"] and not is_burst:
                    self.log.emit("<i>-> Start HDRmerge (DNG)...</i>")
                    res_dng = self._do_hdrmerge(path, name)
                    if res_dng and os.path.exists(res_dng) and self.collect:
                        d_dest = os.path.join(coll_root, "DNG"); os.makedirs(d_dest, exist_ok=True)
                        final_dng = os.path.join(d_dest, os.path.basename(res_dng))
                        shutil.move(res_dng, final_dng); self.result_path.emit(final_dng)

                if self.method in ["enfuse", "both", "beide"]:
                    self.log.emit(f"<i>-> Start Enfuse ({self.bit_depth} bit TIFF)...</i>")
                    res_tif = self._do_enfuse(path, name, cfg, xmp, is_burst)
                    if res_tif and os.path.exists(res_tif) and self.collect:
                        t_dest = os.path.join(coll_root, "TIFF"); os.makedirs(t_dest, exist_ok=True)
                        final_tif = os.path.join(t_dest, os.path.basename(res_tif))
                        shutil.move(res_tif, final_tif); self.result_path.emit(final_tif)

                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            if self.cleanup and self._is_running:
                for p in subdirs: shutil.rmtree(p, ignore_errors=True)
            self.log.emit("<br><b>✓ Verwerking voltooid.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()
    def _do_enfuse(self, path, name, cfg, xmp, is_burst):
        raws = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]); tmp = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp, exist_ok=True); tifs = []; out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
        try:
            for idx, r in enumerate(raws):
                if not self._is_running: return None
                self.log.emit(f"   - RAW {idx+1}/{len(raws)}: {r}")
                out = os.path.join(tmp, f"{os.path.splitext(r)[0]}.tif"); raw_p = os.path.join(path, r); cmd = ['darktable-cli', raw_p]
                if xmp and os.path.exists(xmp): cmd.append(xmp)
                cmd.extend([out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl']); subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(out): reset_and_copy_metadata(raw_p, out); tifs.append(out)
            if len(tifs) >= 2 and self._is_running:
                ali = os.path.join(tmp, "ali_"); subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                alis = sorted(glob.glob(os.path.join(tmp, "ali_*.tif")))
                if alis and self._is_running:
                    if is_burst: enf_cmd = ['enfuse', '--exposure-weight=1.0', '--saturation-weight=0', '--contrast-weight=0', '--output', out_h] + alis
                    else: enf_cmd = ['enfuse', '--exposure-weight=1.0', '--saturation-weight=0.5', '--contrast-weight=0.5', '--output', out_h] + alis
                    subprocess.run(enf_cmd, env=ENV_STABLE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(out_h):
                        if self.crop_percent > 0: subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        reset_and_copy_metadata(os.path.join(path, raws[0]), out_h); return out_h
        finally: (shutil.rmtree(tmp) if os.path.exists(tmp) else None)
        return None
    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]); out_f = os.path.join(path, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-o', out_f] + raws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_f): copy_metadata_full(raws[0], out_f); return out_f
        return None

# --- WORKER 3: PANORAMA ---
class PanoWorker(BaseWorker):
    def __init__(self, files):
        super().__init__(); self.files = files
    @Slot()
    def run(self):
        if len(self.files) < 2: self.log.emit("Fout: Selecteer minimaal 2 foto's."); self.finished.emit(); return
        try:
            self.log.emit(f"Stitchen van {len(self.files)} beelden...")
            imgs = [cv2.imread(f) for f in self.files]
            imgs = [i for i in imgs if i is not None]
            stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
            status, res = stitcher.stitch(imgs)
            if status == cv2.Stitcher_OK:
                out_dir = os.path.join(os.path.dirname(self.files[0]), "Panorama_Resultaten"); os.makedirs(out_dir, exist_ok=True)
                out_p = os.path.join(out_dir, f"Pano_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif")
                cv2.imwrite(out_p, res); reset_and_copy_metadata(self.files[0], out_p)
                self.log.emit(f"✓ <b>Panorama voltooid!</b>"); self.result_path.emit(out_p)
            else: self.log.emit(f"Fout {status}: Stitching mislukt.")
        finally: self.finished.emit()

# --- GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack Flow v8.9.1"); self.setGeometry(100, 100, 1250, 950); self.worker = None; self.thread = None; self.s2_manually_set = False; self.current_res = ""
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs); self.t1, self.t2, self.t3 = QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR verwerking"); self.tabs.addTab(self.t3, "3. Panorama (TIFF)")
        self.setup_t1(); self.setup_t2(); self.setup_t3()
    def setup_t1(self):
        l = QVBoxLayout(self.t1); h1 = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); b1 = QPushButton("..."); b1.clicked.connect(lambda: self.sel(self.s1)); h1.addWidget(QLabel("Bronmap:")); h1.addWidget(self.s1); h1.addWidget(b1); l.addLayout(h1)
        h_gap = QHBoxLayout(); h_gap.addWidget(QLabel("Maximale pauze tussen foto's in een reeks:")); self.gv = QDoubleSpinBox(); self.gv.setRange(0.1, 10.0); self.gv.setValue(1.0); h_gap.addWidget(self.gv); h_gap.addWidget(QLabel("sec")); l.addLayout(h_gap)
        h2 = QHBoxLayout(); self.sc = QComboBox(); self.sc.addItems(["3", "5", "7"]); self.sc.setCurrentIndex(1); h2.addWidget(QLabel("Aantal foto's per HDR-bracket:")); h2.addWidget(self.sc); l.addLayout(h2)
        self.k = QCheckBox("Behoud eerste foto in bronmap", checked=True); l.addWidget(self.k)
        self.b1 = QPushButton("Start Sorteer", clicked=self.go1); l.addWidget(self.b1); self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); l.addWidget(self.log1)
    def setup_t2(self):
        l = QVBoxLayout(self.t2); h = QHBoxLayout(); self.s2 = QLineEdit(); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s2)); h.addWidget(QLabel("Map:")); h.addWidget(self.s2); h.addWidget(b); l.addLayout(h)
        self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); self.m2.setCurrentIndex(2); l.addWidget(self.m2)
        hb = QHBoxLayout(); self.bd = QComboBox(); self.bd.addItems(["8", "16"]); self.cp = QDoubleSpinBox(); self.cp.setValue(1.5); hb.addWidget(QLabel("Bit:")); hb.addWidget(self.bd); hb.addWidget(QLabel("Shave %:")); hb.addWidget(self.cp); l.addLayout(hb)
        self.c1 = QCheckBox("Verzamel resultaten", checked=True); self.c2 = QCheckBox("Verwijder reeks-mappen"); l.addWidget(self.c1); l.addWidget(self.c2)
        h_btns = QHBoxLayout(); self.b2_start = QPushButton("Start HDR", clicked=self.go2); self.b2_stop = QPushButton("Stop HDR", clicked=self.stop_w); self.b2_stop.setEnabled(False); h_btns.addWidget(self.b2_start); h_btns.addWidget(self.b2_stop); l.addLayout(h_btns)
        self.p2 = QProgressBar(); l.addWidget(self.p2)
        h_split = QHBoxLayout(); self.log2 = QTextEdit(); self.log2.setReadOnly(True); h_split.addWidget(self.log2, 1)
        self.scroll2 = QScrollArea(); self.scroll2.setWidgetResizable(True); self.scroll2.setStyleSheet("background-color: #1a1a1a;"); self.prev2 = QLabel("Preview"); self.prev2.setAlignment(Qt.AlignCenter); self.scroll2.setWidget(self.prev2); h_split.addWidget(self.scroll2, 1); l.addLayout(h_split)
    def setup_t3(self):
        l = QVBoxLayout(self.t3); h_top = QHBoxLayout(); self.s3 = QLineEdit(); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s3)); h_top.addWidget(QLabel("TIFF Map:")); h_top.addWidget(self.s3); h_top.addWidget(b); l.addLayout(h_top)
        self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(120, 120)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.lw.setFixedHeight(350); l.addWidget(self.lw)
        h2 = QHBoxLayout(); v_left = QVBoxLayout(); v_left.addWidget(QPushButton("Laden", clicked=self.refresh_t3))
        self.b3 = QPushButton("Panorama", clicked=self.go3); v_left.addWidget(self.b3); self.p3 = QProgressBar(); v_left.addWidget(self.p3); self.log3 = QTextEdit(); v_left.addWidget(self.log3)
        self.b_map = QPushButton("Open Map", clicked=self.open_folder); self.b_dt = QPushButton("Open in Darktable", clicked=self.open_dt); v_left.addWidget(self.b_map); v_left.addWidget(self.b_dt); h2.addLayout(v_left, 1)
        self.scroll3 = QScrollArea(); self.prev3 = QLabel("Preview"); self.prev3.setAlignment(Qt.AlignCenter); self.scroll3.setWidget(self.prev3); self.scroll3.setWidgetResizable(True); h2.addWidget(self.scroll3, 1); l.addLayout(h2)
    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Map", e.text()); (e.setText(d) if d else None)
        if d and e == self.s1:
            self.s2.setText(os.path.join(d, CONFIG["SORTED_DIR_NAME"]))
            self.s3.setText(os.path.join(d, CONFIG["HDR_COLLECT_NAME"], "TIFF"))
        if d and e == self.s3: self.refresh_t3()
    def refresh_t3(self):
        self.lw.clear()
        if not os.path.exists(self.s3.text()): return
        for f in sorted([f for f in os.listdir(self.s3.text()) if f.upper().endswith(('.TIF', '.TIFF', '.JPG'))]):
            fp = os.path.join(self.s3.text(), f); it = QListWidgetItem(f); it.setData(Qt.UserRole, fp); it.setIcon(QIcon(get_pixmap_robust(fp).scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))); self.lw.addItem(it)
    @Slot(str)
    def show_hdr_preview(self, p):
        pix = get_pixmap_robust(p); self.prev2.setPixmap(pix.scaled(self.scroll2.width()-20, 2000, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not pix.isNull() else None
    @Slot(str)
    def show_res(self, p):
        self.current_res = p; pix = get_pixmap_robust(p); self.prev3.setPixmap(pix.scaled(self.scroll3.width()-20, 2000, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not pix.isNull() else None
    def open_folder(self): (subprocess.run(['xdg-open', os.path.dirname(self.current_res)]) if self.current_res else None)
    def open_dt(self): (subprocess.run(['darktable', '--library', ':memory:', self.current_res]) if self.current_res else None)
    def stop_w(self): (self.worker.stop() if self.worker else None)
    def go1(self): self._run(SortWorker(self.s1.text(), int(self.sc.currentText()), self.k.isChecked(), self.gv.value()), self.p1, self.log1, self.b1)
    def go2(self):
        self.b2_start.setEnabled(False); self.b2_stop.setEnabled(True); self.log2.clear()
        meth_text = self.m2.currentText().lower()
        if "beide" in meth_text: meth = "beide"
        elif "enfuse" in meth_text: meth = "enfuse"
        else: meth = "hdrmerge"
        self._run(HdrWorker(self.s2.text(), meth, self.bd.currentText(), self.c1.isChecked(), self.c2.isChecked(), self.cp.value()), self.p2, self.log2, self.b2_start)
    def go3(self): self._run(PanoWorker([self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]), self.p3, self.log3, self.b3)
    def _run(self, w, p, log, b):
        self.worker = w; self.thread = QThread(); b.setEnabled(False); w.moveToThread(self.thread)
        w.finished.connect(lambda: self._end(b)); w.log.connect(log.append); w.progress.connect(p.setValue)
        if hasattr(w, 'result_path'):
            if isinstance(w, HdrWorker): w.result_path.connect(self.show_hdr_preview)
            else: w.result_path.connect(self.show_res)
        self.thread.started.connect(w.run); self.thread.start()
    def _end(self, b):
        self.thread.quit(); self.thread.wait(); self.worker = None; b.setEnabled(True); self.b2_stop.setEnabled(False)

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
