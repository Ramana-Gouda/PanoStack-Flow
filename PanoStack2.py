#!/usr/bin/env python3
"""
PanoStack Flow (v9.6.1)
-----------------------
ARCH LINUX INSTALLATIE:
Mocht het script na een update niet starten, voer dit uit:
$ sudo pacman -S python-opencv python-pyside6 python-numpy perl-image-exiftool \
                 darktable enblend-enfuse hugin hdrmerge imagemagick

BASIS: Volledig behoud van v6.1.4 logica voor Tab 1 en 2.
TAB 4: FIX - 'Open Map' en 'Open in Darktable' richten zich nu op het resultaat.
-----------------------
"""

import sys; import os; import shutil; import subprocess; from datetime import datetime; import glob; import time; import tempfile

# --- CONFIGURATIE ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
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

def get_pixmap_robust(path):
    if not path or not os.path.exists(path): return QPixmap()
    try:
        out = subprocess.run(['exiftool', '-S3', '-Orientation', '-n', path], capture_output=True, text=True)
        orient = int(out.stdout.strip()) if out.stdout.strip() else 1
    except: orient = 1
    pix = QPixmap()
    if os.path.splitext(path)[1].upper() == ".DNG":
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
    return pix.transformed(transform, Qt.SmoothTransformation) if not transform.isIdentity() else pix

