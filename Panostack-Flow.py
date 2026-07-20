#!/usr/bin/env python3
"""
PanoStack Flow (v2.0.5)
- TOEGEVOEGD: Automatische controle van afhankelijke software bij opstarten.
- BEHOUDEN: Selectie vrijgeven in Tab 4 na panorama.
- BEHOUDEN: XMP selectie voor Panorama (beperkt tot DNG).
- BEHOUDEN: Alle v2.0.x fixes (Home-Isolatie, DT 5.6.0 compatibiliteit).
"""

import sys, os, shutil, subprocess, glob, time, tempfile, re, gc, traceback, signal
from datetime import datetime

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
ENV_STABLE = os.environ.copy()
ENV_STABLE["OMP_NUM_THREADS"] = str(max(1, cores - 1))
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# --- DEPENDENCY CHECK ---
def check_dependencies():
    """Controleert of alle externe commando's beschikbaar zijn."""
    deps = {
        "exiftool": "Nodig voor het uitlezen van metadata (sorteren).",
        "darktable-cli": "Nodig voor RAW-ontwikkeling.",
        "enfuse": "Nodig voor HDR/Burst samenvoeging.",
        "align_image_stack": "Nodig voor het uitlijnen van foto's.",
        "hdrmerge": "Nodig voor het maken van DNG HDR's."
    }
    missing = []
    for cmd, desc in deps.items():
        if shutil.which(cmd) is None:
            missing.append(f"• <b>{cmd}</b>: {desc}")
    return missing

# --- IMPORTS ---
try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar, QTextEdit, QTabWidget, QComboBox, QMessageBox, QDoubleSpinBox, QListWidget, QAbstractItemView, QListWidgetItem, QScrollArea, QSplitter)
    from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QSize
    from PySide6.QtGui import QIcon, QPixmap, QTransform, QImage
    import cv2
    import numpy as np
except ImportError as e:
    print(f"Fout bij laden modules: {e}")
    sys.exit(1)

# --- HELPERS ---
def get_image_robust(path):
    if not path or not os.path.exists(path): return QImage()
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS or ext == ".dng":
        for tag in ['-PreviewImage', '-JpgFromRaw', '-ThumbnailImage']:
            try:
                res = subprocess.run(['exiftool', '-b', tag, path], capture_output=True)
                if res.stdout and len(res.stdout) > 5000:
                    img = QImage()
                    if img.loadFromData(res.stdout): return img
            except: continue
    if ext in ['.tif', '.tiff']:
        try:
            cv_img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if cv_img is not None:
                if len(cv_img.shape) == 3: cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                if cv_img.dtype == np.uint16: cv_img = (cv_img / 256).astype(np.uint8)
                h, w, ch = cv_img.shape
                return QImage(cv_img.data, w, h, ch * w, QImage.Format_RGB888).copy()
        except: pass
    img = QImage(); img.load(path); return img

def find_best_xmp(folder_path):
    check_path = folder_path
    for _ in range(3):
        local_xmps = glob.glob(os.path.join(check_path, "*.xmp"))
        if local_xmps: return sorted(local_xmps, key=len)[0]
        parent = os.path.dirname(check_path); check_path = parent
    global_xmp = os.path.join(SCRIPT_DIR, CONFIG["DT_XMP_FILE"])
    return global_xmp if os.path.exists(global_xmp) else None

def parse_exp(val):
    try:
        if '/' in val:
            n, d = val.split('/')
            return float(n) / float(d)
        return float(val)
    except: return 0.0

# --- WORKERS ---
class BaseWorker(QObject):
    finished, progress, log, result_path = Signal(), Signal(int), Signal(str), Signal(str)
    def __init__(self):
        super().__init__()
        self._is_running = True
        self._proc = None
        self._tmp_home = tempfile.mkdtemp(prefix="ps_home_")

    def stop(self):
        self._is_running = False
        if self._proc:
            try:
                if sys.platform == "win32":
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(self._proc.pid)], capture_output=True)
                else:
                    self._proc.terminate()
                    subprocess.run(['pkill', '-f', 'darktable-cli'], capture_output=True)
            except: pass

    def run_command(self, cmd, env=None):
        if not self._is_running: return -1
        custom_env = env or ENV_STABLE.copy()
        if cmd[0] == 'darktable-cli':
            custom_env[("USERPROFILE" if sys.platform == "win32" else "HOME")] = self._tmp_home
            if sys.platform == "win32": custom_env["LOCALAPPDATA"] = self._tmp_home

        self.log.emit(f"<code style='color: #05B8CC;'>Exec: {' '.join(str(x) for x in cmd[:6])}...</code>")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=custom_env)
        while True:
            if not self._is_running:
                try: self._proc.terminate(); break
                except: break
            line = self._proc.stdout.readline()
            if not line and self._proc.poll() is not None: break
            if line: self.log.emit(f"<small style='color: #666;'>{line.strip()}</small>")
        return self._proc.returncode

    def cleanup(self):
        try: shutil.rmtree(self._tmp_home, ignore_errors=True)
        except: pass

