#!/usr/bin/env python3
"""
PanoFlow (v5.8)
- FINAL CHECK: Volledig geoptimaliseerd en stabiel bevonden.
- INFO: Complete uitleg en werkwijze in de GUI.
- FIX: Tab 2 resume-functie (herkent direct RAWs en submappen).
- FEATURE: Sorteer-interval instelbaar (1.0s standaard).
- METADATA: Intelligente oriëntatie-fix voor TIFF en DNG.
"""

import sys; import os; import shutil; import subprocess; from datetime import datetime; import glob

# --- CONFIGURATIE ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
    "SAFE_MARKER": ".safe_to_delete"
}

REQUIRED_TOOLS = ['exiftool', 'darktable-cli', 'align_image_stack', 'enfuse', 'hdrmerge', 'mogrify']
SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG']

# CPU Threads management (laat 1 core vrij voor GUI-responsiviteit)
cores = os.cpu_count() or 2; ENV_STABLE = os.environ.copy(); ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))

# --- HELPER FUNCTIES ---

def smart_copy(src, dst):
    """Btrfs Reflink ondersteuning voor Linux, anders normale kopie."""
    if sys.platform == "linux":
        try: subprocess.run(['cp', '--reflink=auto', src, dst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return
        except: pass
    shutil.copy2(src, dst)

def reset_and_copy_metadata(src_raw, dst_hdr):
    """Voor TIFF: forceert Orientation 1 (Normal) omdat pixels al gedraaid zijn door Darktable."""
    try: subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', '--Orientation', '-Orientation=1', '-n', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def copy_metadata_full(src_raw, dst_hdr):
    """Voor DNG: behoudt alle originele metadata inclusief de sensor-oriëntatie."""
    try: subprocess.run(['exiftool', '-overwrite_original', '-tagsFromFile', src_raw, '-all:all', dst_hdr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QCheckBox, QMessageBox, QDoubleSpinBox)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt
except ImportError:
    print("Fout: PySide6 niet gevonden. Installeer met: pip install PySide6"); sys.exit(1)

# --- WORKER 1: SORTEREN ---
class SortWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self, source_dir, stack_size, keep_first, max_gap):
        super().__init__(); self.source_dir, self.stack_size, self.keep_first, self.max_gap = source_dir, stack_size, keep_first, max_gap
        self._is_running = True
    def stop(self): self._is_running = False

    @Slot()
    def run(self):
        try:
            self.log.emit("PanoFlow: Analysing RAW files..."); cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True); photo_list = []
            for line in filter(None, result.stdout.splitlines()):
                if not self._is_running: break
                p = line.split('\t')
                if len(p) < 4 or os.path.splitext(p[0])[1].upper() not in SUPPORTED_EXTS: continue
                try: dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S"); photo_list.append({'name': p[0], 'ts': dt.timestamp(), 'exp': f"S{p[2]}A{p[3]}"})
                except: continue
            if not photo_list: self.log.emit("No RAW files found."); self.finished.emit(); return
            photo_list.sort(key=lambda x: (x['ts'], x['name'])); dest = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, CONFIG["SAFE_MARKER"]), 'w') as f: f.write("OK")
            curr = []
            for i, photo in enumerate(photo_list):
                if not self._is_running: break
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap): curr.append(photo)
                else: self._process_group(curr, dest); curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr and self._is_running: self._process_group(curr, dest)
            self.progress.emit(100); self.log.emit("✓ Sorting completed.")
        except Exception as e: self.log.emit(f"Error: {e}")
        finally: self.finished.emit()

    def _process_group(self, group, base):
        s = self.stack_size
        if len(group) >= s and len(group) % s == 0:
            for i in range(len(group) // s):
                subset = group[i*s:(i+1)*s]
                if len(set([p['exp'] for p in subset])) > 1:
                    target = os.path.join(base, datetime.fromtimestamp(subset[0]['ts']).strftime('%Y-%m-%d_%H-%M-%S') + f"_{i}_reeks"); os.makedirs(target, exist_ok=True)
                    for idx, f in enumerate(subset):
                        src = os.path.join(self.source_dir, f['name']); smart_copy(src, os.path.join(target, f['name']))
                        if not (self.keep_first and idx == 0) and os.path.exists(src): os.remove(src)

# --- WORKER 2: HDR ---
class HdrWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self, base_dir, method, bit_depth, collect, cleanup, crop_percent):
        super().__init__(); self.base_dir, self.method, self.bit_depth, self.collect, self.cleanup, self.crop_percent = os.path.abspath(base_dir), method, bit_depth, collect, cleanup, crop_percent
        self._is_running = True
    def stop(self): self._is_running = False

    @Slot()
    def run(self):
        try:
            raws_here = [f for f in os.listdir(self.base_dir) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]
            subdirs = [self.base_dir] if raws_here else sorted([d.path for d in os.scandir(self.base_dir) if d.is_dir() and not d.name.startswith('.') and d.name != CONFIG["HDR_COLLECT_NAME"]])
            if not subdirs: self.log.emit("No folders found."); self.finished.emit(); return
            xmp = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG["DT_XMP_FILE"]); root = os.path.dirname(self.base_dir)
            for i, path in enumerate(subdirs):
                if not self._is_running: break
                name = os.path.basename(path); self.log.emit(f"\n--- Processing: {name} ---"); cfg = os.path.expanduser("~/.cache/panoflow_temp")
                if os.path.exists(cfg): shutil.rmtree(cfg)
                os.makedirs(cfg)
                if self.method in ["hdrmerge", "both"]:
                    res_dng = self._do_hdrmerge(path, name)
                    if res_dng and self.collect:
                        d_dest = os.path.join(root, CONFIG["HDR_COLLECT_NAME"], "DNG"); os.makedirs(d_dest, exist_ok=True); shutil.move(res_dng, os.path.join(d_dest, os.path.basename(res_dng)))
                if self.method in ["enfuse", "both"]:
                    res_tif = self._do_enfuse(path, name, cfg, xmp)
                    if res_tif and self.collect:
                        t_dest = os.path.join(root, CONFIG["HDR_COLLECT_NAME"], "TIFF"); os.makedirs(t_dest, exist_ok=True); shutil.move(res_tif, os.path.join(t_dest, os.path.basename(res_tif)))
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            if self._is_running and self.cleanup:
                marker = os.path.join(self.base_dir, CONFIG["SAFE_MARKER"]); (shutil.rmtree(self.base_dir) if os.path.exists(marker) else None)
            self.log.emit("\n<b>Finished.</b>")
        except Exception as e: self.log.emit(f"Error: {e}")
        finally: self.finished.emit()

    def _do_enfuse(self, path, name, cfg, xmp):
        raws = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]); tmp = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp, exist_ok=True); tifs = []; out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
        try:
            for idx, r in enumerate(raws):
                if not self._is_running: return None
                self.log.emit(f"    * Darktable: {r}"); out = os.path.join(tmp, f"{os.path.splitext(r)[0]}.tif"); raw_p = os.path.join(path, r); cmd = ['darktable-cli', raw_p]
                if xmp and os.path.exists(xmp): cmd.append(xmp)
                cmd.extend([out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl']); subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(out): reset_and_copy_metadata(raw_p, out); tifs.append(out)
            if len(tifs) >= 2 and self._is_running:
                ali = os.path.join(tmp, "ali_"); subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if self._is_running:
                    subprocess.run(['enfuse', '--exposure-weight=1.0', '--saturation-weight=0.5', '--contrast-weight=0.5', '--output', out_h] + sorted(glob.glob(f"{ali}*.tif")), env=ENV_STABLE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if self.crop_percent > 0: subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    reset_and_copy_metadata(os.path.join(path, raws[0]), out_h); return out_h
        finally: shutil.rmtree(tmp) if os.path.exists(tmp) else None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]); out_f = os.path.join(path, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-o', out_f] + raws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_f): copy_metadata_full(raws[0], out_f); return out_f

# --- MAIN GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoFlow v5.8"); self.setGeometry(100, 100, 800, 650); self.worker = None; self.thread = None; self.s2_manually_set = False
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs); self.t1, self.t2 = QWidget(), QWidget(); self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR verwerking")
        self.setup_t1(); self.setup_t2(); self.check_deps()

    def check_deps(self):
        m = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
        if m: QMessageBox.warning(self, "Tools Missing", f"De volgende programma's zijn niet gevonden: {', '.join(m)}")

    def _sync(self): (self.s2.setText(os.path.join(self.s1.text(), CONFIG["SORTED_DIR_NAME"])) if not self.s2_manually_set and self.s1.text() else None)

    def show_inf(self):
        txt = (
            "<h3>PanoFlow (v5.8) - Photo Workflow Automation</h3>"
            "<p>Automates management and processing of RAW files for panorama photography.</p>"
            "<b>1. Sorting & Organizing:</b><br>"
            "Groups RAW files into sequences based on capture time (default 1.0s gap). "
            "Master shots (1st frame) and loose photos stay in source folder. This creates a clean overview and "
            "secures a set of images for standard stitching if HDR fails.<br><br>"
            "<b>2. Batch HDR Production:</b><br>"
            "Processes sequences into TIFF (via Enfuse) or 32-bit DNG (via HDRmerge). "
            "Orientation fixes are applied automatically (Portrait shots stay upright).<br><br>"
            "<b>3. Collection & Cleanup:</b><br>"
            "HDR results are moved to 'Verzamelde_HDR_bestanden'. If enabled, temporary folders are deleted.<br><br>"
            "<b>The XMP Profile:</b> Only required for TIFF (Enfuse). Used for lens correction and dynamic range optimization."
        )
        QMessageBox.information(self, "PanoFlow Information", txt)

    def setup_t1(self):
        l = QVBoxLayout(self.t1); h_inf = QHBoxLayout(); h_inf.addStretch(); b_inf = QPushButton("Info / Help"); b_inf.clicked.connect(self.show_inf); h_inf.addWidget(b_inf); l.addLayout(h_inf)
        h1 = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); b1 = QPushButton("..."); b1.clicked.connect(lambda: self.sel(self.s1)); h1.addWidget(QLabel("Bronmap:")); h1.addWidget(self.s1); h1.addWidget(b1); l.addLayout(h1); self.s1.textChanged.connect(self._sync)
        h_g = QHBoxLayout(); h_g.addWidget(QLabel("Max. tijd tussen reeksen:")); self.gv = QDoubleSpinBox(); self.gv.setRange(0.1, 10.0); self.gv.setValue(1.0); self.gv.setSingleStep(0.1); h_g.addWidget(self.gv); h_g.addWidget(QLabel("sec")); h_g.addStretch(); l.addLayout(h_g)
        h2 = QHBoxLayout(); self.sc = QComboBox(); self.sc.addItems(["3", "5", "7"]); self.sc.setCurrentIndex(1); h2.addWidget(QLabel("Foto's per reeks:")); h2.addWidget(self.sc); h2.addStretch(); l.addLayout(h2)
        self.k = QCheckBox("Behoud de eerste foto van elke reeks in de bronmap"); self.k.setChecked(True); l.addWidget(self.k)
        self.b1 = QPushButton("Start Sorteren"); self.b1.clicked.connect(self.go1); l.addWidget(self.b1); self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); self.log1.setReadOnly(True); l.addWidget(self.log1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2); h = QHBoxLayout(); self.s2 = QLineEdit(); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s2)); h.addWidget(QLabel("Map met reeksen:")); h.addWidget(self.s2); h.addWidget(b); l.addLayout(h)
        self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); l.addWidget(self.m2)
        self.enf = QWidget(); el = QVBoxLayout(self.enf); el.setContentsMargins(0,0,0,0); hb = QHBoxLayout(); hb.addWidget(QLabel("Bit Diepte:")); self.bd = QComboBox(); self.bd.addItems(["8", "16"]); self.bd.setCurrentIndex(0); hb.addWidget(self.bd); hb.addStretch(); el.addLayout(hb)
        hc = QHBoxLayout(); hc.addWidget(QLabel("Rand-crop (shave):")); self.cp = QDoubleSpinBox(); self.cp.setRange(0, 10); self.cp.setValue(1.5); hc.addWidget(self.cp); hc.addWidget(QLabel("%")); hc.addStretch(); el.addLayout(hc); l.addWidget(self.enf); self.m2.currentIndexChanged.connect(lambda i: self.enf.setVisible(i != 1))
        self.c1 = QCheckBox("Verzamel resultaten"); self.c1.setChecked(True); l.addWidget(self.c1); self.c2 = QCheckBox("Verwijder reeks-mappen na afloop"); self.c2.setChecked(False); l.addWidget(self.c2)
        self.b2 = QPushButton("Start HDR Verwerking"); self.b2.clicked.connect(self.go2); l.addWidget(self.b2); self.p2 = QProgressBar(); l.addWidget(self.p2); self.log2 = QTextEdit(); self.log2.setReadOnly(True); l.addWidget(self.log2)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Map", e.text())
        if d: e.setText(d); self._sync() if e == self.s1 else None; (setattr(self, 's2_manually_set', True) if e == self.s2 else None)

    def go1(self):
        if self.worker: self.worker.stop(); return
        self.b1.setText("Stop"); self.log1.clear(); self.thread = QThread(); self.worker = SortWorker(self.s1.text(), int(self.sc.currentText()), self.k.isChecked(), self.gv.value())
        self._run(self.p1, self.log1, self.b1, "Start Sorteren")

    def go2(self):
        if self.worker: self.worker.stop(); return
        m = ["enfuse", "hdrmerge", "both"]; self.b2.setText("Stop"); self.log2.clear(); self.thread = QThread(); self.worker = HdrWorker(self.s2.text(), m[self.m2.currentIndex()], self.bd.currentText(), self.c1.isChecked(), self.c2.isChecked(), self.cp.value())
        self._run(self.p2, self.log2, self.b2, "Start HDR Verwerking")

    def _run(self, p, log, b, txt):
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.finished.connect(lambda: self._end(b, txt)); self.worker.log.connect(log.append); self.worker.progress.connect(p.setValue); self.thread.start()

    def _end(self, b, t):
        if self.thread: self.thread.quit(); self.thread.deleteLater()
        self.worker = None; self.thread = None; b.setText(t); b.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv); window = MainWindow(); window.show(); sys.exit(app.exec())