# --- IMPORTS ---
try:
    import cv2
    import numpy as np
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QCheckBox, QMessageBox, QDoubleSpinBox, QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform
except ImportError as e:
    print(f"Fout: {e}"); sys.exit(1)

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
            self.log.emit("Analyse van metadata...")
            cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True); photo_list = []
            for line in filter(None, result.stdout.splitlines()):
                p = line.split('\t')
                if len(p) < 6 or os.path.splitext(p[0])[1].upper() not in SUPPORTED_EXTS: continue
                dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S")
                model = p[4].strip().replace(' ', '_').replace('/', '-') if p[4] else "Onbekende_Camera"
                iso = int(float(p[5])) if p[5] else 0
                photo_list.append({'name': p[0], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[2]}A{p[3]}", 'model': model, 'iso': iso})
            if not photo_list: self.log.emit("Geen RAW gevonden."); self.finished.emit(); return
            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest_root, exist_ok=True)
            curr = []
            for i, photo in enumerate(photo_list):
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap): curr.append(photo)
                else: self._process_group(curr, dest_root); curr = [photo]
                self.progress.emit(int((i / len(photo_list)) * 100))
            if curr: self._process_group(curr, dest_root)
            self.log.emit("✓ Sorteren voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()
    def _process_group(self, group, dest_root):
        if len(group) < 2: return
        is_hdr = len(set([p['exp'] for p in group])) > 1
        prefix = "Reeks" if is_hdr else "Burst"
        if is_hdr:
            s = self.stack_size
            for i in range(len(group) // s): self._target_folder(group[i*s:(i+1)*s], dest_root, "Reeks")
        else: self._target_folder(group, dest_root, "Burst")
    def _target_folder(self, subset, dest_root, type_prefix):
        self.sequence_count += 1; meta = subset[0]
        iso_label = f"_ISO{meta['iso']}" if meta['iso'] >= 1600 else ""
        target = os.path.join(dest_root, meta['model'], meta['date'], f"{type_prefix}_{self.sequence_count:03d}{iso_label}")
        os.makedirs(target, exist_ok=True)
        for idx, f in enumerate(subset):
            src = os.path.join(self.source_dir, f['name'])
            if os.path.exists(src):
                smart_copy(src, os.path.join(target, f['name']))
                if not (self.keep_first and idx == 0): os.remove(src)

# --- WORKER 2 & 3: HDR / BURST ---
class HdrBurstWorker(BaseWorker):
    def __init__(self, base_dir, mode, method, bit_depth, collect, cleanup, crop_percent, burst_limit=0):
        super().__init__(); self.base_dir, self.mode, self.method, self.bit_depth, self.collect, self.cleanup, self.crop_percent, self.burst_limit = base_dir, mode, method, bit_depth, collect, cleanup, crop_percent, burst_limit
    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = [os.path.join(r, d) for r, ds, fs in os.walk(self.base_dir) for d in ds if d.startswith(prefix)]
            if not subdirs: self.log.emit(f"Geen {self.mode} mappen gevonden."); self.finished.emit(); return

            xmp = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG["DT_XMP_FILE"])
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])

            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: break
                name = os.path.basename(path); is_burst = (self.mode == "BURST")
                self.log.emit(f"<br><b>--- Verwerken: {name} ---</b>")
                cfg = os.path.expanduser("~/.cache/panostack_temp"); (shutil.rmtree(cfg) if os.path.exists(cfg) else None); os.makedirs(cfg)
                if self.mode == "HDR" and self.method in ["hdrmerge", "beide", "both"]:
                    self.log.emit("<i>- Start HDRmerge (DNG)...</i>")
                    res_dng = self._do_hdrmerge(path, name)
                    if res_dng and self.collect:
                        d_dest = os.path.join(coll_root, "DNG"); os.makedirs(d_dest, exist_ok=True)
                        final_dng = os.path.join(d_dest, os.path.basename(res_dng))
                        shutil.move(res_dng, final_dng); self.result_path.emit(final_dng)
                if (self.mode == "HDR" and self.method in ["enfuse", "beide", "both"]) or self.mode == "BURST":
                    res_tif = self._do_enfuse(path, name, cfg, xmp, is_burst)
                    if res_tif and self.collect:
                        subdir_name = "TIFF" if self.mode == "HDR" else "BURST_TIFF"
                        t_dest = os.path.join(coll_root, subdir_name); os.makedirs(t_dest, exist_ok=True)
                        final_tif = os.path.join(t_dest, os.path.basename(res_tif))
                        shutil.move(res_tif, final_tif); self.result_path.emit(final_tif)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
                if self.cleanup: shutil.rmtree(path, ignore_errors=True)
            self.log.emit("<br>✓ Klaar.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _do_enfuse(self, path, name, cfg, xmp, is_burst):
        raws = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS])
        if is_burst and self.burst_limit > 0: raws = raws[:self.burst_limit]
        tmp = os.path.join(path, ".tmp_hdr"); os.makedirs(tmp, exist_ok=True); tifs = []; out_h = os.path.join(path, f"{name}_HDR_{self.bit_depth}bit.tif")
        for idx, r in enumerate(raws):
            if not self._is_running: return None
            self.log.emit(f"   -> RAW {idx+1}/{len(raws)}: {r}")
            out = os.path.join(tmp, f"{os.path.splitext(r)[0]}.tif")
            cmd = ['darktable-cli', os.path.join(path, r), out, '--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl']
            if os.path.exists(xmp): cmd.insert(2, xmp)
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(out): reset_and_copy_metadata(os.path.join(path, r), out); tifs.append(out)
        if len(tifs) >= 2:
            self.log.emit("   -> Beelden uitlijnen...")
            ali = os.path.join(tmp, "ali_"); subprocess.run(['align_image_stack', '-v', '-C', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            alis = sorted(glob.glob(os.path.join(tmp, "ali_*.tif")))
            if alis:
                self.log.emit("   -> Enfuse blending...")
                exp, sat, con = ("1.0", "0", "0") if is_burst else ("1.0", "0.5", "0.5")
                subprocess.run(['enfuse', f'--exposure-weight={exp}', f'--saturation-weight={sat}', f'--contrast-weight={con}', '--output', out_h] + alis, env=ENV_STABLE, stdout=subprocess.DEVNULL)
                if os.path.exists(out_h):
                    if self.crop_percent > 0: subprocess.run(['mogrify', '-shave', f'{self.cp}%x{self.cp}%', out_h], stdout=subprocess.DEVNULL)
                    reset_and_copy_metadata(os.path.join(path, raws[0]), out_h); return out_h
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].upper() in SUPPORTED_EXTS])
        out_f = os.path.join(path, f"{name}_HDR.dng")
        subprocess.run(['hdrmerge', '-o', out_f] + raws, stdout=subprocess.DEVNULL); return out_f if os.path.exists(out_f) else None

