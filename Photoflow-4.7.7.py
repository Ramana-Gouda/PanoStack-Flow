#!/usr/bin/env python3
"""
FOTO WORKFLOW AUTOMATISERING (v4.7.7)
- GUI: Informatie-knop toegevoegd in Tab 1.
- INTEGRATIE: Verzamelen en opruimen in HDR-stap.
- VEILIGHEID: Marker-controle voor opschonen mappen.
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
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, (os.cpu_count() or 4) - 2))

def smart_copy(src, dst):
    if sys.platform == "linux":
        try:
            subprocess.run(['cp', '--reflink=auto', src, dst], check=True, capture_output=True)
            return
        except: pass
    shutil.copy2(src, dst)

try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QPushButton, QLabel, QLineEdit,
                                 QFileDialog, QProgressBar, QTextEdit, QTabWidget,
                                 QComboBox, QCheckBox, QMessageBox)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt
except ImportError:
    print("Fout: PySide6 niet gevonden.")
    sys.exit(1)

# --- WORKER: STAP 1 (SORTEREN) ---
class SortWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self, source_dir, stack_size, keep_first):
        super().__init__(); self.source_dir, self.stack_size, self.keep_first = source_dir, stack_size, keep_first

    @Slot()
    def run(self):
        try:
            if not os.path.isdir(self.source_dir): return
            self.log.emit(f"Stap 1: Analyse in {self.source_dir}...")
            cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            photo_list = []
            for line in filter(None, result.stdout.strip().split('\n')):
                parts = line.split('\t')
                if len(parts) < 5 or os.path.splitext(parts[0])[1].upper() not in SUPPORTED_EXTS: continue
                dt = datetime.strptime(parts[1], "%Y:%m:%d %H:%M:%S")
                photo_list.append({'name': parts[0], 'ts': int(dt.timestamp()), 'exp': f"S{parts[2]}A{parts[3]}"})

            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest_base = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest_base, exist_ok=True)
            with open(os.path.join(dest_base, CONFIG["SAFE_MARKER"]), 'w') as f: f.write("OK")

            curr = []
            for i, photo in enumerate(photo_list):
                if not curr or (photo['ts'] - curr[-1]['ts'] <= CONFIG["MAX_GAP_SECONDS"]): curr.append(photo)
                else: self._process_group(curr, dest_base); curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr: self._process_group(curr, dest_base)
            self.log.emit("✓ Sorteren voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _process_group(self, group, base):
        s = self.stack_size
        if len(group) % s == 0:
            for i in range(len(group) // s):
                subset = group[i*s:(i+1)*s]
                if len(set([p['exp'] for p in subset])) > 1:
                    target = os.path.join(base, datetime.fromtimestamp(subset[0]['ts']).strftime('%Y-%m-%d_%H-%M-%S_reeks'))
                    os.makedirs(target, exist_ok=True)
                    for idx, f in enumerate(subset):
                        src = os.path.join(self.source_dir, f['name'])
                        smart_copy(src, os.path.join(target, f['name']))
                        if not (self.keep_first and idx == 0):
                            if os.path.exists(src): os.remove(src)

# --- WORKER: STAP 2 (HDR + VERZAMELEN) ---
class HdrWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self, base_dir, method, bit_depth, collect, cleanup):
        super().__init__()
        self.base_dir = os.path.abspath(base_dir)
        self.method = method
        self.bit_depth = bit_depth
        self.collect = collect
        self.cleanup = cleanup

    @Slot()
    def run(self):
        try:
            subdirs = sorted([d.path for d in os.scandir(self.base_dir) if d.is_dir() and not d.name.startswith('.')])
            if not subdirs:
                self.log.emit("Geen mappen gevonden."); self.finished.emit(); return

            script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            xmp_path = os.path.join(script_dir, CONFIG["DT_XMP_FILE"])

            for i, path in enumerate(subdirs):
                name = os.path.basename(path)
                self.log.emit(f"\n--- Verwerken: {name} ---")
                cfg_dir = os.path.expanduser("~/.cache/darktable_workflow_temp")
                if os.path.exists(cfg_dir): shutil.rmtree(cfg_dir)
                os.makedirs(cfg_dir)

                if self.method == 'enfuse': self._do_enfuse_stable(path, name, cfg_dir, xmp_path)
                else: self._do_hdrmerge(path, name)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 80))

            if self.collect:
                self.log.emit("\n--- Resultaten verzamelen ---")
                dest = os.path.join(os.path.dirname(self.base_dir), CONFIG["HDR_COLLECT_NAME"])
                os.makedirs(dest, exist_ok=True)
                found_files = glob.glob(os.path.join(self.base_dir, '**', '*_HDR_*.tif'), recursive=True) + \
                              glob.glob(os.path.join(self.base_dir, '**', '*_HDR.dng'), recursive=True)
                for f in list(set(found_files)):
                    if dest not in f: shutil.move(f, os.path.join(dest, os.path.basename(f)))
                self.log.emit(f"✓ Bestanden verplaatst naar '{CONFIG['HDR_COLLECT_NAME']}'.")

            if self.cleanup:
                if os.path.exists(os.path.join(self.base_dir, CONFIG["SAFE_MARKER"])):
                    shutil.rmtree(self.base_dir)
                    self.log.emit("✓ Reeks-mappen opgeruimd.")

            self.progress.emit(100); self.log.emit("\n<b>Batch voltooid.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _do_enfuse_stable(self, path, name, cfg, xmp):
        raw_files = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS])
        if not raw_files: return
        tmp_dir = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp_dir, exist_ok=True)
        tifs = []
        try:
            for r in raw_files:
                out = os.path.join(tmp_dir, f"{os.path.splitext(r)[0]}.tif")
                cmd = ['darktable-cli', os.path.join(path, r)]
                if xmp and os.path.exists(xmp): cmd.append(xmp)
                cmd.extend([out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl'])
                subprocess.run(cmd, capture_output=True)
                if os.path.exists(out): tifs.append(out)
            if len(tifs) >= 2:
                ali = os.path.join(tmp_dir, "ali_")
                res = subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, capture_output=True)
                if res.returncode == 0:
                    out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
                    cmd_enf = ['enfuse', '--exposure-weight=1', '--saturation-weight=0.2', '--hard-mask', '--output', out_h]
                    subprocess.run(cmd_enf + sorted(glob.glob(f"{ali}*.tif")), env=ENV_STABLE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            if os.path.exists(tmp_dir): shutil.rmtree(tmp_dir)

    def _do_hdrmerge(self, path, name):
        raws = [os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]
        out_d = os.path.join(path, CONFIG["HDRMERGE_DIR_NAME"]); os.makedirs(out_d, exist_ok=True)
        out_f = os.path.join(out_d, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-o', out_f] + raws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Workflow Foto Automatisering v47.7"); self.setGeometry(100, 100, 800, 600)
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.t1, self.t2 = QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR verwerking")
        self.setup_t1(); self.setup_t2()

    def show_info(self):
        info_text = (
            "<h3>Photo Workflow Automation (v47.7)</h3>"
            "<p>This program automates the management and processing of large quantities of RAW image files, "
            "designed for panorama construction.</p>"
            "<b>1. Sorting and Organizing:</b><br>"
            "RAW files are automatically grouped into sequences based on capture time and exposure differences. "
            "Only the first capture of each sequence, along with individual loose photos, remains in the source folder. "
            "This creates a clean overview and secures a standard set of images for stitching should HDR results yield 'ghosting'.<br><br>"
            "<b>2. Batch HDR Production:</b><br>"
            "Identified sequences are processed into HDR files (TIFF via Enfuse or 32-bit DNG via HDRmerge). "
            "Processing occurs serially per folder to prevent system overload while utilizing all processor threads.<br><br>"
            "<b>3. Collection and Cleanup:</b><br>"
            "HDR results are moved to 'Verzamelde_HDR_bestanden' one level above the working directory. "
            "Temporary folders can be deleted automatically after successful processing.<br><br>"
            "<b>The XMP Profile (oppepper.xmp):</b><br>"
            "Required only for <i>Enfuse (TIFF)</i>. It applies <b>lens correction</b> (crucial for accurate alignment) "
            "and pre-optimizes dynamic range via modules like Sigmoid."
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("Program Information")
        msg.setTextFormat(Qt.RichText)
        msg.setText(info_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    def setup_t1(self):
        l = QVBoxLayout(self.t1)

        # Info knop bovenaan
        h_info = QHBoxLayout(); h_info.addStretch()
        btn_info = QPushButton("Info / Help"); btn_info.setFixedWidth(100)
        btn_info.clicked.connect(self.show_info); h_info.addWidget(btn_info); l.addLayout(h_info)

        h1 = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); b1 = QPushButton("...")
        b1.clicked.connect(lambda: self.sel(self.s1)); h1.addWidget(QLabel("Bronmap:")); h1.addWidget(self.s1); h1.addWidget(b1); l.addLayout(h1)

        h2 = QHBoxLayout(); self.sc = QComboBox(); self.sc.addItems(["3", "5", "7"]); self.sc.setCurrentIndex(1)
        h2.addWidget(QLabel("Foto's per reeks:")); h2.addWidget(self.sc); h2.addStretch(); l.addLayout(h2)

        self.keep_cb = QCheckBox("Behoud de eerste foto van elke reeks in de bronmap")
        self.keep_cb.setChecked(True); l.addWidget(self.keep_cb)

        self.b_start1 = QPushButton("Start Sorteren"); self.b_start1.clicked.connect(self.go1); l.addWidget(self.b_start1)
        self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); self.log1.setReadOnly(True); l.addWidget(self.log1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2)
        h = QHBoxLayout(); self.s2 = QLineEdit(); b = QPushButton("...")
        b.clicked.connect(lambda: self.sel(self.s2)); h.addWidget(QLabel("Map met reeksen:")); h.addWidget(self.s2); h.addWidget(b); l.addLayout(h)
        self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)"]); l.addWidget(self.m2)
        self.enf_o = QWidget(); el = QVBoxLayout(self.enf_o); el.setContentsMargins(0,0,0,0)
        el.addWidget(QLabel("Bit Diepte:")); self.bd = QComboBox(); self.bd.addItems(["16", "8"]); el.addWidget(self.bd); l.addWidget(self.enf_o)
        self.m2.currentIndexChanged.connect(lambda i: self.enf_o.setVisible(i==0))
        self.coll_cb = QCheckBox("Verzamel resultaten in centrale map"); self.coll_cb.setChecked(True); l.addWidget(self.coll_cb)
        self.cln_cb = QCheckBox("Verwijder reeks-mappen na afloop"); self.cln_cb.setChecked(True); l.addWidget(self.cln_cb)
        self.b_start2 = QPushButton("Start HDR Verwerking"); self.b_start2.clicked.connect(self.go2); l.addWidget(self.b_start2)
        self.p2 = QProgressBar(); l.addWidget(self.p2); self.log2 = QTextEdit(); self.log2.setReadOnly(True); l.addWidget(self.log2)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Kies map", e.text()); e.setText(d) if d else None

    def _lock_ui(self, lock=True):
        self.b_start1.setEnabled(not lock); self.b_start2.setEnabled(not lock)

    def go1(self):
        self._lock_ui(True); self.log1.clear(); self.thread = QThread()
        self.worker = SortWorker(self.s1.text(), int(self.sc.currentText()), self.keep_cb.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(lambda: self._lock_ui(False))
        self.worker.log.connect(self.log1.append); self.worker.progress.connect(self.p1.setValue); self.thread.start()
        p = os.path.join(self.s1.text(), CONFIG["SORTED_DIR_NAME"]); self.s2.setText(p)

    def go2(self):
        self._lock_ui(True); self.log2.clear(); self.thread = QThread()
        self.worker = HdrWorker(self.s2.text(), 'enfuse' if self.m2.currentIndex()==0 else 'hdrmerge', self.bd.currentText(), self.coll_cb.isChecked(), self.cln_cb.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(lambda: self._lock_ui(False))
        self.worker.log.connect(self.log2.append); self.worker.progress.connect(self.p2.setValue); self.thread.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow(); w.show(); sys.exit(app.exec())
