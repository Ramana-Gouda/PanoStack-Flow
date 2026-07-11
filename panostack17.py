#!/usr/bin/env python3
"""
PanoStack Flow (v9.8.36)
-----------------------
FIX: Keuzeknop in Tab 4 wordt nu ook geel bij gebruik van de ververs-knop.
FEAT: Gedetailleerde voortgangsinformatie tijdens Enfuse-bewerking (Tab 2).
FIX: Darktable 5.6+ GUI opent afbeeldingen via library-redirect.
FIX: Witruimte in alle tabs volledig verwijderd (links uitgelijnd).
-----------------------
"""

import sys; import os; import shutil; import subprocess; from datetime import datetime; import glob; import time; import tempfile; import re

# --- CONFIGURATIE ---
CONFIG = {
    "SORTED_DIR_NAME": "geordend_op_reeks",
    "HDR_COLLECT_NAME": "Verzamelde_HDR_bestanden",
    "DT_XMP_FILE": "oppepper.xmp",
}
REQUIRED_TOOLS = ['exiftool', 'darktable-cli', 'align_image_stack', 'enfuse', 'hdrmerge', 'mogrify']
SUPPORTED_EXTS = ['.RW2', '.ARW', '.CR2', '.CR3', '.NEF', '.ORF', '.RAF', '.DNG']
VALID_EXTS = {ext.lower() for ext in SUPPORTED_EXTS}

cores = os.cpu_count() or 2; ENV_STABLE = os.environ.copy(); ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))

