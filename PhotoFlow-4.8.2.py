#!/usr/bin/env python3
"""
PANOFLOW (v48.2)
- FEATURE: Sub-seconde EXIF analyse (gebruikt milliseconden voor extreem snelle reeksen).
- FEATURE: Decimalen in tijdsinterval (bijv. 0.5s) voor ultra-strakke sortering.
- SYNC: Live-Sync van paden tussen Tab 1 en 2.
- ORIËNTATIE: Reset voor TIFF, Behoud voor DNG.
"""

import sys
import os
import shutil
import subprocess
from datetime import datetime
import glob

# --- CONFIGURATIE ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
    "SAFE_MARKER": ".safe_to_delete"
}

REQUIRED_TOOLS = ['exiftool', 'darktable-cli', 'align_image_stack', 'enfuse', 'hdrmerge', 'mogrify']
SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG']
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, (os.cpu_count() or 4) - 2))

# --- HELPER FUNCTIES ---

def smart_copy(src, dst):
    if sys.platform == "linux":
        try:
            subprocess.run(['cp', '--reflink=auto', src, dst], check=True, capture_output=True)
            return
        except: pass
    shutil.copy2(src, dst)

def reset_and_copy_metadata(src_raw, dst_hdr):
    try:
        subprocess.run([
            'exiftool', '-overwrite_original', '-tagsFromFile', src_raw,
            '-all:all', '--Orientation', '-Orientation=1', '-n', dst_hdr
        ], capture_output=True)
    except: pass

def copy_metadata_full(src_raw, dst_hdr):
    try:
        subprocess.run([
            'exiftool', '-overwrite_original', '-tagsFromFile', src_raw,
            '-all:all', dst_hdr
        ], capture_output=True)
    except: pass

try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QPushButton, QLabel, QLineEdit,
                                 QFileDialog, QProgressBar, QTextEdit, QTabWidget,
                                 QComboBox, QCheckBox, QMessageBox, QDoubleSpinBox)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt
except ImportError:
    print("Fout: PySide6 niet gevonden. Installeer met: pip install PySide6")
    sys.exit(1)

# --- WORKERS ---
class BaseWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self):
        super().__init__(); self._is_running = True
    def stop(self):
        self._is_running = False

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
            if not os.path.isdir(self.source_dir): return
            self.log.emit(f"PanoFlow: Analysing {self.source_dir} (Sub-second precision)...")

            # We vragen SubSecTimeOriginal op voor milliseconde-precisie
            cmd = ['exiftool', '-q', '-S3', '-T', '-n',
                   '-FileName', '-SubSecTimeOriginal', '-DateTimeOriginal',
                   '-ExposureTime', '-FNumber', '-Model', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            photo_list = []
            for line in filter(None, result.stdout.strip().split('\n')):
                if not self._is_running: break
                p = line.split('\t')
                if len(p) < 6 or os.path.splitext(p[0])[1].upper() not in SUPPORTED_EXTS: continue

                # Probeer tijd met milliseconden te parsen, anders fallback naar seconden
                try:
                    # p[1] is SubSecTimeOriginal (formaat: 2023:10:27 14:30:05.12)
                    dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S.%f")
                except:
                    dt = datetime.strptime(p[2], "%Y:%m:%d %H:%M:%S")

                photo_list.append({
                    'name': p[0],
                    'ts': dt.timestamp(),
                    'exp': f"S{p[3]}A{p[4]}"
                })

            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, CONFIG["SAFE_MARKER"]), 'w') as f: f.write("PanoFlow-Safe")

            curr = []
            for i, photo in enumerate(photo_list):
                if not self._is_running: break
                # Vergelijk timestamps (nu met float precisie voor milliseconden)
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap):
                    curr.append(photo)
                else:
                    self._process_group(curr, dest)
                    curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))

            if curr and self._is_running: self._process_group(curr, dest)
            self.progress.emit(100)
            self.log.emit("✓ Sorting completed." if self._is_running else "⚠ Interrupted.")
        except Exception as e: self.log.emit(f"Error: {e}")
        finally: self.finished.emit()

    def _process_group(self, group, base):
        s = self.stack_size
        total = len(group)
        if total >= s and total % s == 0:
            for i in range(total // s):
                subset = group[i*s:(i+1)*s]
                if len(set([p['exp'] for p in subset])) > 1:
                    # Mapnaam op basis van milliseconde-precisie om dubbele mappen te voorkomen
                    target = os.path.join(base, datetime.fromtimestamp(subset[0]['ts']).strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3] + '_reeks')
                    os.makedirs(target, exist_ok=True)
                    for idx, f in enumerate(subset):
                        src = os.path.join(self.source_dir, f['name'])
                        smart_copy(src, os.path.join(target, f['name']))
                        if not (self.keep_first and idx == 0) and os.path.exists(src): os.remove(src)

