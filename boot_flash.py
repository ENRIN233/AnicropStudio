# -*- coding: utf-8 -*-
"""
boot_flash.py - Anicrop Studio 模块逐个上电
"""

import math
import random

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QObject
from PySide6.QtGui import QPainter, QColor


class FlickerOverlay(QWidget):
    """黑色遮罩层，挂在某个模块上，自己闪一下后消失"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._alpha = 0.0

    def set_alpha(self, alpha: float):
        a = max(0.0, min(1.0, alpha))
        if abs(a - self._alpha) < 0.003:
            return
        self._alpha = a
        self.update()

    def paintEvent(self, event):
        if self._alpha <= 0.001:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, int(self._alpha * 255)))


class ModuleFlash(QObject):
    """
    单个模块的频闪：
      前期高频抖动 → 后期低频 → 完全稳定
    """

    def __init__(self, widget, duration_ms=4000):
        super().__init__(widget)
        self.widget = widget
        self.duration_ms = duration_ms

        self.overlay = FlickerOverlay(widget)
        self.overlay.setGeometry(0, 0, widget.width(), widget.height())
        self.overlay.setVisible(True)
        self.overlay.raise_()
        self.overlay.set_alpha(1.0)

        self._elapsed = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._elapsed += 16.0
        if self._elapsed >= self.duration_ms:
            # 干脆地停：alpha 直接归 0
            self.overlay.set_alpha(0.0)
            self.overlay.setVisible(False)
            self.overlay.deleteLater()
            self._timer.stop()
            return

        # 固定频率 12Hz
        freq = 16.0
        sine = 0.5 + 0.5 * math.sin(self._elapsed / 1000.0 * freq * 2.0 * math.pi)

        # 固定强度 0.85
        alpha = sine * 1
        self.overlay.set_alpha(alpha)

class BootFlash(QObject):
    """
    模块逐个上电
    参数:
        main_window: 主窗口
        steps: [(延迟毫秒, widget), ...]
        flash_duration: 每个模块黑罩褪掉用的时长（毫秒）
    """

    def __init__(self, main_window, steps, flash_duration=800):
        super().__init__(main_window)
        self.win = main_window
        self.steps = steps
        self.flash_duration = flash_duration

    def start(self):
        # 1. 全部模块先隐藏
        for _delay, widget in self.steps:
            widget.setVisible(False)

        # 2. 按顺序安排上线
        for delay_ms, widget in self.steps:
            QTimer.singleShot(delay_ms, lambda w=widget: self._power_on(w))

    def _power_on(self, widget):
        widget.setVisible(True)
        widget.update()
        # 挂一层黑罩，从 1 快速降到 0
        flash = ModuleFlash(widget, duration_ms=self.flash_duration)
        widget._module_flash = flash   # 防止被 GC