class ThumbnailWorker(QObject):
    finished, progress, thumb_ready = Signal(), Signal(int), Signal(str, str, QImage)
    def __init__(self, directory, extensions, only_series=False):
        super().__init__(); self.directory, self.extensions, self.only_series = directory, extensions, only_series
    def run(self):
        if not os.path.exists(self.directory): self.finished.emit(); return
        files = []
        ext_tuple = tuple(e.lower() for e in self.extensions)
        for root, _, filenames in os.walk(self.directory):
            if self.only_series and not os.path.basename(root).startswith("Serie_"): continue
            for f in filenames:
                if f.lower().endswith(ext_tuple): files.append(os.path.join(root, f))
        files = sorted(list(set(files)))
        for i, fp in enumerate(files):
            img = get_image_robust(fp)
            if not img.isNull(): self.thumb_ready.emit(os.path.basename(fp), fp, img)
            self.progress.emit(int(((i + 1) / (len(files) or 1)) * 100))
        self.finished.emit()

class SortWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, source_dir, max_gap):
        super().__init__(); self.source_dir = source_dir; self.max_gap = max_gap
    @Slot()
    def run(self):
        try:
            self.log.emit("<b style='color: #05B8CC;'>Sorteer-proces gestart...</b>")
            self.log.emit(f"Bron: {self.source_dir}")
            self.log.emit(f"Maximale pauze tussen foto's: {self.max_gap} seconden.")
            self.log.emit("<i>Info: Bestanden worden gegroepeerd op cameramodel en tijdstip. Belichtingsverschillen bepalen het type (HDR/Burst/Serie).</i><br>")

            all_files = [f for f in os.listdir(self.source_dir) if any(f.lower().endswith(ext) for ext in VALID_EXTS)]
            photos = []
            cmd = ['exiftool', '-q', '-f', '-S3', '-T', '-n', '-FileName', '-DateTimeOriginal', '-ExposureTime', '-FNumber', '-Model', '-ISO', '-FileSize#', '-SubSecTimeOriginal']
            for i in range(0, len(all_files), 40):
                if not self._is_running: break
                batch = all_files[i:i + 40]
                res = subprocess.run(cmd + batch, capture_output=True, text=True, cwd=self.source_dir)
                for line in filter(None, res.stdout.splitlines()):
                    p = line.split('\t')
                    if len(p) < 2: continue
                    try:
                        dt = datetime.strptime(p[1], "%Y:%m:%d %H:%M:%S")
                        subsec = float(f"0.{p[7]}") if (len(p) > 7 and p[7].isdigit()) else 0.0
                        photos.append({'name': p[0], 'ts': dt.timestamp() + subsec, 'date': dt.strftime('%Y-%m-%d'), 'raw_exp': p[2] if len(p)>2 else "0", 'model': p[4].strip().replace(' ','_') if len(p)>4 else "Onbekend", 'iso': int(re.sub(r"\D", "", p[5])) if (len(p)>5 and p[5] != "-") else 0})
                    except: continue
                self.sub_progress.emit(int(((i + len(batch)) / len(all_files)) * 100))

            photos.sort(key=lambda x: (x['model'], x['ts']))
            dest_root = os.path.join(self.source_dir, CONFIG["SORTED_DIR_NAME"])
            curr, seq, stopped = [], 0, False

            for idx, p in enumerate(photos):
                if not self._is_running: stopped = True; break
                if not curr or (p['ts'] - curr[-1]['ts'] <= self.max_gap and p['model'] == curr[-1]['model']):
                    curr.append(p)
                else:
                    self._process_group(curr, dest_root, seq); seq += 1; curr = [p]
                self.progress.emit(int(((idx + 1) / len(photos)) * 100))

            if not stopped:
                if curr: self._process_group(curr, dest_root, seq)
                self.log.emit("<br><b style='color: #05B8CC;'>✓ Sorteren succesvol voltooid.</b>")
            else: self.log.emit("<br><b style='color: red;'>STOP GEACTIVEERD.</b>")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.cleanup(); self.finished.emit()

    def _process_group(self, group, dest_root, seq):
        if len(group) < 2: return
        exp_vals = [parse_exp(p['raw_exp']) for p in group]
        type_p = "Reeks" if (max(exp_vals) / (min(exp_vals) or 1)) > 1.15 else ("Burst" if group[0]['iso'] > 800 else "Serie")
        target_path = os.path.join(dest_root, group[0]['model'], group[0]['date'], f"{type_p}_{seq+1:03d}")
        os.makedirs(target_path, exist_ok=True)
        for idx, f in enumerate(group):
            src, dst = os.path.join(self.source_dir, f['name']), os.path.join(target_path, f['name'])
            if sys.platform == "linux":
                subprocess.run(['cp', '--reflink=auto', src, dst], capture_output=True)
            else: shutil.copy2(src, dst)
            if idx > 0:
                try: os.remove(src)
                except: pass
        self.result_path.emit(os.path.join(target_path, group[0]['name']))

class HdrBurstWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, base_dir, mode, method, bit_depth, burst_limit=0):
        super().__init__(); self.base_dir, self.mode, self.method, self.bit_depth, self.burst_limit = base_dir, mode, method.lower(), bit_depth, burst_limit
    @Slot()
    def run(self):
        try:
            if self.mode == "HDR": subdirs = [os.path.join(r, d) for r, ds, _ in os.walk(self.base_dir) for d in ds if d.startswith("Reeks_")]
            else: subdirs = [os.path.join(r, d) for r, ds, _ in os.walk(self.base_dir) for d in ds if d.startswith("Burst_") or d.startswith("Serie_")]
            if not subdirs: self.log.emit("Geen mappen gevonden."); self.finished.emit(); return
            coll_root = os.path.join(os.path.dirname(self.base_dir.rstrip(os.sep)), CONFIG["HDR_COLLECT_NAME"]); stopped = False
            for i, path in enumerate(sorted(subdirs)):
                if not self._is_running: stopped = True; break
                name, xmp = os.path.basename(path), find_best_xmp(path)
                if self.mode == "HDR" and ("hdrmerge" in self.method or "beide" in self.method):
                    res = self._do_hdrmerge(path, name)
                    if res: os.makedirs(os.path.join(coll_root, "DNG"), exist_ok=True); shutil.copy2(res, os.path.join(coll_root, "DNG", os.path.basename(res))); self.result_path.emit(res)
                if not self._is_running: stopped = True; break
                if (self.mode == "HDR" and ("enfuse" in self.method or "beide" in self.method)) or self.mode == "BURST":
                    res = self._do_enfuse(path, name, xmp)
                    if res: os.makedirs(os.path.join(coll_root, "TIFF"), exist_ok=True); shutil.copy2(res, os.path.join(coll_root, "TIFF", os.path.basename(res))); self.result_path.emit(res)
                self.progress.emit(int(((i + 1) / len(subdirs)) * 100))
            if stopped: self.log.emit("<br><b style='color: red;'>STOP GEACTIVEERD.</b>")
            else: self.log.emit("<br>✓ Klaar.")
        except Exception as e: self.log.emit(f"Fout: {e}")
        finally: self.cleanup(); self.finished.emit()

    def _do_enfuse(self, path, name, xmp):
        all_f = sorted([f for f in os.listdir(path) if any(f.lower().endswith(ext) for ext in RAW_EXTS) and "_HDR" not in f])
        files = all_f[:self.burst_limit] if (self.mode == "BURST" and self.burst_limit > 0) else all_f
        if len(files) < 2: return None
        tmp = os.path.join(path, ".tmp_p"); os.makedirs(tmp, exist_ok=True); tifs = []
        for idx, f in enumerate(files):
            if not self._is_running: return None
            src, out = os.path.join(path, f), os.path.join(tmp, f"img_{idx:03d}.tif")
            if os.path.exists(out): os.remove(out)
            cmd = ['darktable-cli', os.path.abspath(src)]
            if xmp: cmd.append(os.path.abspath(xmp))
            cmd.extend([os.path.abspath(out), '--core', '--library', ':memory:', '--disable-opencl', '--conf', 'plugins/imageio/format/tiff/out_color_profile=1', '--conf', f'plugins/imageio/format/tiff/bpp={self.bit_depth}', '--conf', 'plugins/imageio/format/tiff/alpha=0', '--conf', 'plugins/imageio/format/tiff/compression=0'])
            if self.run_command(cmd) != 0: return None
            if os.path.exists(out): tifs.append(out)
            self.sub_progress.emit(int(((idx+1) / (len(files) + 1)) * 100))
        if len(tifs) < 2: return None
        self.run_command(['align_image_stack', '-m', '-a', os.path.join(tmp, "a_"), '-c', '15', '-z', '-x', '-y'] + tifs)
        alis = sorted(glob.glob(os.path.join(tmp, "a_*.tif"))) or tifs
        out_h = os.path.join(path, f"{name}_HDR.tif")
        if os.path.exists(out_h): os.remove(out_h)
        self.run_command(['enfuse', f'--depth={self.bit_depth}', '--exposure-weight=1.0', '--output', out_h] + alis)
        if os.path.exists(out_h): shutil.rmtree(tmp, ignore_errors=True); return out_h
        return None

    def _do_hdrmerge(self, path, name):
        raws = sorted([os.path.abspath(os.path.join(path, f)) for f in os.listdir(path) if any(f.lower().endswith(ext) for ext in RAW_EXTS) and "_HDR" not in f])
        if len(raws) < 2: return None
        out = os.path.abspath(os.path.join(path, f"{name}_HDR.dng"))
        if os.path.exists(out): os.remove(out)
        self.run_command(['hdrmerge', '-b', '16', '-o', out] + raws)
        return out if os.path.exists(out) else None

