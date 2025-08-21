#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mr LY Tool — Premium Downloader UI
Platforms: TikTok, Instagram, Facebook, YouTube (via yt-dlp)
Includes: License key input + generator + download timer + shutdown + auto-update
"""

import sys, os, re, threading, urllib.parse, pathlib, subprocess, random, string, tempfile, shutil, urllib.request
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QPlainTextEdit,
    QVBoxLayout, QHBoxLayout, QComboBox, QFileDialog, QProgressBar, QMessageBox, QCheckBox
)

try:
    import yt_dlp
except Exception:
    yt_dlp = None

PLATFORMS = ["Auto Detect", "YouTube", "TikTok", "Instagram", "Facebook"]
INPUT_TYPES = ["Auto Detect", "URL", "Username"]
CURRENT_VERSION = "1.0.0"

# ---------------- Auto-Update URL ----------------
latest_url = "https://raw.githubusercontent.com/elliotbutler9310-ops/MrLYDownloader/refs/heads/main/Mr%20LY%20Download.py"

# ---------------- License Key ----------------
def generate_license(exp_days: int = 30) -> str:
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(random.choices(chars, k=4)) for _ in range(3)]
    exp_date = (datetime.now() + timedelta(days=exp_days)).strftime("%Y%m%d")
    key = '-'.join(parts + [exp_date])
    return key

def validate_license(key: str) -> bool:
    try:
        parts = key.strip().split('-')
        if len(parts) != 4: return False
        exp_date = datetime.strptime(parts[3], "%Y%m%d")
        if datetime.now() > exp_date: return False
        return True
    except: return False

# ---------------- Utilities ----------------
def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s.strip())
    return s.strip("_") or "download"

def detect_platform(url_or_user: str) -> str:
    text = url_or_user.strip().lower()
    if text.startswith("http"):
        host = urllib.parse.urlparse(text).netloc.lower()
        if "youtu" in host: return "YouTube"
        if "tiktok.com" in host: return "TikTok"
        if "instagram.com" in host: return "Instagram"
        if "facebook.com" in host or "fb.watch" in host: return "Facebook"
    return "Auto Detect"

def build_url_from_username(platform: str, username: str) -> Optional[str]:
    u = username.strip().lstrip("@")
    if not u: return None
    if platform == "YouTube": return f"https://www.youtube.com/@{u}"
    if platform == "TikTok": return f"https://www.tiktok.com/@{u}"
    if platform == "Instagram": return f"https://www.instagram.com/{u}/"
    if platform == "Facebook": return f"https://www.facebook.com/{u}"
    return None

def derive_folder_name(platform: str, url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        last = slugify((p.path.rstrip("/") or "/").split("/")[-1])
        host = p.netloc.split(":")[0]
        if not last: last = slugify(p.netloc)
        return slugify(f"{host}_{last}")
    except: return slugify(url)

@dataclass
class DownloadItem:
    platform: str
    input_type: str
    raw_text: str
    resolved_url: Optional[str] = None
    out_dir: Optional[str] = None

# ---------------- Signals ----------------
class DownloaderSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    item_progress = pyqtSignal(str)
    counts = pyqtSignal(int, int, int)
    done = pyqtSignal()

# ---------------- Logger ----------------
class YTDLPLogger:
    def __init__(self, sig: DownloaderSignals, prefix: str = ""):
        self.sig = sig
        self.prefix = prefix
    def debug(self, msg): self.sig.log.emit(f"{self.prefix}{msg}")
    def warning(self, msg): self.sig.log.emit(f"⚠️ {self.prefix}{msg}")
    def error(self, msg): self.sig.log.emit(f"❌ {self.prefix}{msg}")

# ---------------- Worker ----------------
class Worker(threading.Thread):
    def __init__(self, items: List[DownloadItem], cookie_text: str, base_dir: str, sig: DownloaderSignals, stop_flag):
        super().__init__(daemon=True)
        self.items = items
        self.cookie_text = cookie_text.strip()
        self.base_dir = base_dir
        self.sig = sig
        self.stop_flag = stop_flag
        self.total = len(items)
        self.ok = 0
        self.fail = 0
        self.processes: List[subprocess.Popen] = []

    def run(self):
        if yt_dlp is None:
            self.sig.log.emit("❌ yt-dlp not installed. Run: pip install yt-dlp")
            self.sig.done.emit()
            return

        for idx, item in enumerate(self.items, start=1):
            if self.stop_flag.is_set(): break
            try:
                self.sig.item_progress.emit(f"[{idx}/{self.total}] Preparing: {item.raw_text}")
                url = item.resolved_url or item.raw_text.strip()
                platform = item.platform if item.platform != "Auto Detect" else detect_platform(url)
                folder_name = derive_folder_name(platform or "Auto", url)
                outdir = os.path.join(self.base_dir, platform or "Auto", folder_name)
                os.makedirs(outdir, exist_ok=True)
                item.out_dir = outdir

                headers = {}
                fmt = "bestvideo[height<=1080]+bestaudio/best"
                merge_fmt = "mp4"
                if platform in ["TikTok", "Instagram", "Facebook"]:
                    fmt = "best[ext=mp4][height<=1080]"
                    merge_fmt = None

                ydl_opts = {
                    "logger": YTDLPLogger(self.sig, prefix=f"[{platform}] "),
                    "progress_hooks": [self._hook],
                    "outtmpl": os.path.join(outdir, "%(title).80s [%(id)s].%(ext)s"),
                    "concurrent_fragment_downloads": 4,
                    "retries": 5,
                    "ignoreerrors": "only_download",
                    "noprogress": True,
                    "format": fmt
                }
                if merge_fmt:
                    ydl_opts["merge_output_format"] = merge_fmt
                if self.cookie_text:
                    if self.cookie_text.upper().startswith("COOKIEFILE:"):
                        cookie_path = self.cookie_text.split(":",1)[1].strip()
                        if os.path.exists(cookie_path):
                            ydl_opts["cookiefile"] = cookie_path
                            self.sig.log.emit(f"🍪 Using cookie file: {cookie_path}")
                    else:
                        headers["Cookie"] = self.cookie_text
                if headers: ydl_opts["http_headers"] = headers

                cmd = [sys.executable, "-m", "yt_dlp", url, "-o", os.path.join(outdir, "%(title).80s [%(id)s].%(ext)s"), "-f", fmt]
                if merge_fmt: cmd += ["--merge-output-format", merge_fmt]
                if self.cookie_text.upper().startswith("COOKIEFILE:"):
                    cmd += ["--cookies", self.cookie_text.split(":",1)[1].strip()]

                self.sig.item_progress.emit(f"[{idx}/{self.total}] Downloading → {url}")
                proc = subprocess.Popen(cmd)
                self.processes.append(proc)
                while proc.poll() is None:
                    if self.stop_flag.is_set():
                        proc.kill()
                        self.sig.log.emit("⏹️ Download killed.")
                        break
                if proc.returncode == 0:
                    self.ok += 1
                    self.sig.log.emit(f"✅ Finished: {url}\n   → Saved in: {outdir}")
                else:
                    self.fail += 1
                    self.sig.log.emit(f"❌ Failed: {url}")
            except Exception as e:
                self.fail += 1
                self.sig.log.emit("❌ Error: " + str(e))
            finally:
                self.sig.counts.emit(self.total, self.ok, self.fail)
                pct = int(((self.ok + self.fail) / max(1,self.total))*100)
                self.sig.progress.emit(pct)
        self.sig.done.emit()

    def _hook(self, d):
        if d.get("status")=="downloading":
            total=d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded=d.get("downloaded_bytes",0)
            if total: pct=int(downloaded*100/max(1,total))
            self.sig.item_progress.emit(f"⬇️ {pct}%  {d.get('filename','')}")
        elif d.get("status")=="finished":
            self.sig.item_progress.emit(f"💾 Post-processing: {d.get('filename','')}")

# ---------------- Main UI ----------------
class MrLYDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mr LY Tool — Premium Downloader")
        self.resize(980,680)
        self.stop_flag = threading.Event()
        self.worker: Optional[Worker] = None
        self.signals = DownloaderSignals()
        self.download_seconds = 0
        self.download_timer = QTimer(self)
        self.download_timer.timeout.connect(self._tick_download)
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.timeout.connect(self._tick_shutdown)
        self.shutdown_seconds = 0
        self._build_ui()
        self._wire_signals()

    def _build_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #0b0b0b; color: #f5d36a; font-family: Segoe UI; }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
                background-color: #121212; color: #f5d36a;
                border: 1px solid #7a5f0e; border-radius: 10px; padding: 8px;
            }
            QPushButton {
                background-color: #1a1a1a; color: #f5d36a;
                border: 2px solid #a47c1b; border-radius: 18px; padding: 12px 24px;
                font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #222; }
            QPushButton:disabled { color: #7a5f0e; border-color: #7a5f0e; }
            QLabel.h1 { font-size: 26px; font-weight: 700; color: #ffd777; }
            QProgressBar { border: 1px solid #7a5f0e; border-radius: 10px; }
            QProgressBar::chunk { background-color: #f5d36a; border-radius: 10px; }
        """)

        title=QLabel("Mr LY Tool — Premium Downloader")
        title.setProperty("class","h1")

        row1=QHBoxLayout()
        self.platform=QComboBox(); self.platform.addItems(PLATFORMS)
        self.input_type=QComboBox(); self.input_type.addItems(INPUT_TYPES)
        row1.addWidget(QLabel("Platform:")); row1.addWidget(self.platform)
        row1.addSpacing(10)
        row1.addWidget(QLabel("Input:")); row1.addWidget(self.input_type)
        row1.addStretch(1)

        # License
        license_row=QHBoxLayout()
        self.license_box=QLineEdit()
        self.license_box.setPlaceholderText("Enter License Key")
        self.license_box.setEchoMode(QLineEdit.EchoMode.Password)
        self.license_toggle=QPushButton("👁")
        self.license_toggle.setFixedWidth(30)
        self.license_toggle.setCheckable(True)
        self.license_toggle.clicked.connect(self._toggle_license_visibility)
        self.license_days_box=QLineEdit()
        self.license_days_box.setPlaceholderText("Expiration days (e.g., 30)")
        btn_gen_license=QPushButton("Generate Key")
        btn_gen_license.clicked.connect(self._generate_license)
        license_row.addWidget(self.license_box)
        license_row.addWidget(self.license_toggle)
        license_row.addWidget(self.license_days_box)
        license_row.addWidget(btn_gen_license)

        # Links
        self.link_box=QPlainTextEdit()
        self.link_box.setPlaceholderText("Paste URL(s) or username(s) here — one per line")
        self.link_box.setFixedHeight(110)

        # Cookie
        cookie_row=QHBoxLayout()
        self.cookie_box=QLineEdit()
        self.cookie_box.setPlaceholderText("Cookie header OR COOKIEFILE:/path/to/cookies.txt (optional)")
        btn_cookie=QPushButton("📁 Browse Cookie File")
        btn_cookie.clicked.connect(self._pick_cookie_file)
        cookie_row.addWidget(QLabel("Cookies:"))
        cookie_row.addWidget(self.cookie_box)
        cookie_row.addWidget(btn_cookie)

        # Output folder
        out_row=QHBoxLayout()
        self.out_dir=QLineEdit(os.path.join(str(pathlib.Path.home()),"MrLY_Downloads"))
        btn_pick_out=QPushButton("📁 Choose Output Folder")
        btn_pick_out.clicked.connect(self._pick_output)
        out_row.addWidget(QLabel("Save to:")); out_row.addWidget(self.out_dir); out_row.addWidget(btn_pick_out)

        # Start / Stop + Timer + Shutdown
        run_row=QHBoxLayout()
        self.btn_start=QPushButton("▶ START DOWNLOAD")
        self.btn_stop=QPushButton("■ STOP DOWNLOAD")
        self.lbl_timer=QLabel("00:00:00")
        self.lbl_timer.setStyleSheet("font-size:24px;font-weight:bold;color:#FFD700;min-width:120px;")
        run_row.addWidget(self.btn_start); run_row.addWidget(self.lbl_timer)
        run_row.addSpacing(30); run_row.addWidget(self.btn_stop); run_row.addStretch(1)

        cnt_row=QHBoxLayout()
        self.lbl_total=QLabel("Total: 0"); self.lbl_ok=QLabel("Success: 0"); self.lbl_fail=QLabel("Failed: 0")
        cnt_row.addWidget(self.lbl_total); cnt_row.addSpacing(10)
        cnt_row.addWidget(self.lbl_ok); cnt_row.addSpacing(10)
        cnt_row.addWidget(self.lbl_fail); cnt_row.addStretch(1)

        self.progress=QProgressBar(); self.progress.setValue(0)
        self.item_status=QLabel("Idle")
        self.shutdown_check=QCheckBox("Shutdown PC after download")
        self.shutdown_check.setStyleSheet("color:#f5d36a;font-weight:bold;")
        self.cancel_shutdown_btn=QPushButton("❌ Cancel Shutdown")
        self.cancel_shutdown_btn.setVisible(False)

        # Update button
        self.btn_update=QPushButton(f"Update Version ({CURRENT_VERSION})")

        self.log=QPlainTextEdit(); self.log.setReadOnly(True)

        layout=QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(row1)
        layout.addLayout(license_row)
        layout.addWidget(self.link_box)
        layout.addLayout(cookie_row)
        layout.addLayout(out_row)
        layout.addSpacing(20)
        layout.addLayout(run_row)
        layout.addSpacing(10)
        layout.addLayout(cnt_row)
        layout.addWidget(self.progress)
        layout.addWidget(self.item_status)
        layout.addWidget(self.shutdown_check)
        layout.addWidget(self.cancel_shutdown_btn)
        layout.addWidget(self.btn_update)
        layout.addWidget(self.log)

    # ---------------- UI Signals ----------------
    def _wire_signals(self):
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.cancel_shutdown_btn.clicked.connect(self._cancel_shutdown)
        self.btn_update.clicked.connect(self._update_version)
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self.progress.setValue)
        self.signals.item_progress.connect(self.item_status.setText)
        self.signals.counts.connect(self._update_counts)
        self.signals.done.connect(self._on_done)

    def _append_log(self,s:str): self.log.appendPlainText(s)
    def _update_counts(self,total,ok,fail):
        self.lbl_total.setText(f"Total: {total}")
        self.lbl_ok.setText(f"Success: {ok}")
        self.lbl_fail.setText(f"Failed: {fail}")

    def _pick_output(self):
        d=QFileDialog.getExistingDirectory(self,"Choose output folder",self.out_dir.text())
        if d: self.out_dir.setText(d)
    def _pick_cookie_file(self):
        f=QFileDialog.getOpenFileName(self,"Select Cookie File","","Text Files (*.txt);;All Files (*)")
        if f[0]: self.cookie_box.setText(f"COOKIEFILE:{f[0]}")

    # ---------------- License ----------------
    def _generate_license(self):
        try: days=int(self.license_days_box.text())
        except: days=30
        key=generate_license(days)
        self.license_box.setText(key)
        QMessageBox.information(self,"License Generated",f"Key valid for {days} days:\n{key}")

    def _toggle_license_visibility(self):
        if self.license_toggle.isChecked(): self.license_box.setEchoMode(QLineEdit.EchoMode.Normal)
        else: self.license_box.setEchoMode(QLineEdit.EchoMode.Password)

    # ---------------- Timer ----------------
    def _tick_download(self):
        self.download_seconds+=1
        h=self.download_seconds//3600; m=(self.download_seconds%3600)//60; s=self.download_seconds%60
        self.lbl_timer.setText(f"{h:02}:{m:02}:{s:02}")

    # ---------------- Shutdown ----------------
    def _start_shutdown_timer(self,seconds:int=60):
        self.shutdown_seconds=seconds
        self.cancel_shutdown_btn.setVisible(True)
        self.shutdown_timer.start(1000)

    def _tick_shutdown(self):
        if self.shutdown_seconds<=0:
            self.shutdown_timer.stop()
            self.cancel_shutdown_btn.setVisible(False)
            self._append_log("💻 Shutting down now...")
            if sys.platform.startswith("win"): subprocess.call("shutdown /s /t 0", shell=True)
            else: subprocess.call("shutdown now", shell=True)
        else:
            self.item_status.setText(f"Shutdown in {self.shutdown_seconds} seconds...")
            self.shutdown_seconds-=1

    def _cancel_shutdown(self):
        self.shutdown_timer.stop()
        self.cancel_shutdown_btn.setVisible(False)
        self._append_log("❌ Shutdown canceled.")
        self.item_status.setText("Shutdown canceled")

    # ---------------- Start / Stop ----------------
    def _start(self):
        if not validate_license(self.license_box.text()):
            QMessageBox.warning(self,"Invalid License","License key is invalid or expired!")
            return
        lines=[l.strip() for l in self.link_box.toPlainText().splitlines() if l.strip()]
        if not lines:
            QMessageBox.warning(self,"No links","Please enter URL(s) or username(s) to download.")
            return
        items=[DownloadItem(platform=self.platform.currentText(),
                            input_type=self.input_type.currentText(),
                            raw_text=line) for line in lines]
        self.stop_flag.clear()
        self.worker=Worker(items, self.cookie_box.text(), self.out_dir.text(), self.signals, self.stop_flag)
        self.worker.start()
        self.download_seconds=0
        self.download_timer.start(1000)
        self._append_log("▶ Download started...")

    def _stop(self):
        self.stop_flag.set()
        self._append_log("■ Download stopped by user.")
        self.download_timer.stop()

    def _on_done(self):
        self.download_timer.stop()
        self._append_log("✅ All tasks finished.")
        if self.shutdown_check.isChecked(): self._start_shutdown_timer(seconds=60)

    # ---------------- Auto-Update ----------------
    def _update_version(self):
        self._append_log("🔄 Checking for latest version...")
        try:
            latest_url = "https://example.com/mrly_downloader.py"  # Change to your hosted latest script
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
            urllib.request.urlretrieve(latest_url, tmp_file.name)
            current_file = os.path.realpath(sys.argv[0])
            backup_file = current_file + ".bak"
            shutil.copy2(current_file, backup_file)
            shutil.copy2(tmp_file.name, current_file)
            self._append_log(f"✅ Update applied! Backup: {backup_file}")
            self._append_log("♻ Restarting application...")
            if sys.platform.startswith("win"):
                subprocess.Popen([sys.executable, current_file])
            else:
                os.execv(sys.executable, [sys.executable, current_file])
            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self,"Update Failed",f"Failed to update: {e}")
            self._append_log(f"❌ Update failed: {e}")

# ---------------- Main ----------------
if __name__=="__main__":
    app=QApplication(sys.argv)
    win=MrLYDownloader()
    win.show()
    sys.exit(app.exec())
