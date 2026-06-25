#!/usr/bin/env python3
"""
FOTO WORKFLOW AUTOMATISERING (v47.1)
- STABILITEIT: Seriële verwerking per map (voorkomt vervorming/smalle beelden).
- VEILIGHEID: Gebruikt '.safe_to_delete' marker voor Stap 3.
- CAMERA: Ondersteunt ARW, CR2, CR3, NEF, RW2 (één merk per sessie aanbevolen).
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
    "HDRMERGE_DIR_NAME": "hdr_dng_files",
    "MAX_GAP_SECONDS": 4,
    "DT_XMP_FILE": "oppepper.xmp",
    "SAFE_MARKER": ".safe_to_delete"
}

SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG']
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = "12" # Ryzen 3600 threads

try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QPushButton, QLabel, QLineEdit,
                                 QFileDialog, QProgressBar, QTextEdit, QTabWidget,
                                 QComboBox, QCheckBox, QMessageBox)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt
except ImportError:
    print("Fout: PySide6 niet gevonden.")
    sys.exit(1)

def smart_copy(src, dst):
    """Btrfs Reflink ondersteuning."""
    try:
        subprocess.run(['cp', '--reflink=auto', src, dst], check=True, capture_output=True)
    except:
        shutil.copy2(src, dst)

# --- WORKER: STAP 1 (SORTEREN) ---
class SortWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)

    def __init__(self, source_dir, stack_mode, keep_mode):
        super().__init__()
        self.source_dir, self.stack_mode, self.keep_mode = source_dir, stack_mode, keep_mode

    @Slot()
    def run(self):
        try:
            allowed = [3] if self.stack_mode == 1 else [5] if self.stack_mode == 2 else [7] if self.stack_mode == 3 else [7, 5, 3]
            self.log.emit(f"Stap 1: RAW analyse in {self.source_dir}...")

            cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal',
                   '-ExposureTime', '-FNumber', '-Model', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            photo_list = []
            models = set()

            for line in filter(None, result.stdout.strip().split('\n')):
                parts = line.split('\t')
                if len(parts) < 5: continue
                if os.path.splitext(parts[0])[1].upper() not in SUPPORTED_EXTS: continue

                dt = datetime.strptime(parts[1], "%Y:%m:%d %H:%M:%S")
                models.add(parts[4])
                photo_list.append({'name': parts[0], 'ts': int(dt.timestamp()), 'exp': f"S{parts[2]}A{parts[3]}"})

            if not photo_list:
                self.log.emit("Geen RAW-bestanden gevonden."); self.finished.emit(); return

            self.log.emit(f"✓ Camera(s): {', '.join(models)}")

            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest_base = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest_base, exist_ok=True)

            # Veiligheidsmarker plaatsen
            with open(os.path.join(dest_base, CONFIG["SAFE_MARKER"]), 'w') as f:
                f.write("OK")

            curr = []
            for i, photo in enumerate(photo_list):
                if not curr or (photo['ts'] - curr[-1]['ts'] <= CONFIG["MAX_GAP_SECONDS"]):
                    curr.append(photo)
                else:
                    self._process_group(curr, dest_base, allowed)
                    curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr: self._process_group(curr, dest_base, allowed)
            self.log.emit("Sorteren voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _process_group(self, group, base, allowed):
        total = len(group)
        for s in allowed:
            if s > 0 and total % s == 0:
                for i in range(total // s):
                    subset = group[i*s:(i+1)*s]
                    if len(set([p['exp'] for p in subset])) > 1:
                        target = os.path.join(base, datetime.fromtimestamp(subset[0]['ts']).strftime('%Y-%m-%d_%H-%M-%S_reeks'))
                        os.makedirs(target, exist_ok=True)
                        for idx, f in enumerate(subset):
                            src = os.path.join(self.source_dir, f['name'])
                            smart_copy(src, os.path.join(target, f['name']))
                            if self.keep_mode == 1 or (self.keep_mode == 0 and idx > 0):
                                if os.path.exists(src): os.remove(src)
                return

# --- WORKER: STAP 2 (HDR VERWERKING) ---
class HdrWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self, base_dir, method, bit_depth):
        super().__init__(); self.base_dir, self.method, self.bit_depth = base_dir, method, bit_depth

    @Slot()
    def run(self):
        try:
            subdirs = sorted([d.path for d in os.scandir(self.base_dir) if d.is_dir() and not d.name.startswith('_')])
            if not subdirs: self.log.emit("Geen mappen gevonden."); self.finished.emit(); return

            cfg_dir = os.path.expanduser("~/.cache/darktable_workflow_v47")

            for i, path in enumerate(subdirs):
                name = os.path.basename(path)
                self.log.emit(f"\n--- Verwerken: {name} ---")
                if os.path.exists(cfg_dir): shutil.rmtree(cfg_dir)
                os.makedirs(cfg_dir)

                if self.method == 'enfuse': self._do_enfuse_stable(path, name, cfg_dir)
                else: self._do_hdrmerge(path, name)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            self.log.emit("\nBatch voltooid."); self.finished.emit()
        except Exception as e: self.log.emit(f"Fout: {e}"); self.finished.emit()

    def _do_enfuse_stable(self, path, name, cfg):
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        xmp = os.path.join(script_dir, CONFIG["DT_XMP_FILE"])
        raw_files = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS])
        if not raw_files: return

        tmp_dir = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp_dir, exist_ok=True)
        tifs = []
        for r in raw_files:
            self.log.emit(f"  > Converteren: {r}")
            out = os.path.join(tmp_dir, f"{os.path.splitext(r)[0]}.tif")
            # We gebruiken darktable-cli met een schone cache per sessie
            cmd = ['darktable-cli', os.path.join(path, r), xmp, out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl']
            subprocess.run(cmd, capture_output=True)
            if os.path.exists(out): tifs.append(out)

        if len(tifs) >= 2:
            self.log.emit("  > Uitlijnen...")
            ali = os.path.join(tmp_dir, "ali_")
            subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            self.log.emit("  > Samenvoegen beelden...")
            out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
            cmd = ['enfuse', '--exposure-weight=1', '--saturation-weight=0.2', '--hard-mask', '--output', out_h]
            subprocess.run(cmd + sorted(glob.glob(f"{ali}*.tif")), env=ENV_STABLE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log.emit(f"  ✓ TIFF Gereed.")
        shutil.rmtree(tmp_dir)

    def _do_hdrmerge(self, path, name):
        raws = [os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]
        out_d = os.path.join(path, CONFIG["HDRMERGE_DIR_NAME"]); os.makedirs(out_d, exist_ok=True)
        out_f = os.path.join(out_d, f"{name}_HDR.dng")
        res = subprocess.run(['hdrmerge', '-o', out_f] + raws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0: self.log.emit(f"  ✓ DNG Gereed.")

# --- WORKER: STAP 3 (VERZAMELEN) ---
class PanoWorker(QObject):
    finished, log = Signal(), Signal(str)
    def __init__(self, sorted_dir, cleanup_enabled):
        super().__init__(); self.sorted_dir = os.path.abspath(sorted_dir); self.cleanup_enabled = cleanup_enabled
    @Slot()
    def run(self):
        marker = os.path.join(self.sorted_dir, CONFIG["SAFE_MARKER"])
        if self.cleanup_enabled and not os.path.exists(marker):
            self.log.emit("<font color='red'><b>VEILIGHEIDS-STOP:</b> Marker niet gevonden. Map wordt niet verwijderd.</font>")
            self.cleanup_enabled = False

        parent = os.path.dirname(self.sorted_dir)
        dest = os.path.join(parent, CONFIG["HDR_COLLECT_NAME"]); os.makedirs(dest, exist_ok=True)
        found = 0
        all_f = glob.glob(os.path.join(self.sorted_dir, '**', '*_HDR_*.tif'), recursive=True) + \
                glob.glob(os.path.join(self.sorted_dir, '**', '*_HDR.dng'), recursive=True)

        for f in list(set(all_f)):
            if dest in f: continue
            try: shutil.move(f, os.path.join(dest, os.path.basename(f))); found += 1
            except: pass

        self.log.emit(f"✓ {found} bestanden verzameld in '{CONFIG['HDR_COLLECT_NAME']}'.")
        if self.cleanup_enabled:
            shutil.rmtree(self.sorted_dir)
            self.log.emit("✓ Werkmap volledig opgeruimd.")
        self.finished.emit()

# --- GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Workflow Foto Automatisering v47.1"); self.setGeometry(100, 100, 800, 650)
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3 = QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Verzamelen")
        self.setup_t1(); self.setup_t2(); self.setup_t3()

    def setup_t1(self):
        l = QVBoxLayout(self.t1); h = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s1)); h.addWidget(QLabel("Bron:")); h.addWidget(self.s1); h.addWidget(b); l.addLayout(h)
        self.sc = QComboBox(); self.sc.addItems(["Auto", "Vast 3", "Vast 5", "Vast 7"]); l.addWidget(QLabel("Stack-grootte:")); l.addWidget(self.sc)
        self.kc = QComboBox(); self.kc.addItems(["Bewaar de 1e foto van elke reeks en alle enkele foto's", "Bewaar alleen de losse foto's (verplaats alle reeksen)"]); l.addWidget(self.kc)
        self.b1 = QPushButton("Start Sorteren"); self.b1.clicked.connect(self.go1); l.addWidget(self.b1)
        self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); self.log1.setReadOnly(True); l.addWidget(self.log1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2); h = QHBoxLayout(); self.s2 = QLineEdit(); b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s2)); h.addWidget(QLabel("Map:")); h.addWidget(self.s2); h.addWidget(b); l.addLayout(h)
        self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)"]); l.addWidget(self.m2)
        self.enf_o = QWidget(); el = QVBoxLayout(self.enf_o); el.addWidget(QLabel("Bit Diepte:")); self.bd = QComboBox(); self.bd.addItems(["8", "16"]); el.addWidget(self.bd); l.addWidget(self.enf_o)
        self.m2.currentIndexChanged.connect(lambda i: self.enf_o.setVisible(i==0))
        self.b2 = QPushButton("Start HDR Verwerking"); self.b2.clicked.connect(self.go2); l.addWidget(self.b2)
        self.p2 = QProgressBar(); l.addWidget(self.p2); self.log2 = QTextEdit(); self.log2.setReadOnly(True); l.addWidget(self.log2)

    def setup_t3(self):
        l = QVBoxLayout(self.t3); h = QHBoxLayout(); self.s3 = QLineEdit(); b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s3)); h.addWidget(QLabel("Bron:")); h.addWidget(self.s3); h.addWidget(b); l.addLayout(h)
        self.cl_ch = QCheckBox("Verwijder de map 'geordend_op_reeks' na verzamelen"); self.cl_ch.setChecked(True); l.addWidget(self.cl_ch)
        self.b3 = QPushButton("Verzamel resultaten & Ruim op"); self.b3.clicked.connect(self.go3); l.addWidget(self.b3)
        self.log3 = QTextEdit(); self.log3.setReadOnly(True); l.addWidget(self.log3)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Kies map", e.text()); e.setText(d) if d else None
    def go1(self):
        self.log1.clear(); self.thread = QThread(); self.worker = SortWorker(self.s1.text(), self.sc.currentIndex(), self.kc.currentIndex())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.finished.connect(self.thread.quit); self.worker.log.connect(self.log1.append); self.worker.progress.connect(self.p1.setValue); self.thread.start()
        p = os.path.join(self.s1.text(), CONFIG["SORTED_DIR_NAME"]); self.s2.setText(p); self.s3.setText(p)
    def go2(self):
        self.log2.clear(); self.thread = QThread(); self.worker = HdrWorker(self.s2.text(), 'enfuse' if self.m2.currentIndex()==0 else 'hdrmerge', self.bd.currentText())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.finished.connect(self.thread.quit); self.worker.log.connect(self.log2.append); self.worker.progress.connect(self.p2.setValue); self.thread.start()
    def go3(self):
        self.log3.clear(); self.thread = QThread(); self.worker = PanoWorker(self.s3.text(), self.cl_ch.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.finished.connect(self.thread.quit); self.worker.log.connect(self.log3.append); self.thread.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow(); w.show(); sys.exit(app.exec())