# --- WORKER 4: PANORAMA ---
class PanoWorker(BaseWorker):
    def __init__(self, files):
        super().__init__(); self.files = files
    @Slot()
    def run(self):
        try:
            self.log.emit(f"Stitchen van {len(self.files)} beelden...")
            imgs = [cv2.imread(f) for f in self.files if os.path.exists(f)]
            stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
            status, res = stitcher.stitch(imgs)
            if status == cv2.Stitcher_OK:
                out_dir = os.path.join(os.path.dirname(self.files[0]), "Panorama_Resultaten"); os.makedirs(out_dir, exist_ok=True)
                out_p = os.path.join(out_dir, f"Pano_{datetime.now().strftime('%H%M%S')}.tif")
                cv2.imwrite(out_p, res); reset_and_copy_metadata(self.files[0], out_p)
                self.log.emit(f"✓ Panorama klaar!"); self.result_path.emit(out_p)
            else: self.log.emit(f"Fout: Stitching mislukt (Code {status})")
        finally: self.finished.emit()

# --- GUI ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack Flow v9.6.1"); self.setGeometry(100, 100, 1350, 950); self.worker = None; self.thread = None
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Burst"); self.tabs.addTab(self.t4, "4. Panorama")
        self.setup_t1(); self.setup_t2(); self.setup_t3(); self.setup_t4()

    def show_info(self):
        msg = QMessageBox(self); msg.setWindowTitle("Programma Informatie")
        msg.setText("<h3>PanoStack Flow v9.6.1</h3>"
                    "Geoptimaliseerd voor <b>Arch Linux met KDE Plasma</b>.<br><br>"
                    "<b>Arch Linux installatie:</b><br>"
                    "<code>sudo pacman -S python-opencv python-pyside6 python-numpy perl-image-exiftool darktable enblend-enfuse hugin hdrmerge imagemagick</code>")
        msg.exec()

    def setup_t1(self):
        l = QVBoxLayout(self.t1); h_info = QHBoxLayout(); h_info.addStretch(); btn_info = QPushButton("Programma Informatie"); btn_info.clicked.connect(self.show_info); h_info.addWidget(btn_info); l.addLayout(h_info)
        self.s1 = QLineEdit(os.path.expanduser("~")); b1 = QPushButton("..."); b1.clicked.connect(lambda: self.sel(self.s1))
        h1 = QHBoxLayout(); h1.addWidget(QLabel("Bron RAW:")); h1.addWidget(self.s1); h1.addWidget(b1); l.addLayout(h1)
        h_gap = QHBoxLayout(); h_gap.addWidget(QLabel("Maximale pauze tussen foto's in een reeks:")); self.gv = QDoubleSpinBox(); self.gv.setRange(0.1, 10.0); self.gv.setValue(1.0); h_gap.addWidget(self.gv); h_gap.addWidget(QLabel("sec")); l.addLayout(h_gap)
        self.sc = QComboBox(); self.sc.addItems(["3", "5", "7"]); self.sc.setCurrentIndex(1)
        l.addWidget(QLabel("Foto's per HDR-bracket:")); l.addWidget(self.sc)
        self.b1 = QPushButton("Start Sorteren", clicked=self.go1); l.addWidget(self.b1); self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); l.addWidget(self.log1)

    def setup_t2(self): # HDR TAB
        l = QVBoxLayout(self.t2); h2 = QHBoxLayout(); self.s2 = QLineEdit(); b2 = QPushButton("..."); b2.clicked.connect(lambda: self.sel(self.s2))
        h2.addWidget(QLabel("Sorteer map:")); h2.addWidget(self.s2); h2.addWidget(b2); l.addLayout(h2)
        self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); self.m2.setCurrentIndex(2); l.addWidget(QLabel("Methode:")); l.addWidget(self.m2)
        hb = QHBoxLayout(); self.bd2 = QComboBox(); self.bd2.addItems(["8", "16"]); self.bd2.setCurrentIndex(1); self.cp2 = QDoubleSpinBox(); self.cp2.setValue(1.5); hb.addWidget(QLabel("Bit:")); hb.addWidget(self.bd2); hb.addWidget(QLabel("Shave %:")); hb.addWidget(self.cp2); l.addLayout(hb)
        h_btns = QHBoxLayout(); self.b2_start = QPushButton("Start HDR", clicked=lambda: self.go_proc("HDR")); self.b2_stop = QPushButton("Stop", clicked=self.stop_w); l.addLayout(h_btns); h_btns.addWidget(self.b2_start); h_btns.addWidget(self.b2_stop)
        self.p2 = QProgressBar(); l.addWidget(self.p2)
        h_split = QHBoxLayout(); self.log2 = QTextEdit(); self.log2.setReadOnly(True); h_split.addWidget(self.log2, 1); self.scroll2 = QScrollArea(); self.prev2 = QLabel("Preview"); self.prev2.setAlignment(Qt.AlignCenter); self.scroll2.setWidget(self.prev2); self.scroll2.setWidgetResizable(True); h_split.addWidget(self.scroll2, 1); l.addLayout(h_split)

    def setup_t3(self): # BURST TAB
        l = QVBoxLayout(self.t3); h3 = QHBoxLayout(); self.s3 = QLineEdit(); b3 = QPushButton("..."); b3.clicked.connect(lambda: self.sel(self.s3))
        h3.addWidget(QLabel("Sorteer map:")); h3.addWidget(self.s3); h3.addWidget(b3); l.addLayout(h3)
        hb = QHBoxLayout(); self.bd3 = QComboBox(); self.bd3.addItems(["8", "16"]); self.bd3.setCurrentIndex(1); self.cp3 = QDoubleSpinBox(); self.cp3.setValue(1.5); hb.addWidget(QLabel("Bit:")); hb.addWidget(self.bd3); hb.addWidget(QLabel("Shave %:")); hb.addWidget(self.cp3); l.addLayout(hb)
        h_limit = QHBoxLayout(); self.bl3 = QComboBox(); self.bl3.addItems(["Alle", "8", "16"]); self.bl3.setCurrentIndex(0); h_limit.addWidget(QLabel("Max. aantal foto's per Burst:")); h_limit.addWidget(self.bl3); h_limit.addStretch(); l.addLayout(h_limit)
        h_btns = QHBoxLayout(); self.b3_start = QPushButton("Start Burst", clicked=lambda: self.go_proc("BURST")); self.b3_stop = QPushButton("Stop", clicked=self.stop_w); l.addLayout(h_btns); h_btns.addWidget(self.b3_start); h_btns.addWidget(self.b3_stop)
        self.p3 = QProgressBar(); l.addWidget(self.p3)
        h_split = QHBoxLayout(); self.log3 = QTextEdit(); self.log3.setReadOnly(True); h_split.addWidget(self.log3, 1); self.scroll3 = QScrollArea(); self.prev3 = QLabel("Preview"); self.prev3.setAlignment(Qt.AlignCenter); self.scroll3.setWidget(self.prev3); self.scroll3.setWidgetResizable(True); h_split.addWidget(self.scroll3, 1); l.addLayout(h_split)

    def setup_t4(self): # PANO TAB
        l = QVBoxLayout(self.t4); h4 = QHBoxLayout(); self.s4 = QLineEdit(); b4 = QPushButton("..."); b4.clicked.connect(lambda: self.sel(self.s4))
        h4.addWidget(QLabel("Verzamelmap:")); h4.addWidget(self.s4); h4.addWidget(b4); l.addLayout(h4)
        self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(120, 120)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.lw.setFixedHeight(350); l.addWidget(self.lw)
        h_split = QHBoxLayout()
        v_left = QVBoxLayout()
        h_btns = QHBoxLayout(); h_btns.addWidget(QPushButton("Laden", clicked=self.refresh_t4)); self.b4_start = QPushButton("Panorama", clicked=self.go4); h_btns.addWidget(self.b4_start); v_left.addLayout(h_btns)
        v_left.addWidget(QLabel("<b>Voortgang:</b>"))
        self.p4 = QProgressBar(); v_left.addWidget(self.p4)
        self.log4 = QTextEdit(); self.log4.setReadOnly(True); v_left.addWidget(self.log4)
        v_left.addWidget(QPushButton("Open Map", clicked=self.open_pano_folder))
        v_left.addWidget(QPushButton("Open in Darktable", clicked=self.open_dt_pano))
        h_split.addLayout(v_left, 1)
        v_right = QVBoxLayout()
        self.scroll4 = QScrollArea(); self.prev4 = QLabel("Preview"); self.prev4.setAlignment(Qt.AlignCenter); self.scroll4.setWidget(self.prev4); self.scroll4.setWidgetResizable(True); h_split.addLayout(v_right, 1); v_right.addWidget(self.scroll4)
        l.addLayout(h_split)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Map", e.text())
        if d:
            e.setText(d)
            if e == self.s1:
                self.s2.setText(os.path.join(d, CONFIG["SORTED_DIR_NAME"])); self.s3.setText(os.path.join(d, CONFIG["SORTED_DIR_NAME"]))
                self.s4.setText(os.path.join(d, CONFIG["HDR_COLLECT_NAME"]))
            if e == self.s4: self.refresh_t4()

    def refresh_t4(self):
        self.lw.clear(); map_p = self.s4.text()
        if not os.path.exists(map_p): return
        for root, dirs, files in os.walk(map_p):
            for f in sorted(files):
                if f.upper().endswith(('.TIF', '.TIFF', '.JPG')):
                    fp = os.path.join(root, f); it = QListWidgetItem(f); it.setData(Qt.UserRole, fp); it.setIcon(QIcon(get_pixmap_robust(fp).scaled(120, 120, Qt.KeepAspectRatio))); self.lw.addItem(it)

    def open_pano_folder(self):
        # Open de specifieke resultatenmap of de hoofdverzamelmap
        path = ""
        if hasattr(self, 'current_pano_res'): path = os.path.dirname(self.current_pano_res)
        else: path = os.path.join(self.s4.text(), "Panorama_Resultaten")

        if not os.path.exists(path): path = self.s4.text()
        subprocess.run(['xdg-open', path])

    def open_dt_pano(self):
        # Open het LAATST GEMAAKTE panorama in Darktable
        path = getattr(self, 'current_pano_res', "")
        if path and os.path.exists(path):
            subprocess.run(['darktable', '--library', ':memory:', path])
        else:
            self.log4.append("Geen panorama resultaat gevonden om te openen.")

    def stop_w(self): (self.worker.stop() if self.worker else None)
    def go1(self): self._run(SortWorker(self.s1.text(), int(self.sc.currentText()), True, self.gv.value()), self.p1, self.log1, self.b1)
    def go_proc(self, mode):
        if mode == "HDR":
            m_text = self.m2.currentText().lower()
            meth = "beide" if "beide" in m_text else "enfuse" if "enfuse" in m_text else "hdrmerge"
            p, log, b, s, bd, cp, limit = (self.p2, self.log2, self.b2_start, self.s2, self.bd2.currentText(), self.cp2.value(), 0)
        else:
            limit_val = 0 if self.bl3.currentText() == "Alle" else int(self.bl3.currentText())
            p, log, b, s, meth, bd, cp, limit = (self.p3, self.log3, self.b3_start, self.s3, "enfuse", self.bd3.currentText(), self.cp3.value(), limit_val)
        self._run(HdrBurstWorker(s.text(), mode, meth, bd, True, False, cp, limit), p, log, b)
    def go4(self): self._run(PanoWorker([self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]), self.p4, self.log4, self.b4_start)

    def _run(self, w, p, log, b):
        self.worker = w; self.thread = QThread(); b.setEnabled(False); w.moveToThread(self.thread)
        w.finished.connect(lambda: self._end(b)); w.log.connect(log.append); w.progress.connect(p.setValue)
        if hasattr(w, 'result_path'):
            target_p = self.prev2 if (isinstance(w, HdrBurstWorker) and w.mode == "HDR") else self.prev3 if (isinstance(w, HdrBurstWorker) and w.mode == "BURST") else self.prev4
            target_sc = self.scroll2 if (isinstance(w, HdrBurstWorker) and w.mode == "HDR") else self.scroll3 if (isinstance(w, HdrBurstWorker) and w.mode == "BURST") else self.scroll4
            w.result_path.connect(lambda path, tp=target_p, ts=target_sc: self.update_preview(path, tp, ts))
        self.thread.started.connect(w.run); self.thread.start()

    def update_preview(self, path, tp, ts):
        if "Panorama_Resultaten" in path: self.current_pano_res = path
        tp.setPixmap(get_pixmap_robust(path).scaled(ts.width()-20, 2000, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _end(self, b):
        self.thread.quit(); self.thread.wait(); self.worker = None; b.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