# --- HELPERS (ORIGINEEL v9.7.4) ---
def smart_copy(src, dst):
    if sys.platform == "linux":
        try:
            subprocess.run(['cp', '--reflink=auto', src, dst], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except: pass
    try:
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

def get_pixmap_robust(path):
    if not path or not os.path.exists(path): return QPixmap()
    ext = os.path.splitext(path)[1].lower()
    pix = QPixmap()
    if ext == ".dng":
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            try:
                res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
                if res.stdout and len(res.stdout) > 5000:
                    pix.loadFromData(res.stdout); break
            except: continue
    if pix.isNull(): pix.load(path)
    if pix.isNull(): return QPixmap()
    try:
        out = subprocess.run(['exiftool', '-S3', '-Orientation', '-n', path], capture_output=True, text=True)
        orient = int(out.stdout.strip()) if out.stdout.strip() else 1
        if orient in [3, 6, 8]:
            trans = QTransform()
            if orient == 6: trans.rotate(90)
            elif orient == 8: trans.rotate(270)
            elif orient == 3: trans.rotate(180)
            pix = pix.transformed(trans, Qt.SmoothTransformation)
    except: pass
    return pix

# --- IMPORTS ---
try:
    import cv2
    import numpy as np
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox, QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QCursor
except ImportError as e:
    print(f"Fout: {e}"); sys.exit(1)

# --- WORKERS ---
class BaseWorker(QObject):
    finished, progress, log = Signal(), Signal(int), Signal(str)
    result_path = Signal(str)
    def __init__(self): super().__init__(); self._is_running = True
    def stop(self): self._is_running = False

class SortWorker(BaseWorker):
    def __init__(self, source_dir, stack_size, keep_first, max_gap):
        super().__init__(); self.source_dir, self.stack_size, self.keep_first, self.max_gap = source_dir, stack_size, keep_first, max_gap
    @Slot()
    def run(self):
        try:
            self.log.emit("Metadata analyseren...")
            cmd = ['exiftool', '-q', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO', self.source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True); photo_list = []
            for line in filter(None, result.stdout.splitlines()):
                p = line.split('\t')
                ext = os.path.splitext(p[0])[1].lower()
                if len(p) < 6 or ext not in VALID_EXTS: continue
                dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S")
                model = p[4].strip().replace(' ', '_').replace('/', '-') if p[4] else "Onbekende_Camera"
                iso = int(re.sub(r"\D", "", p[5])) if p[5] else 0
                photo_list.append({'name': p[0], 'ts': dt.timestamp(), 'date': dt.strftime('%Y-%m-%d'), 'exp': f"S{p[2]}A{p[3]}", 'model': model, 'iso': iso})
            photo_list.sort(key=lambda x: (x['ts'], x['name']))
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"]); os.makedirs(dest_root, exist_ok=True)
            curr = []; seq = 0
            for i, photo in enumerate(photo_list):
                if not curr or (photo['ts'] - curr[-1]['ts'] <= self.max_gap): curr.append(photo)
                else: seq = self._process_group(curr, dest_root, seq); curr = [photo]
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
                seq += 1; self._target_folder(group[i*self.stack_size:(i+1)*self.stack_size], dest_root, "Reeks", seq)
        else:
            prefix = "Burst" if group[0]['iso'] > 800 else "Serie"
            seq += 1; self._target_folder(group, dest_root, prefix, seq)
        return seq
    def _target_folder(self, subset, dest_root, type_prefix, seq):
        meta = subset[0]; iso_label = f"_ISO{meta['iso']}" if meta['iso'] >= 1600 else ""
        target = os.path.join(dest_root, meta['model'], meta['date'], f"{type_prefix}_{seq:03d}{iso_label}")
        os.makedirs(target, exist_ok=True)
        for idx, f in enumerate(subset):
            src = os.path.join(self.source_dir, f['name'])
            if os.path.exists(src) and smart_copy(src, os.path.join(target, f['name'])):
                if not (self.keep_first and idx == 0): os.remove(src)

class HdrBurstWorker(BaseWorker):
    def __init__(self, base_dir, mode, method, bit_depth, collect, cleanup, crop_percent, burst_limit=0):
        super().__init__(); self.base_dir, self.mode, self.method, self.bit_depth, self.collect, self.cleanup, self.crop_percent, self.burst_limit = base_dir, mode, method, bit_depth, collect, cleanup, crop_percent, burst_limit
    @Slot()
    def run(self):
        try:
            prefix = "Reeks_" if self.mode == "HDR" else "Burst_"
            subdirs = []
            for r, ds, fs in os.walk(self.base_dir):
                for d in ds:
                    if d.startswith(prefix): subdirs.append(os.path.join(r, d))
            if not subdirs:
                self.log.emit(f"Geen mappen gevonden met prefix '{prefix}'"); self.finished.emit(); return
            xmp = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG["DT_XMP_FILE"])
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"])
            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: break
                name = os.path.basename(path); self.log.emit(f"<b>Verwerken: {name}</b>")
                cfg = os.path.expanduser("~/.cache/panostack_temp"); (shutil.rmtree(cfg) if os.path.exists(cfg) else None); os.makedirs(cfg)
                if self.mode == "HDR" and self.method in ["hdrmerge", "beide"]:
                    res_dng = self._do_hdrmerge(path, name)
                    if res_dng and self.collect:
                        d_dest = os.path.join(coll_root, "DNG"); os.makedirs(d_dest, exist_ok=True)
                        final_dng = os.path.join(d_dest, os.path.basename(res_dng)); shutil.move(res_dng, final_dng); self.result_path.emit(final_dng)
                    elif res_dng: self.result_path.emit(res_dng)
                if (self.mode == "HDR" and self.method in ["enfuse", "beide"]) or self.mode == "BURST":
                    res_tif = self._do_enfuse(path, name, cfg, xmp, self.mode == "BURST")
                    if res_tif and self.collect:
                        t_dest = os.path.join(coll_root, "TIFF" if self.mode == "HDR" else "BURST_TIFF"); os.makedirs(t_dest, exist_ok=True)
                        final_tif = os.path.join(t_dest, os.path.basename(res_tif)); shutil.move(res_tif, final_tif); self.result_path.emit(final_tif)
                    elif res_tif: self.result_path.emit(res_tif)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
                if self.cleanup: shutil.rmtree(path, ignore_errors=True)
            self.log.emit("✓ Alles voltooid.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.finished.emit()

    def _do_enfuse(self, path, name, cfg, xmp, is_burst):
        raws = sorted([f for f in os.listdir(path) if os.path.splitext(f)[1].lower() in VALID_EXTS])
        if not raws: return None
        if is_burst and self.burst_limit > 0: raws = raws[:self.burst_limit]
        tmp = os.path.join(path, ".tmp_hdr"); (shutil.rmtree(tmp) if os.path.exists(tmp) else None); os.makedirs(tmp)

        # Voortgangsinformatie over XMP
        sidecar_test = os.path.join(path, raws[0] + ".xmp")
        xmp_info = "Sidecar (.xmp in map)" if os.path.exists(sidecar_test) else (f"Globaal ({CONFIG['DT_XMP_FILE']})" if xmp and os.path.exists(xmp) else "Standaard instellingen")
        self.log.emit(f"  - Bron bewerking: {xmp_info}")

        tifs = []
        for idx, r in enumerate(raws):
            if not self._is_running: return None
            self.log.emit(f"  - Exporteren beeld {idx+1} van {len(raws)} via Darktable...")
            raw_file = os.path.join(path, r); out = os.path.join(tmp, f"img_{idx:03d}.tif"); sidecar = raw_file + ".xmp"
            cmd = ['darktable-cli', raw_file]
            if not os.path.exists(sidecar) and xmp and os.path.exists(xmp): cmd.append(xmp)
            cmd.append(out); cmd.extend(['--core', '--configdir', cfg, '--library', ':memory:', '--disable-opencl'])
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(out): tifs.append(out)

        if len(tifs) < 2: return None
        self.log.emit(f"  - Beelden uitlijnen (align_image_stack)...")
        ali = os.path.join(tmp, "ali_"); subprocess.run(['align_image_stack', '-m', '-a', ali] + tifs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        alis = sorted(glob.glob(os.path.join(tmp, "ali_*.tif"))) or tifs

        self.log.emit(f"  - Samenvoegen via Enfuse...")
        out_h = os.path.join(path, f"{name}_HDR.tif"); exp, sat, con = ("1.0", "0", "0") if is_burst else ("1.0", "0.5", "0.5")
        subprocess.run(['enfuse', f'--exposure-weight={exp}', f'--saturation-weight={sat}', f'--contrast-weight={con}', '--output', out_h] + alis, env=ENV_STABLE, stdout=subprocess.DEVNULL)
        if os.path.exists(out_h):
            if self.crop_percent > 0: subprocess.run(['mogrify', '-shave', f'{self.crop_percent}%x{self.crop_percent}%', out_h], stdout=subprocess.DEVNULL)
            reset_and_copy_metadata(os.path.join(path, raws[0]), out_h); return out_h
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.join(path, f) for f in os.listdir(path) if os.path.splitext(f)[1].lower() in VALID_EXTS])
        if not raws: return None
        out_f = os.path.join(path, f"{name}_HDR.dng")
        self.log.emit("  - Samenvoegen via HDRmerge (DNG)...")
        subprocess.run(['hdrmerge', '-b', '16', '-o', out_f] + raws, stdout=subprocess.DEVNULL)
        if os.path.exists(out_f): copy_metadata_full(raws[0], out_f); return out_f
        return None

class PanoWorker(BaseWorker):
    def __init__(self, files):
        super().__init__(); self.files = files
    @Slot()
    def run(self):
        temp_dir = tempfile.mkdtemp()
        try:
            self.log.emit(f"Stitchen van {len(self.files)} beelden...")
            imgs = []
            for i, f in enumerate(self.files):
                if not os.path.exists(f): continue
                if f.lower().endswith('.dng'):
                    self.log.emit(f"  - Conversie DNG {i+1} naar TIFF...")
                    tmp_tif = os.path.join(temp_dir, f"tmp_{i}.tif")
                    subprocess.run(['darktable-cli', f, tmp_tif, '--library', ':memory:', '--disable-opencl'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    img = cv2.imread(tmp_tif)
                else: img = cv2.imread(f)
                if img is not None: imgs.append(img)
            if len(imgs) < 2: self.log.emit("Fout: Te weinig beelden geladen."); return
            status, res = cv2.Stitcher_create(cv2.Stitcher_PANORAMA).stitch(imgs)
            if status == cv2.Stitcher_OK:
                out_dir = os.path.join(os.path.dirname(self.files[0]), "Panorama_Resultaten"); os.makedirs(out_dir, exist_ok=True)
                out_p = os.path.join(out_dir, f"Pano_{datetime.now().strftime('%H%M%S')}.tif")
                cv2.imwrite(out_p, res); reset_and_copy_metadata(self.files[0], out_p)
                self.log.emit(f"✓ Klaar: {os.path.basename(out_p)}"); self.result_path.emit(out_p)
            else: self.log.emit(f"Fout bij stitchen: {status}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True); self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PanoStack Flow v9.8.36"); self.setGeometry(100, 100, 1400, 950)
        self.worker = None; self.thread = None; self.active_preview_path = ""
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.t1, self.t2, self.t3, self.t4 = QWidget(), QWidget(), QWidget(), QWidget()
        self.tabs.addTab(self.t1, "1. Sorteer"); self.tabs.addTab(self.t2, "2. HDR"); self.tabs.addTab(self.t3, "3. Burst"); self.tabs.addTab(self.t4, "4. Panorama")
        self.setup_t1(); self.setup_t2(); self.setup_t3(); self.setup_t4()

    def setup_t1(self):
        l = QVBoxLayout(self.t1); self.s1 = QLineEdit(os.path.expanduser("~"))
        h_src = QHBoxLayout(); h_src.addWidget(QLabel("Bron RAW:")); h_src.addWidget(self.s1)
        b1_br = QPushButton("..."); b1_br.setFixedWidth(40); b1_br.clicked.connect(lambda: self.sel(self.s1)); h_src.addWidget(b1_br)
        self.btn_i = QPushButton("ⓘ", clicked=self.show_info); self.btn_i.setFixedWidth(40); self.btn_i.setStyleSheet("background-color: #2a5a8a; color: white;")
        h_src.addWidget(self.btn_i); l.addLayout(h_src)
        h_all = QHBoxLayout(); h_all.setAlignment(Qt.AlignLeft); h_all.setSpacing(10)
        h_all.addWidget(QLabel("Pauze (sec):")); self.gv = QDoubleSpinBox(); self.gv.setValue(1.0); self.gv.setFixedWidth(60); h_all.addWidget(self.gv)
        h_all.addWidget(QLabel("Bracket:")); self.sc = QComboBox(); self.sc.addItems(["3","5","7"]); self.sc.setCurrentIndex(1); self.sc.setFixedWidth(50); h_all.addWidget(self.sc)
        self.b1 = QPushButton("Start Sorteren", clicked=self.go1); self.b1.setStyleSheet("font-weight: bold;"); self.b1.setFixedWidth(150); h_all.addWidget(self.b1); h_all.addStretch(); l.addLayout(h_all)
        self.p1 = QProgressBar(); l.addWidget(self.p1); self.log1 = QTextEdit(); l.addWidget(self.log1)

    def setup_t2(self):
        l = QVBoxLayout(self.t2); self.s2 = QLineEdit()
        h2 = QHBoxLayout(); h2.addWidget(QLabel("Map:")); h2.addWidget(self.s2); b2 = QPushButton("..."); b2.clicked.connect(lambda: self.sel(self.s2)); h2.addWidget(b2); l.addLayout(h2)
        h_opts = QHBoxLayout(); h_opts.setAlignment(Qt.AlignLeft); h_opts.setSpacing(10); self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Enfuse (TIFF) + HDRmerge (DNG)"])
        self.m2.currentIndexChanged.connect(self.sync_t2_ui); h_opts.addWidget(self.m2); h_opts.addWidget(QLabel("Bit:")); self.bd2 = QComboBox(); self.bd2.addItems(["8","16"]); self.bd2.setFixedWidth(50); h_opts.addWidget(self.bd2); h_opts.addWidget(QLabel("Randjes (%):")); self.cp2 = QDoubleSpinBox(); self.cp2.setValue(1.5); self.cp2.setFixedWidth(60); h_opts.addWidget(self.cp2); h_opts.addStretch(); l.addLayout(h_opts)
        h_btns = QHBoxLayout(); self.b2 = QPushButton("Start HDR Verwerking", clicked=lambda: self.go_proc("HDR")); self.stop2 = QPushButton("Stop", clicked=self.stop_proc); self.stop2.setEnabled(False); h_btns.addWidget(self.b2); h_btns.addWidget(self.stop2); h_btns.addStretch(); l.addLayout(h_btns)
        self.p2 = QProgressBar(); l.addWidget(self.p2)
        h_split = QHBoxLayout(); self.log2 = QTextEdit(); self.scroll2 = QScrollArea(); self.prev2 = QLabel(); self.prev2.setAlignment(Qt.AlignCenter); self.scroll2.setWidget(self.prev2); self.scroll2.setWidgetResizable(True); h_split.addWidget(self.log2, 1); h_split.addWidget(self.scroll2, 1); l.addLayout(h_split)

    def setup_t3(self):
        l = QVBoxLayout(self.t3); self.s3 = QLineEdit()
        h3 = QHBoxLayout(); h3.addWidget(QLabel("Map:")); h3.addWidget(self.s3); b3 = QPushButton("..."); b3.clicked.connect(lambda: self.sel(self.s3)); h3.addWidget(b3); l.addLayout(h3)
        hb = QHBoxLayout(); hb.setAlignment(Qt.AlignLeft); hb.setSpacing(10); hb.addWidget(QLabel("Stack limiet:")); self.sl3 = QComboBox(); self.sl3.addItems(["8","16"]); self.sl3.setFixedWidth(60); hb.addWidget(self.sl3)
        hb.addWidget(QLabel("Randjes (%):")); self.cp3 = QDoubleSpinBox(); self.cp3.setValue(1.5); self.cp3.setFixedWidth(60); hb.addWidget(self.cp3)
        self.b3 = QPushButton("Start Burst Verwerking", clicked=lambda: self.go_proc("BURST")); self.b3.setFixedWidth(150); hb.addWidget(self.b3)
        self.stop3 = QPushButton("Stop", clicked=self.stop_proc); self.stop3.setEnabled(False); self.stop3.setFixedWidth(60); hb.addWidget(self.stop3); hb.addStretch(); l.addLayout(hb)
        self.p3 = QProgressBar(); l.addWidget(self.p3); h_split = QHBoxLayout(); self.log3 = QTextEdit(); self.scroll3 = QScrollArea(); self.prev3 = QLabel(); self.prev3.setAlignment(Qt.AlignCenter)
        self.scroll3.setWidget(self.prev3); self.scroll3.setWidgetResizable(True); h_split.addWidget(self.log3, 1); h_split.addWidget(self.scroll3, 1); l.addLayout(h_split)

    def setup_t4(self):
        l = QVBoxLayout(self.t4); self.s4 = QLineEdit()
        h4 = QHBoxLayout(); h4.addWidget(QLabel("Verzamelmap:")); h4.addWidget(self.s4); b4 = QPushButton("..."); b4.clicked.connect(lambda: self.sel(self.s4)); h4.addWidget(b4); l.addLayout(h4)
        h_f = QHBoxLayout(); h_f.addWidget(QLabel("Bron type:")); self.f4 = QComboBox(); self.f4.addItems(["TIFF/JPG Bestanden", "DNG Bestanden"]); self.f4.currentIndexChanged.connect(self.on_filter_changed); h_f.addWidget(self.f4); h_f.addStretch(); l.addLayout(h_f)
        self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setIconSize(QSize(120, 120)); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.lw.setFixedHeight(450); l.addWidget(self.lw)
        h_bt = QHBoxLayout(); h_bt.setAlignment(Qt.AlignLeft); h_bt.setSpacing(10); h_bt.addWidget(QPushButton("Laden / Verversen", clicked=self.on_refresh_clicked)); self.b4_stitch = QPushButton("Start Panorama", clicked=self.go4); self.b4_stitch.setStyleSheet("font-weight: bold;"); h_bt.addWidget(self.b4_stitch); h_bt.addStretch(); l.addLayout(h_bt)
        h_s = QHBoxLayout(); v_l = QVBoxLayout(); self.p4 = QProgressBar(); self.log4 = QTextEdit(); v_l.addWidget(self.p4); v_l.addWidget(self.log4); h_s.addLayout(v_l, 1)
        v_r = QVBoxLayout(); self.scroll4 = QScrollArea(); self.prev4 = QLabel(); self.prev4.setAlignment(Qt.AlignCenter); self.scroll4.setWidget(self.prev4); self.scroll4.setWidgetResizable(True); v_r.addWidget(self.scroll4)
        self.btn_dt = QPushButton("Preview openen in Darktable (database-vrij)", clicked=self.open_dt_from_preview); v_r.addWidget(self.btn_dt); h_s.addLayout(v_r, 2); l.addLayout(h_s)

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Selecteer Map", e.text())
        if d:
            e.setText(d)
            if e == self.s1: self.s2.setText(os.path.join(d, CONFIG["SORTED_DIR_NAME"])); self.s3.setText(os.path.join(d, CONFIG["SORTED_DIR_NAME"])); self.s4.setText(os.path.join(d, CONFIG["HDR_COLLECT_NAME"]))
            if e == self.s4: self.on_refresh_clicked()

    def show_info(self):
        msg = QMessageBox(self); msg.setWindowTitle("Informatie"); msg.setTextFormat(Qt.RichText)
        msg.setText("<h3>Gebruik</h3><ol><li><b>Sorteer:</b> Groepeert foto's (ISO > 800 voor Burst).</li><li><b>HDR/Burst:</b> Verwerkt mappen.</li><li><b>Panorama:</b> Stitch beelden.</li></ol><h3>XMP</h3><ul><li>Sidecar <i>.xmp</i> krijgt voorrang.</li><li><i>oppepper.xmp</i> wordt als tweede keuze gebruikt.</li></ul>"); msg.exec()

    def sync_t2_ui(self):
        method = self.m2.currentText().lower(); is_dng = "hdrmerge" in method and "+" not in method
        if is_dng: self.bd2.setCurrentText("16"); self.bd2.setEnabled(False)
        else: self.bd2.setEnabled(True)

    def on_refresh_clicked(self):
        self.f4.setStyleSheet("background-color: #ffff00; color: black;")
        QApplication.processEvents()
        self.refresh_t4(force_clear=True)
        self.f4.setStyleSheet("")
        QApplication.processEvents()

    def on_filter_changed(self):
        self.f4.setStyleSheet("background-color: #ffff00; color: black;")
        QApplication.processEvents()
        self.refresh_t4(force_clear=True)
        self.f4.setStyleSheet("")
        QApplication.processEvents()

    def refresh_t4(self, select_file=None, force_clear=False):
        map_p = self.s4.text()
        if not os.path.exists(map_p): return
        choice = self.f4.currentIndex(); valid_exts = ('.tif', '.tiff', '.jpg') if choice == 0 else ('.dng',)
        if force_clear: self.lw.clear()
        existing_paths = [self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count())]
        for root, ds, fs in os.walk(map_p):
            for f in sorted(fs):
                if f.lower().endswith(valid_exts):
                    fp = os.path.normpath(os.path.abspath(os.path.realpath(os.path.join(root, f))))
                    if fp not in existing_paths:
                        it = QListWidgetItem(f); it.setData(Qt.UserRole, fp); it.setIcon(QIcon(get_pixmap_robust(fp).scaled(120, 120, Qt.KeepAspectRatio))); self.lw.addItem(it)
                    if select_file and fp == os.path.normpath(os.path.abspath(os.path.realpath(select_file))):
                        for i in range(self.lw.count()):
                            if self.lw.item(i).data(Qt.UserRole) == fp:
                                self.lw.item(i).setSelected(True); self.lw.scrollToItem(self.lw.item(i))

    def open_dt_from_preview(self):
        if self.active_preview_path:
            full_path = os.path.abspath(os.path.expanduser(self.active_preview_path))
            if os.path.exists(full_path):
                subprocess.Popen(['darktable', '--library', ':memory:', full_path], start_new_session=True)
            else: QMessageBox.warning(self, "Fout", f"Bestand niet gevonden:\n{full_path}")

    def stop_proc(self):
        if self.worker: self.worker.stop()

    def go1(self): self._run(SortWorker(self.s1.text(), int(self.sc.currentText()), True, self.gv.value()), self.p1, self.log1, self.b1)
    def go_proc(self, mode):
        if mode == "HDR":
            m = self.m2.currentText().lower(); meth = "beide" if "+" in m else "enfuse" if "enfuse" in m else "hdrmerge"
            self._run(HdrBurstWorker(self.s2.text(), "HDR", meth, self.bd2.currentText(), True, False, self.cp2.value()), self.p2, self.log2, self.b2)
        else:
            limit = int(self.sl3.currentText())
            self._run(HdrBurstWorker(self.s3.text(), "BURST", "enfuse", "16", True, False, self.cp3.value(), burst_limit=limit), self.p3, self.log3, self.b3)
    def go4(self): self._run(PanoWorker([self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]), self.p4, self.log4, self.b4_stitch)

    def _run(self, w, p, log, b):
        self.worker = w; self.thread = QThread(); b.setEnabled(False)
        if hasattr(self, 'stop2'): self.stop2.setEnabled(True)
        if hasattr(self, 'stop3'): self.stop3.setEnabled(True)
        w.moveToThread(self.thread); w.log.connect(log.append); w.progress.connect(p.setValue)
        w.finished.connect(lambda: (self.thread.quit(), self.thread.wait(), b.setEnabled(True), (self.stop2.setEnabled(False) if hasattr(self, 'stop2') else None), (self.stop3.setEnabled(False) if hasattr(self, 'stop3') else None)))
        if hasattr(w, 'result_path'):
            if isinstance(w, PanoWorker): w.result_path.connect(lambda path: (self.refresh_t4(path), self.show_prev(path, self.prev4, self.scroll4)))
            else:
                tp = self.prev2 if (isinstance(w, HdrBurstWorker) and w.mode == "HDR") else self.prev3 if (isinstance(w, HdrBurstWorker) and w.mode == "BURST") else self.prev4
                ts = self.scroll2 if (isinstance(w, HdrBurstWorker) and w.mode == "HDR") else self.scroll3 if (isinstance(w, HdrBurstWorker) and w.mode == "BURST") else self.scroll4
                w.result_path.connect(lambda path, t_p=tp, t_s=ts: self.show_prev(path, t_p, t_s))
        self.thread.started.connect(w.run); self.thread.start()

    def show_prev(self, path, tp, ts):
        self.active_preview_path = path; pix = get_pixmap_robust(path)
        if not pix.isNull():
            w = max(ts.width() - 20, 1000); tp.setPixmap(pix.scaled(w, 4000, Qt.KeepAspectRatio, Qt.SmoothTransformation))

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec())