class HdrWorker(BaseWorker):
    def __init__(self, base_dir, method, bit_depth, collect, cleanup, crop_percent):
        super().__init__()
        self.base_dir, self.method, self.bit_depth = os.path.abspath(base_dir), method, bit_depth
        self.collect, self.cleanup, self.crop_percent = collect, cleanup, crop_percent

    @Slot()
    def run(self):
        try:
            subdirs = sorted([d.path for d in os.scandir(self.base_dir) if d.is_dir() and not d.name.startswith('.')])
            if not subdirs: self.log.emit("No folders found."); self.finished.emit(); return
            script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            xmp = os.path.join(script_dir, CONFIG["DT_XMP_FILE"])
            collect_dest = os.path.join(os.path.dirname(self.base_dir), CONFIG["HDR_COLLECT_NAME"])
            if self.collect: os.makedirs(collect_dest, exist_ok=True)

            for i, path in enumerate(subdirs):
                if not self._is_running: break
                name = os.path.basename(path)
                self.log.emit(f"\n--- Processing: {name} ---")
                cfg = os.path.expanduser("~/.cache/panoflow_temp")
                if os.path.exists(cfg): shutil.rmtree(cfg)
                os.makedirs(cfg)

                result_file = None
                if self.method == 'enfuse': result_file = self._do_enfuse(path, name, cfg, xmp)
                else: result_file = self._do_hdrmerge(path, name)

                if result_file and self.collect and self._is_running:
                    shutil.move(result_file, os.path.join(collect_dest, os.path.basename(result_file)))
                self.progress.emit(int(((i + 1) / len(subdirs)) * 95))

            if self._is_running and self.cleanup: self._do_cleanup()
            self.progress.emit(100)
            self.log.emit("\n<b>Finished.</b>" if self._is_running else "\n<b>Aborted.</b>")
        except Exception as e: self.log.emit(f"Error: {e}")
        finally: self.finished.emit()

    def _do_enfuse(self, path, name, cfg, xmp):
        raws = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS])
        if not raws: return None
        tmp = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp, exist_ok=True)
        tifs = []
        out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
        try:
            for r in raws:
                if not self._is_running: return None
                out = os.path.join(tmp, f"{os.path.splitext(r)[0]}.tif")
                raw_path = os.path.join(path, r)
                cmd = ['darktable-cli', raw_path]
                if xmp and os.path.exists(xmp): cmd.append(xmp)
                cmd.extend([out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl'])
                subprocess.run(cmd, capture_output=True)
                if os.path.exists(out): reset_and_copy_metadata(raw_path, out); tifs.append(out)
            if len(tifs) >= 2 and self._is_running:
                ali = os.path.join(tmp, "ali_"); res = subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, capture_output=True)
                if res.returncode == 0 and self._is_running:
                    cmd_enf = ['enfuse', '--exposure-weight=1.0', '--saturation-weight=0.5', '--contrast-weight=0.5', '--output', out_h]
                    subprocess.run(cmd_enf + sorted(glob.glob(f"{ali}*.tif")), env=ENV_STABLE, capture_output=True)
                    if self.crop_percent > 0:
                        subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h])
                    reset_and_copy_metadata(os.path.join(path, raws[0]), out_h)
                    self.log.emit(f"  ✓ TIFF Ready.")
                    return out_h
        finally: shutil.rmtree(tmp) if os.path.exists(tmp) else None
        return None

    def _do_hdrmerge(self, path, name):
        raw_files = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS])
        if not raw_files: return None
        raw_paths = [os.path.join(path, f) for f in raw_files]
        out_f = os.path.join(path, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-o', out_f] + raw_paths, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_f):
            copy_metadata_full(raw_paths[0], out_f)
            self.log.emit(f"  ✓ DNG Ready.")
            return out_f
        return None

    def _do_cleanup(self):
        marker = os.path.join(self.base_dir, CONFIG["SAFE_MARKER"])
        if os.path.exists(marker):
            shutil.rmtree(self.base_dir)

# --- MAIN GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoFlow v48.2"); self.setGeometry(100, 100, 800, 650); self.worker = None; self.thread = None
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs); self.t1, self.t2 = QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR verwerking")
        self.setup_t1(); self.setup_t2(); self.check_deps()

    def check_deps(self):
        m = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
        if m: QMessageBox.warning(self, "Tools Missing", f"Required programs not found: {', '.join(m)}")

    def _sync_paths(self):
        source = self.s1.text()
        if source:
            self.s2.setText(os.path.join(source, CONFIG["SORTED_DIR_NAME"]))

    def setup_t1(self):
        l = QVBoxLayout(self.t1); btn = QPushButton("Info / Help"); btn.clicked.connect(self.info); l.addWidget(btn, 0, Qt.AlignRight)
        h1 = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); b1 = QPushButton("..."); b1.clicked.connect(lambda: self.sel(self.s1))
        h1.addWidget(QLabel("Bronmap:")); h1.addWidget(self.s1); h1.addWidget(b1); l.addLayout(h1)
        self.s1.textChanged.connect(self._sync_paths)

        h_gap = QHBoxLayout()
        h_gap.addWidget(QLabel("Max. tijd tussen reeksen:"));
        self.gap_val = QDoubleSpinBox()
        self.gap_val.setRange(0.1, 10.0); self.gap_val.setValue(1.0); self.gap_val.setSingleStep(0.5)
        h_gap.addWidget(self.gap_val); h_gap.addWidget(QLabel("seconden (precisie: 0.1s)")); h_gap.addStretch()
        l.addLayout(h_gap)

        h2 = QHBoxLayout(); self.sc = QComboBox(); self.sc.addItems(["3", "5", "7"]); self.sc.setCurrentIndex(1)
        h2.addWidget(QLabel("Foto's per reeks:")); h2.addWidget(self.sc); h2.addStretch(); l.addLayout(h2)

        self.k = QCheckBox("Behoud de eerste foto van elke reeks in de bronmap"); self.k.setChecked(True); l.addWidget(self.k)
        self.b1 = QPushButton("Start Sorteren"); self.b1.clicked.connect(self.go1); l.addWidget(self.b1)
        self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); self.log1.setReadOnly(True); l.addWidget(self.log1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2); h = QHBoxLayout(); self.s2 = QLineEdit(); b = QPushButton("..."); b.clicked.connect(lambda: self.sel(self.s2))
        h.addWidget(QLabel("Map met reeksen:")); h.addWidget(self.s2); h.addWidget(b); l.addLayout(h)
        self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)"]); l.addWidget(self.m2)
        self.enf = QWidget(); el = QVBoxLayout(self.enf); el.setContentsMargins(0,0,0,0)
        h_bit = QHBoxLayout(); h_bit.addWidget(QLabel("Bit Diepte:")); self.bd = QComboBox(); self.bd.addItems(["16", "8"]); h_bit.addWidget(self.bd); h_bit.addStretch(); el.addLayout(h_bit)
        h_crop = QHBoxLayout(); h_crop.addWidget(QLabel("Rand-crop percentage (shave):")); self.cp = QDoubleSpinBox(); self.cp.setRange(0, 10); self.cp.setValue(1.5); h_crop.addWidget(self.cp); h_crop.addWidget(QLabel("%")); h_crop.addStretch(); el.addLayout(h_crop)
        l.addWidget(self.enf); self.m2.currentIndexChanged.connect(lambda i: self.enf.setVisible(i==0))
        self.c1 = QCheckBox("Verzamel resultaten"); self.c1.setChecked(True); l.addWidget(self.c1)
        self.c2 = QCheckBox("Verwijder reeks-mappen na afloop"); self.c2.setChecked(False); l.addWidget(self.c2)
        self.b2 = QPushButton("Start HDR Verwerking"); self.b2.clicked.connect(self.go2); l.addWidget(self.b2)
        self.p2 = QProgressBar(); l.addWidget(self.p2); self.log2 = QTextEdit(); self.log2.setReadOnly(True); l.addWidget(self.log2)

    def info(self):
        txt = "<h3>PanoFlow (v48.2)</h3><p><b>Precision:</b> Added sub-second EXIF analysis for rapid sequence bursts.</p>"
        QMessageBox.information(self, "PanoFlow Info", txt)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Select Folder", e.text());
        if d:
            e.setText(d)
            if e == self.s1: self._sync_paths()

    def go1(self):
        if self.worker: self.worker.stop(); return
        self.b1.setText("Stop Sorteren"); self.log1.clear(); self.thread = QThread()
        self.worker = SortWorker(self.s1.text(), int(self.sc.currentText()), self.k.isChecked(), self.gap_val.value())
        self._run(self.p1, self.log1, self.b1, "Start Sorteren")

    def go2(self):
        if self.worker: self.worker.stop(); return
        self.b2.setText("Stop Verwerking"); self.log2.clear(); self.thread = QThread()
        self.worker = HdrWorker(self.s2.text(), 'enfuse' if self.m2.currentIndex()==0 else 'hdrmerge', self.bd.currentText(), self.c1.isChecked(), self.c2.isChecked(), self.cp.value() if self.m2.currentIndex()==0 else 0)
        self._run(self.p2, self.log2, self.b2, "Start HDR Verwerking")

    def _run(self, bar, log, btn, txt):
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(lambda: self._on_finish(btn, txt))
        self.worker.log.connect(log.append); self.worker.progress.connect(bar.setValue); self.thread.start()

    def _on_finish(self, btn, txt):
        self.thread.quit(); self.thread.wait(); self.worker = None; btn.setText(txt); btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv); window = MainWindow(); window.show(); sys.exit(app.exec())
