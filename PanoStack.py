#!/usr/bin/env python3
"""
PanoStack Flow (v6.1.4)
- OPTIMALISATIE: Specifieke Enfuse-parameters voor Bursts voor maximale ruisonderdrukking (Mean Stacking).
- LOGICA: Burst = Gemiddelde van alle frames (ISO-ruis reductie).
- LOGICA: Reeks = Contrast/Exposure blending (HDR).
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
cores = os.cpu_count() or 2; ENV_STABLE = os.environ.copy(); ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))

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

try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QCheckBox, QMessageBox, QDoubleSpinBox)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt
except ImportError:
    print("Fout: PySide6 niet gevonden."); sys.exit(1)

# --- BASE WORKER ---
class BaseWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    def __init__(self): super().__init__(); self._is_running = True
    def stop(self): self._is_running = False

# --- WORKER 1: SORTEREN ---
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
                if not self._is_running: break
                p = line.split('\t')
                if len(p) < 6 or os.path.splitext(p[0])[1].upper() not in SUPPORTED_EXTS: continue
                try:
                    dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S")
                    model = p[4].strip().replace(' ', '_').replace('/', '-') if p[4] else "Onbekende_Camera"
                    iso = int(float(p[5])) if p[5] else 0
                    photo_list.append({'name': p[0], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[2]}A{p[3]}", 'model': model, 'iso': iso})
                except: continue

            if not photo_list: self.log.emit("Geen RAW bestanden gevonden."); self.finished.emit(); return
            photo_list.sort(key=lambda x: (x['ts'], x['name']))

            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            os.makedirs(dest_root, exist_ok=True)
            with open(os.path.join(dest_root, CONFIG["SAFE_MARKER"]), 'w') as f: f.write("OK")

            curr = []
            for i, photo in enumerate(photo_list):
                if not self._is_running: break
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap): curr.append(photo)
                else: self._process_group(curr, dest_root); curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr and self._is_running: self._process_group(curr, dest_root)
            self.progress.emit(100); self.log.emit(f"✓ Klaar! {self.sequence_count} items gesorteerd.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _process_group(self, group, dest_root):
        if len(group) < 2: return
        is_hdr = len(set([p['exp'] for p in group])) > 1
        if is_hdr:
            s = self.stack_size
            if len(group) >= s:
                for i in range(len(group) // s):
                    subset = group[i*s:(i+1)*s]
                    self._create_target_folder(subset, dest_root, "Reeks")
        else: self._create_target_folder(group, dest_root, "Burst")

    def _create_target_folder(self, photo_subset, dest_root, type_prefix):
        self.sequence_count += 1
        meta = photo_subset[0]
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

# --- WORKER 2: HDR & BURST ---
class HdrWorker(BaseWorker):
    def __init__(self, base_dir, method, bit_depth, collect, cleanup, crop_percent):
        super().__init__(); self.base_dir, self.method, self.bit_depth, self.collect, self.cleanup, self.crop_percent = os.path.abspath(base_dir), method, bit_depth, collect, cleanup, crop_percent
    @Slot()
    def run(self):
        try:
            subdirs = []
            for root, dirs, files in os.walk(self.base_dir):
                for d in dirs:
                    if d.startswith("Reeks_") or d.startswith("Burst_"): subdirs.append(os.path.join(root, d))
            subdirs.sort()
            if not subdirs: self.finished.emit(); return

            xmp = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG["DT_XMP_FILE"])
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])

            for i, path in enumerate(subdirs):
                if not self._is_running: break
                name = os.path.basename(path)
                is_burst = name.startswith("Burst_")
                self.log.emit(f"\n--- Verwerken: {name} ---")
                cfg = os.path.expanduser("~/.cache/panostack_temp")
                if os.path.exists(cfg): shutil.rmtree(cfg)
                os.makedirs(cfg)

                if self.method in ["hdrmerge", "both"] and not is_burst:
                    res_dng = self._do_hdrmerge(path, name)
                    if res_dng and os.path.exists(res_dng) and self.collect:
                        d_dest = os.path.join(coll_root, "DNG"); os.makedirs(d_dest, exist_ok=True); shutil.move(res_dng, os.path.join(d_dest, os.path.basename(res_dng)))
                elif is_burst and self.method in ["hdrmerge", "both"]:
                    self.log.emit("    - DNG overslaan: HDRmerge niet zinvol voor Bursts.")

                if self.method in ["enfuse", "both"]:
                    res_tif = self._do_enfuse(path, name, cfg, xmp, is_burst)
                    if res_tif and os.path.exists(res_tif) and self.collect:
                        t_dest = os.path.join(coll_root, "TIFF"); os.makedirs(t_dest, exist_ok=True); shutil.move(res_tif, os.path.join(t_dest, os.path.basename(res_tif)))

                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))

            if self._is_running and self.cleanup:
                for p in subdirs:
                    if os.path.basename(p).startswith("Reeks_"): shutil.rmtree(p)
                    elif os.path.basename(p).startswith("Burst_") and self.method in ["enfuse", "both"]: shutil.rmtree(p)
            self.log.emit("\n<b>Klaar.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _do_enfuse(self, path, name, cfg, xmp, is_burst):
        raws = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]); tmp = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp, exist_ok=True); tifs = []; out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
        try:
            for r in raws:
                if not self._is_running: return None
                out = os.path.join(tmp, f"{os.path.splitext(r)[0]}.tif"); raw_p = os.path.join(path, r); cmd = ['darktable-cli', raw_p]
                if xmp and os.path.exists(xmp): cmd.append(xmp)
                cmd.extend([out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl']); subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(out): reset_and_copy_metadata(raw_p, out); tifs.append(out)

            if len(tifs) >= 2 and self._is_running:
                ali = os.path.join(tmp, "ali_"); subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                alis = sorted(glob.glob(os.path.join(tmp, "ali_*.tif")))
                if alis and self._is_running:
                    # --- OPTIMALISATIE VOOR BURST vs HDR ---
                    if is_burst:
                        # Mean stacking: alle frames wegen even zwaar (maximale ruisonderdrukking)
                        self.log.emit("    * Enfuse: Optimaliseren voor ruisonderdrukking (Mean Stacking)...")
                        enf_cmd = ['enfuse', '--exposure-weight=1.0', '--saturation-weight=0', '--contrast-weight=0', '--output', out_h] + alis
                    else:
                        # HDR blending: weging op basis van contrast en verzadiging
                        enf_cmd = ['enfuse', '--exposure-weight=1.0', '--saturation-weight=0.5', '--contrast-weight=0.5', '--output', out_h] + alis

                    subprocess.run(enf_cmd, env=ENV_STABLE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(out_h):
                        if self.crop_percent > 0: subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        reset_and_copy_metadata(os.path.join(path, raws[0]), out_h); return out_h
        finally: shutil.rmtree(tmp) if os.path.exists(tmp) else None
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS]); out_f = os.path.join(path, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-o', out_f] + raws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_f): copy_metadata_full(raws[0], out_f); return out_f
        return None

# --- GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack Flow v6.1.4"); self.setGeometry(100, 100, 800, 650); self.worker = None; self.thread = None; self.s2_manually_set = False
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs); self.t1, self.t2 = QWidget(), QWidget(); self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR verwerking")
        self.setup_t1(); self.setup_t2(); self.check_deps()

    def check_deps(self):
        m = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
        if m: QMessageBox.warning(self, "Tools Missing", f"Niet gevonden: {', '.join(m)}")

    def _sync(self): (self.s2.setText(os.path.join(self.s1.text(), CONFIG["SORTED_DIR_NAME"])) if not self.s2_manually_set and self.s1.text() else None)

    def show_inf(self):
        txt = (
            "<h3>PanoStack Flow (v6.1.4)</h3>"
            "<b>Maximale Ruisonderdrukking bij Bursts:</b><br>"
            "Wanneer een burst wordt verwerkt tot TIFF, gebruikt het script nu <i>Mean Stacking</i>.<br>"
            "Dit betekent dat elke foto in de burst exact even zwaar wordt meegeteld om willekeurige sensorruis weg te filteren zonder details te verliezen.<br><br>"
            "<b>HDR Verwerking:</b><br>"
            "Voor HDR-brackets (verschillende belichtingen) blijft de focus op contrast en dynamisch bereik."
        )
        QMessageBox.information(self, "Informatie", txt)

    def setup_t1(self):
        l = QVBoxLayout(self.t1); h_inf = QHBoxLayout(); h_inf.addStretch(); b_inf = QPushButton("Info / Help"); b_inf.clicked.connect(self.show_inf); h_inf.addWidget(b_inf); l.addLayout(h_inf)
        h1 = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); b1 = QPushButton("..."); b1.clicked.connect(lambda: self.sel(self.s1)); h1.addWidget(QLabel("Bronmap:")); h1.addWidget(self.s1); h1.addWidget(b1); l.addLayout(h1); self.s1.textChanged.connect(self._sync)
        h_g = QHBoxLayout(); h_gap = QHBoxLayout(); h_gap.addWidget(QLabel("Max. tijd tussen reeksen:")); self.gv = QDoubleSpinBox(); self.gv.setRange(0.1, 10.0); self.gv.setValue(1.0); self.gv.setSingleStep(0.1); h_gap.addWidget(self.gv); h_gap.addWidget(QLabel("sec")); h_gap.addStretch(); l.addLayout(h_gap)
        h2 = QHBoxLayout(); self.sc = QComboBox(); self.sc.addItems(["3", "5", "7"]); self.sc.setCurrentIndex(1); h2.addWidget(QLabel("Foto's per HDR-reeks:")); h2.addWidget(self.sc); h2.addStretch(); l.addLayout(h2)
        self.k = QCheckBox("Behoud de eerste foto van elke reeks in de bronmap"); self.k.setChecked(True); l.addWidget(self.k)
        self.b1 = QPushButton("Start Sorteer"); self.b1.clicked.connect(self.go1); l.addWidget(self.b1); self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); self.log1.setReadOnly(True); l.addWidget(self.log1)

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
        self._run(self.p1, self.log1, self.b1, "Start Sorteer")

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