class PanoWorker(BaseWorker):
    sub_progress = Signal(int)
    def __init__(self, files, xmp_path=None):
        super().__init__()
        self.files = files
        self.xmp_path = xmp_path
    @Slot()
    def run(self):
        tmp_dir = tempfile.mkdtemp(); imgs = []; stopped = False
        try:
            for i, f in enumerate(self.files):
                if not self._is_running: stopped = True; break
                t = os.path.join(tmp_dir, f"p_{i}.tif")
                if os.path.exists(t): os.remove(t)

                ext = os.path.splitext(f)[1].lower()
                cmd = ['darktable-cli', os.path.abspath(f)]
                if ext == ".dng" and self.xmp_path and os.path.exists(self.xmp_path):
                    cmd.append(os.path.abspath(self.xmp_path))

                cmd.extend([os.path.abspath(t), '--core', '--library', ':memory:', '--conf', 'plugins/imageio/format/tiff/out_color_profile=1', '--conf', 'plugins/imageio/format/tiff/alpha=0', '--conf', 'plugins/imageio/format/tiff/bpp=8'])
                self.run_command(cmd)
                img = cv2.imread(t)
                if img is not None: imgs.append(img)
                self.sub_progress.emit(int(((i + 1) / len(self.files)) * 100))
            if not stopped and len(imgs) > 1:
                stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                status, res = stitcher.stitch(imgs)
                if status == cv2.Stitcher_OK:
                    out = os.path.join(os.path.dirname(self.files[0]), f"Pano_{datetime.now().strftime('%H%M%S')}.tif")
                    if os.path.exists(out): os.remove(out)
                    cv2.imwrite(out, res); self.result_path.emit(out)
            elif stopped: self.log.emit("<br><b style='color: red;'>STOP GEACTIVEERD.</b>")
        finally:
            time.sleep(0.5); shutil.rmtree(tmp_dir, ignore_errors=True)
            self.cleanup(); self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PanoStack Flow v2.0.5")
        self.resize(1300, 900); self.worker = None; self.thread = None; self.lt = None; self.last_result_path = None
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs); self.setup_ui()

    def setup_ui(self):
        # TAB 1: Sorteer
        self.t1 = QWidget(); self.tabs.addTab(self.t1, "1. Sorteer"); l1 = QVBoxLayout(self.t1)
        h1 = QHBoxLayout(); self.s1 = QLineEdit(os.path.expanduser("~")); h1.addWidget(QLabel("Bron:")); h1.addWidget(self.s1); b1_sel = QPushButton("..."); b1_sel.clicked.connect(lambda: self.sel(self.s1)); h1.addWidget(b1_sel)
        b1_i = QPushButton("ⓘ"); b1_i.setFixedWidth(30); b1_i.clicked.connect(self.show_info); h1.addWidget(b1_i); l1.addLayout(h1)
        hc = QHBoxLayout(); hc.addWidget(QLabel("Pauze (sec):")); self.gv = QDoubleSpinBox(); self.gv.setValue(1.0); self.gv.setRange(0.1, 60.0); hc.addWidget(self.gv); hc.addStretch(); l1.addLayout(hc)
        self.b1 = QPushButton("Start Sorteren"); self.b1.clicked.connect(self.go1); l1.addWidget(self.b1); self.p1 = self._make_pb(); l1.addWidget(self.p1)
        sp1 = QSplitter(Qt.Horizontal); self.log1 = QTextEdit(); self.prev1 = QLabel(); self.prev1.setAlignment(Qt.AlignCenter); sc1 = QScrollArea(); sc1.setWidget(self.prev1); sc1.setWidgetResizable(True); sp1.addWidget(self.log1); sp1.addWidget(sc1); l1.addWidget(sp1); sp1.setSizes([300, 900])

        # TAB 2: HDR
        self.t2 = QWidget(); self.tabs.addTab(self.t2, "2. HDR"); l2 = QVBoxLayout(self.t2)
        h2 = QHBoxLayout(); self.s2 = QLineEdit(); h2.addWidget(QLabel("Map:")); h2.addWidget(self.s2); b2_sel = QPushButton("..."); b2_sel.clicked.connect(lambda: self.sel(self.s2)); h2.addWidget(b2_sel); l2.addLayout(h2)
        ho = QHBoxLayout(); self.m2 = QComboBox(); self.m2.addItems(["Enfuse (TIFF)", "HDRmerge (DNG)", "Beide"]); ho.addWidget(self.m2); self.bd2_lab = QLabel("Bits:"); ho.addWidget(self.bd2_lab); self.bd2 = QComboBox(); self.bd2.addItems(["16","8"]); ho.addWidget(self.bd2); ho.addStretch(); l2.addLayout(ho)
        self.m2.currentTextChanged.connect(self.check_dng_mode)
        self.b2 = QPushButton("Start HDR"); self.b2.clicked.connect(lambda: self.go_proc("HDR")); l2.addWidget(self.b2); self.p2 = self._make_pb(); l2.addWidget(self.p2); self.p2_sub = self._make_pb(); l2.addWidget(self.p2_sub)
        hs2 = QHBoxLayout(); self.stop2 = QPushButton("Stop"); self.stop2.setFixedSize(50, 18); self.stop2.setEnabled(False); self.stop2.clicked.connect(self.stop_proc); hs2.addStretch(); hs2.addWidget(self.stop2); l2.addLayout(hs2)
        sp2 = QSplitter(Qt.Horizontal); self.log2 = QTextEdit(); self.prev2 = QLabel(); self.prev2.setAlignment(Qt.AlignCenter); sc2 = QScrollArea(); sc2.setWidget(self.prev2); sc2.setWidgetResizable(True); sp2.addWidget(self.log2); sp2.addWidget(sc2); l2.addWidget(sp2); sp2.setSizes([400, 800])

        # TAB 3: Burst
        self.t3 = QWidget(); self.tabs.addTab(self.t3, "3. Burst"); l3 = QVBoxLayout(self.t3)
        h3 = QHBoxLayout(); self.s3 = QLineEdit(); h3.addWidget(QLabel("Map:")); h3.addWidget(self.s3); b3_sel = QPushButton("..."); b3_sel.clicked.connect(lambda: self.sel(self.s3)); h3.addWidget(b3_sel); l3.addLayout(h3)
        hb = QHBoxLayout(); hb.addWidget(QLabel("Limiet:")); self.bl3 = QComboBox(); self.bl3.addItems(["8", "16", "32"]); hb.addWidget(self.bl3); hb.addStretch(); l3.addLayout(hb)
        self.b3 = QPushButton("Start Burst"); self.b3.clicked.connect(lambda: self.go_proc("BURST")); l3.addWidget(self.b3); self.p3 = self._make_pb(); l3.addWidget(self.p3); self.p3_sub = self._make_pb(); l3.addWidget(self.p3_sub)
        hs3 = QHBoxLayout(); self.stop3 = QPushButton("Stop"); self.stop3.setFixedSize(50, 18); self.stop3.setEnabled(False); self.stop3.clicked.connect(self.stop_proc); hs3.addStretch(); hs3.addWidget(self.stop3); l3.addLayout(hs3)
        sp3 = QSplitter(Qt.Horizontal); self.log3 = QTextEdit(); self.prev3 = QLabel(); self.prev3.setAlignment(Qt.AlignCenter); sc3 = QScrollArea(); sc3.setWidget(self.prev3); sc3.setWidgetResizable(True); sp3.addWidget(self.log3); sp3.addWidget(sc3); l3.addWidget(sp3); sp3.setSizes([300, 900])

        # TAB 4: Panorama
        self.t4 = QWidget(); self.tabs.addTab(self.t4, "4. Panorama"); l4 = QVBoxLayout(self.t4)
        h4_top = QHBoxLayout()
        self.f4 = QComboBox(); self.f4.addItems(["TIFF/JPG", "DNG", "RAW (Series)"]); self.f4.currentIndexChanged.connect(self.refresh_t4); h4_top.addWidget(self.f4)
        h4_top.addWidget(QLabel("Grootte:")); self.ts4 = QComboBox(); self.ts4.addItems(["100", "150", "200", "250", "300"]); self.ts4.setCurrentText("200"); self.ts4.currentIndexChanged.connect(self.refresh_t4); h4_top.addWidget(self.ts4)
        h4_top.addWidget(QLabel("Map:")); self.s4 = QLineEdit(); h4_top.addWidget(self.s4); b4 = QPushButton("..."); b4.clicked.connect(lambda: self.sel(self.s4)); h4_top.addWidget(b4)
        l4.addLayout(h4_top)

        self.pano_xmp_container = QWidget()
        h4_xmp = QHBoxLayout(self.pano_xmp_container); h4_xmp.setContentsMargins(0,0,0,0)
        h4_xmp.addWidget(QLabel("DNG XMP (optioneel):"))
        self.s4_xmp = QLineEdit(); h4_xmp.addWidget(self.s4_xmp)
        b4_xmpsel = QPushButton("..."); b4_xmpsel.clicked.connect(lambda: self.sel_file(self.s4_xmp)); h4_xmp.addWidget(b4_xmpsel)
        l4.addWidget(self.pano_xmp_container)
        self.pano_xmp_container.setVisible(False)

        self.pano_info = QLabel("<small><i>Info: DNG previews tonen soms liggend, maar het panorama-resultaat is correct.</i></small>")
        self.pano_info.setStyleSheet("color: #666; margin-bottom: 2px;"); self.pano_info.setVisible(False); l4.addWidget(self.pano_info)
        self.p4_load = self._make_pb(); l4.addWidget(self.p4_load)
        self.v_sp4 = QSplitter(Qt.Vertical)
        self.lw = QListWidget(); self.lw.setViewMode(QListWidget.IconMode); self.lw.setSelectionMode(QAbstractItemView.MultiSelection); self.lw.itemClicked.connect(lambda it: self.show_prev(it.data(Qt.UserRole))); self.v_sp4.addWidget(self.lw)
        bot_pano = QWidget(); lb4 = QVBoxLayout(bot_pano); lb4.setContentsMargins(0,0,0,0)
        hb4 = QHBoxLayout(); self.b4 = QPushButton("Start Panorama"); self.b4.clicked.connect(self.go4); hb4.addWidget(self.b4); self.btn_open4 = QPushButton("Openen in Darktable"); self.btn_open4.clicked.connect(self.open_in_dt); hb4.addWidget(self.btn_open4); lb4.addLayout(hb4)
        self.p4_sub = self._make_pb(); lb4.addWidget(self.p4_sub)
        hs4 = QHBoxLayout(); self.stop4 = QPushButton("Stop"); self.stop4.setFixedSize(50, 18); self.stop4.setEnabled(False); self.stop4.clicked.connect(self.stop_proc); hs4.addStretch(); hs4.addWidget(self.stop4); lb4.addLayout(hs4)
        sp4 = QSplitter(Qt.Horizontal); self.log4 = QTextEdit(); self.prev4 = QLabel(); self.prev4.setAlignment(Qt.AlignCenter); sc4 = QScrollArea(); sc4.setWidget(self.prev4); sc4.setWidgetResizable(True); sp4.addWidget(self.log4); sp4.addWidget(sc4); lb4.addWidget(sp4); sp4.setSizes([300, 900])
        self.v_sp4.addWidget(bot_pano); l4.addWidget(self.v_sp4)
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def check_dng_mode(self, text):
        is_dng = "DNG" in text
        self.bd2.setEnabled(not is_dng); self.bd2_lab.setEnabled(not is_dng)

    def _make_pb(self):
        pb = QProgressBar(); pb.setFixedHeight(8); pb.setTextVisible(False); pb.setStyleSheet("QProgressBar { border: 1px solid #bbb; background: #eee; } QProgressBar::chunk { background: #05B8CC; }")
        return pb

    def sel(self, e):
        d = QFileDialog.getExistingDirectory(self, "Kies Map", e.text())
        if d:
            p = os.path.abspath(d); e.setText(p)
            if e == self.s1:
                self.s2.setText(os.path.join(p, CONFIG["SORTED_DIR_NAME"]))
                self.s3.setText(os.path.join(p, CONFIG["SORTED_DIR_NAME"]))
                self.s4.setText(os.path.join(p, CONFIG["HDR_COLLECT_NAME"]))
            self.refresh_t4()

    def sel_file(self, e):
        f, _ = QFileDialog.getOpenFileName(self, "Kies XMP Bestand", e.text(), "XMP Bestanden (*.xmp)")
        if f: e.setText(os.path.abspath(f))

    def show_info(self):
        text = """<h2 style='color: #05B8CC;'>PanoStack Flow v2.0</h2>
        <p>Dit script biedt een complete workflow voor het sorteren en verwerken van RAW-foto's naar HDR, Bursts en Panorama's.</p>
        <h3 style='color: #05B8CC;'>1. Sorteren</h3>
        <ul><li><b>Pauze:</b> De maximale tijd (in sec) tussen foto's om ze in dezelfde reeks te groeperen.</li>
        <li><b>Type-detectie:</b> Herkent automatisch HDR-reeksen (belichtings-bracketing), Bursts (actie) en Series (panorama/overig).</li></ul>
        <h3 style='color: #05B8CC;'>2. HDR & Burst</h3>
        <ul><li><b>Isolatie:</b> Gebruikt Home-Redirect om database locks in Darktable 5.6+ te voorkomen.</li>
        <li><b>Enfuse:</b> Voegt belichtingen samen tot een natuurlijke 8-bit of 16-bit TIFF.</li>
        <li><b>HDRmerge:</b> Maakt een 16-bit DNG met behoud van alle RAW-informatie.</li></ul>
        <h3 style='color: #05B8CC;'>3. Panorama</h3>
        <ul><li><b>Stitching:</b> Gebruikt OpenCV Stitching engine voor naadloze overgangen.</li>
        <li><b>Ondersteuning:</b> Werkt zowel met samengevoegde DNG's als individuele RAW-bestanden.</li></ul>
        <p><i>Benodigdheden: ExifTool, Darktable-cli, Enfuse, Align_image_stack, HDRmerge.</i></p>"""
        QMessageBox.information(self, "Informatie", text)

    def open_in_dt(self):
        if self.last_result_path and os.path.exists(self.last_result_path):
            subprocess.Popen(['darktable', '--library', ':memory:', self.last_result_path])
        else: QMessageBox.warning(self, "Fout", "Geen bestand geselecteerd.")

    def refresh_t4(self):
        idx = self.f4.currentIndex(); only_series = False
        self.pano_info.setVisible(idx == 1)
        self.pano_xmp_container.setVisible(idx == 1)
        if idx == 0: path = os.path.join(self.s4.text(), "TIFF"); exts = ('.tif','.tiff','.jpg','.jpeg')
        elif idx == 1: path = os.path.join(self.s4.text(), "DNG"); exts = ('.dng',)
        else: path = self.s2.text(); exts = tuple(RAW_EXTS); only_series = True
        if not os.path.exists(path): return
        self.lw.clear(); size = int(self.ts4.currentText()); self.lw.setIconSize(QSize(size, size))
        if self.lt and self.lt.isRunning(): self.lt.quit(); self.lt.wait()
        self.lt = QThread(); self.lwk = ThumbnailWorker(path, exts, only_series); self.lwk.moveToThread(self.lt); self.lt.started.connect(self.lwk.run); self.lwk.thumb_ready.connect(self.add_thumb); self.lwk.progress.connect(self.p4_load.setValue); self.lwk.finished.connect(self.lt.quit); self.lt.start()

    def add_thumb(self, n, p, img):
        size = int(self.ts4.currentText()); it = QListWidgetItem(n); it.setData(Qt.UserRole, p); it.setIcon(QIcon(QPixmap.fromImage(img.scaled(size, size, Qt.KeepAspectRatio)))); self.lw.addItem(it)

    def stop_proc(self):
        if self.worker: self.worker.stop()

    def go1(self):
        sorted_dir = os.path.join(self.s1.text(), CONFIG["SORTED_DIR_NAME"])
        if os.path.exists(sorted_dir):
            if QMessageBox.question(self, "Opnieuw?", "De map is reeds gesorteerd. Wilt u opnieuw sorteren?", QMessageBox.Yes|QMessageBox.No) == QMessageBox.No: return
        self.p1.setValue(0); w = SortWorker(self.s1.text(), self.gv.value()); self._run(w, self.p1, self.log1, self.b1, None)

    def go_proc(self, mode):
        p = self.s2.text() if mode == "HDR" else self.s3.text(); limit = int(self.bl3.currentText()) if mode == "BURST" else 0
        w = HdrBurstWorker(p, mode, self.m2.currentText(), self.bd2.currentText(), limit)
        w.sub_progress.connect(self.p2_sub.setValue if mode=="HDR" else self.p3_sub.setValue)
        self._run(w, self.p2 if mode=="HDR" else self.p3, self.log2 if mode=="HDR" else self.log3, (self.b2 if mode=="HDR" else self.b3), (self.stop2 if mode=="HDR" else self.stop3))

    def go4(self):
        files = [self.lw.item(i).data(Qt.UserRole) for i in range(self.lw.count()) if self.lw.item(i).isSelected()]
        xmp_path = self.s4_xmp.text().strip()
        if files:
            w = PanoWorker(files, xmp_path if xmp_path else None)
            w.sub_progress.connect(self.p4_sub.setValue)
            w.finished.connect(self.lw.clearSelection)
            self._run(w, self.p4_sub, self.log4, self.b4, self.stop4)

    def _run(self, w, p, log, b, s_btn):
        if self.thread and self.thread.isRunning(): self.thread.quit(); self.thread.wait()
        self.worker = w; self.thread = QThread(); b.setEnabled(False)
        if s_btn: s_btn.setEnabled(True)
        w.moveToThread(self.thread)
        w.log.connect(log.append); w.progress.connect(p.setValue); w.finished.connect(self.thread.quit); w.finished.connect(lambda: (b.setEnabled(True), s_btn.setEnabled(False) if s_btn else None))
        if hasattr(w, 'result_path'): w.result_path.connect(lambda path: self.show_prev(path, w))
        self.thread.started.connect(w.run); self.thread.start()

    def show_prev(self, path, w=None):
        try:
            self.last_result_path = path
            if w and isinstance(w, SortWorker): target = self.prev1
            elif w and hasattr(w, 'mode') and w.mode == "HDR": target = self.prev2
            elif w and hasattr(w, 'mode') and w.mode == "BURST": target = self.prev3
            else: target = self.prev4
            img = get_image_robust(path)
            if not img.isNull(): target.setPixmap(QPixmap.fromImage(img).scaled(target.width(), target.height(), Qt.KeepAspectRatio))
        except: pass

    def on_tab_changed(self, idx):
        if idx == 3: self.refresh_t4()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Controleer dependencies VOORDAT het venster opent
    missing_deps = check_dependencies()
    if missing_deps:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Ontbrekende Software")
        msg.setText("De volgende programma's zijn niet gevonden op uw systeem:")
        msg.setInformativeText("\n".join(missing_deps) + "\n\nInstalleer deze programma's en voeg ze toe aan uw PATH-omgeving.")
        msg.exec()
        # We gaan door, maar de gebruiker is gewaarschuwd.
        # (Je kunt ook sys.exit() gebruiken om het script hier te stoppen)

    try:
        win = MainWindow(); win.show(); sys.exit(app.exec())
    except Exception: print(traceback.format_exc())
