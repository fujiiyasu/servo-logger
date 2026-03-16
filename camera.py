#!/usr/bin/env python3
"""
camera.py
=========
USBカメラによるタイムラプス撮影モジュール
"""

import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[WARN] opencv-python が見つかりません: pip install opencv-python-headless")


class TimelapseCamera:
    def __init__(self, session_dir: Path, interval_sec: float = 1.0, device: int = 0):
        self.session_dir  = session_dir
        self.interval_sec = interval_sec
        self.device       = device
        self.running      = False
        self.frame_count  = 0
        self.frame_log    = []   # [{frame_index, timestamp_ms, filepath}]
        self._thread      = None
        self._cap         = None

    def open(self):
        if not CV2_AVAILABLE:
            print("[WARN] OpenCV 未インストールのためカメラ無効")
            return False
        self._cap = cv2.VideoCapture(self.device)
        if not self._cap.isOpened():
            print(f"[ERROR] カメラ {self.device} を開けません")
            return False
        # 解像度設定
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        print(f"[OK] カメラ初期化完了 (device={self.device})")
        return True

    def _capture_loop(self, start_time: float):
        while self.running:
            ret, frame = self._cap.read()
            if ret:
                timestamp_ms = int((time.time() - start_time) * 1000)
                filename     = f"frame_{self.frame_count:06d}.jpg"
                filepath     = self.session_dir / filename
                cv2.imwrite(str(filepath), frame)
                self.frame_log.append({
                    "frame_index":  self.frame_count,
                    "timestamp_ms": timestamp_ms,
                    "filepath":     str(filepath),
                    "filename":     filename,
                })
                self.frame_count += 1
            time.sleep(self.interval_sec)

    def start(self, start_time: float):
        if not self._cap or not self._cap.isOpened():
            return
        self.running     = True
        self.frame_count = 0
        self.frame_log   = []
        self._thread     = threading.Thread(
            target=self._capture_loop, args=(start_time,), daemon=True
        )
        self._thread.start()
        print("[OK] タイムラプス撮影開始")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        print(f"[OK] 撮影停止 ({self.frame_count} フレーム)")

    def close(self):
        self.stop()
        if self._cap:
            self._cap.release()