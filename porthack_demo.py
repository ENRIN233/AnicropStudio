# -*- coding: utf-8 -*-
"""
Anicrop Studio - 状态指示器版 (v48)
1. 球体放大 1.4 倍（0.32 → 0.448）
2. 窗口大小锁死（固定 280×280）
"""

import sys
import math
import random
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QFrame
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QRadialGradient


WORDS = [
    "canon", "sony", "nikon", "fujifilm", "panasonic", "leica",
    "hasselblad", "olympus", "dji", "sigma", "pentax", "ricoh",
    "zeiss", "tamron", "samyang", "voigtlander",
    "r50", "r6", "r5", "r3", "r8", "5d4", "6d2", "90d",
    "a7m4", "a7r5", "a7s3", "a1", "a9", "a6700", "zv-e1", "fx3",
    "z6ii", "z7ii", "z8", "z9", "z50", "zfc", "d850",
    "x100v", "x-t5", "x-h2", "x-s20", "gfx100", "gfx100s",
    "s5ii", "gh6", "g9ii",
    "auto", "pmode", "av", "tv", "mmode", "bulb", "custom",
    "afs", "afc", "afa", "mf", "dmf", "afon", "eyeaf",
    "single", "burst", "timer", "bkt", "hdr",
    "f1.2", "f1.4", "f1.8", "f2.8", "f4", "f5.6", "f8", "f11",
    "iso100", "iso200", "iso400", "iso800", "iso1600", "iso3200",
    "iso6400", "iso12800", "iso25600",
    "1/60s", "1/125s", "1/250s", "1/500s", "1/1000s", "1/2000s",
    "1/4000s", "1/8000s", "30s", "1s", "2s",
    "ev+1", "ev-1", "ev+2", "ev-2",
    "24mm", "35mm", "50mm", "85mm", "135mm", "200mm", "300mm",
    "16-35", "24-70", "70-200", "18-45", "18-150",
    "prime", "zoom", "macro", "tiltshift",
    "raw", "cr3", "arw", "nef", "raf", "dng", "jpg", "heif",
    "exif", "xmp", "aflock", "aelock", "focuspeaking",
    "bokeh", "shutter", "aperture", "sensor", "histogram",
    "whitebalance", "awb", "kelvin", "graycard",
    "2800k", "3200k", "4000k", "5000k", "5600k", "6500k",
    "lightroom", "captureone", "dpp", "photoshop", "dxo",
    "retouch", "export", "thumbnail", "batch", "preset",
]


class IndicatorSphere(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000000;")
        # ===== 窗口锁死: 固定尺寸，不随父容器拉伸 =====
        self.setFixedSize(280, 280)

        self.t = 0.0

        self.NUM_NODES = 220
        self.R_BASE = 0.85
        self.Y_FLATTEN = 0.68
        self.SIZE_MULT = 1.4

        self.BREATH_SPEED = 0.12

        self.YAW_SPEED = 0.002
        self.TRAVELER_SPEED_MIN = 0.004
        self.TRAVELER_SPEED_MAX = 0.010
        self.TRAVELER_FADE = 0.006

        self.BUSY_HUE_STRENGTH = 0.55
        self.FLASH_FREQ = 1.0
        self.FLASH_AMP = 0.15

        self.header_h = 17
        self.bar_h = 13

        self.header_left = "app:PortHack"
        self.header_right = "IP: 51.195.49.24"

        self.surge_state = "normal"
        self.surge_intensity = 0.0
        self.surge_timer = 0.0
        self.surge_next = random.uniform(30.0, 90.0)
        self.surge_hold = 0.0
        self.surge_hold_target = 0.0

        self.busy_target_external = 0.0
        self.busy_external = 0.0

        self.busy = 0.0
        self.hue_mix = 0.0
        self.flash = 0.0

        self.scale_phase = random.uniform(0, math.pi * 2)
        self.pitch_phase = random.uniform(0, math.pi * 2)

        self.rain_cols = []
        for _ in range(18):
            self.rain_cols.append(self._make_rain_col())

        self.bg_stars_far = []
        for _ in range(60):
            self.bg_stars_far.append({
                "x": random.random(),
                "y": random.random(),
                "size": random.uniform(0.3, 0.7),
                "alpha": random.randint(40, 100),
                "twinkle_phase": random.uniform(0, math.pi * 2),
                "twinkle_speed": random.uniform(0.5, 1.5),
            })

        self.nodes_dir = []
        self.nodes_r = []
        self._generate_nodes()

        self.node_phases = [random.uniform(0, math.pi * 2) for _ in range(self.NUM_NODES)]
        self.node_speeds = [random.uniform(0.6, 1.4) for _ in range(self.NUM_NODES)]

        self.drift_phases = [random.uniform(0, math.pi * 2) for _ in range(self.NUM_NODES)]
        self.drift_speeds = [random.uniform(0.3, 0.8) for _ in range(self.NUM_NODES)]
        self.drift_dirs = []
        for _ in range(self.NUM_NODES):
            theta = random.uniform(0, math.pi * 2)
            phi = math.acos(random.uniform(-1.0, 1.0))
            self.drift_dirs.append((
                math.sin(phi) * math.cos(theta),
                math.cos(phi),
                math.sin(phi) * math.sin(theta),
            ))

        self.K = 5
        self.connections = []
        self._rebuild_connections()

        self.reconnect_timer = 0.0
        self.travelers = []
        self.spawn_timer = 0.0
        self.yaw = 0.0
        self.pitch = 0.25
        self.progress = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def set_busy(self, busy: bool):
        self.busy_target_external = 1.0 if busy else 0.0

    def set_progress(self, value: float):
        self.progress = max(0.0, min(1.0, value))

    def _make_rain_col(self):
        length = random.randint(5, 12)
        return {
            "x": random.random(),
            "y": random.random() * 1.5 - 0.5,
            "speed": random.uniform(0.0006, 0.0025),
            "length": length,
            "chars": [random.choice("01" * 8 + "0123456789ABCDEF") for _ in range(length)],
            "char_timer": random.uniform(0, 0.3),
            "alpha": random.randint(35, 80),
        }

    def _generate_nodes(self):
        for _ in range(self.NUM_NODES):
            r = random.random() ** (1.0 / 3.0)
            theta = random.uniform(0, math.pi * 2)
            phi = math.acos(random.uniform(-1.0, 1.0))
            dx = math.sin(phi) * math.cos(theta)
            dy = math.cos(phi)
            dz = math.sin(phi) * math.sin(theta)
            self.nodes_dir.append((dx, dy, dz))
            self.nodes_r.append(r)

    def _rebuild_connections(self):
        self.connections = []
        base_positions = []
        for i in range(self.NUM_NODES):
            dx, dy, dz = self.nodes_dir[i]
            r = self.nodes_r[i] * self.R_BASE
            base_positions.append((dx * r, dy * r * self.Y_FLATTEN, dz * r))

        for i in range(self.NUM_NODES):
            x1, y1, z1 = base_positions[i]
            dists = []
            for j in range(self.NUM_NODES):
                if i == j:
                    continue
                x2, y2, z2 = base_positions[j]
                d = (x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2
                dists.append((d, j))
            dists.sort()
            for d, j in dists[:self.K]:
                a, b = min(i, j), max(i, j)
                self.connections.append((a, b))
        self.connections = list(set(self.connections))

    def _tick(self):
        dt = 0.016
        self.t += dt

        if self.surge_state == "normal":
            self.surge_timer += dt
            if self.surge_timer >= self.surge_next:
                self.surge_state = "rising"
                self.surge_timer = 0.0
                self.surge_hold_target = random.uniform(15.0, 40.0)
        elif self.surge_state == "rising":
            self.surge_intensity += 0.02
            if self.surge_intensity >= 1.0:
                self.surge_intensity = 1.0
                self.surge_state = "overload"
                self.surge_hold = 0.0
        elif self.surge_state == "overload":
            self.surge_hold += dt
            if self.surge_hold >= self.surge_hold_target:
                self.surge_state = "falling"
        elif self.surge_state == "falling":
            self.surge_intensity -= 0.015
            if self.surge_intensity <= 0.0:
                self.surge_intensity = 0.0
                self.surge_state = "normal"
                self.surge_next = random.uniform(30.0, 90.0)

        self.busy_external += (self.busy_target_external - self.busy_external) * 0.05

        self.busy = max(self.surge_intensity, self.busy_external)
        self.hue_mix += (self.busy - self.hue_mix) * 0.05

        flash_amp = self.FLASH_AMP * (0.3 + 0.7 * self.busy)
        self.flash = math.sin(self.t * self.FLASH_FREQ * math.pi * 2) * flash_amp

        speed_mult = 1.0 + 2.0 * self.busy

        self.yaw += self.YAW_SPEED * speed_mult

        self.reconnect_timer += dt * speed_mult
        if self.reconnect_timer > 1.5:
            self.reconnect_timer = 0.0
            self._partial_reconnect()

        self.spawn_timer += dt * speed_mult
        if self.spawn_timer > 0.20:
            self.spawn_timer = 0.0
            self._spawn_traveler()

        for tr in self.travelers[:]:
            if tr.get("fade_in", False):
                tr["fade_alpha"] += self.TRAVELER_FADE * speed_mult
                if tr["fade_alpha"] >= 1.0:
                    tr["fade_alpha"] = 1.0
                    tr["fade_in"] = False
                continue
            if tr.get("fading", False):
                tr["fade_alpha"] -= self.TRAVELER_FADE * speed_mult
                if tr["fade_alpha"] <= 0:
                    self.travelers.remove(tr)
                continue
            tr["t"] += tr["speed"] * speed_mult
            if tr["t"] >= 1.0:
                tr["t"] = 0.0
                tr["seg"] += 1
                if tr["seg"] >= len(tr["path"]) - 1:
                    tr["fading"] = True

        for col in self.rain_cols:
            col["y"] += col["speed"] * speed_mult
            col["char_timer"] += dt * speed_mult
            if col["char_timer"] > 0.15:
                col["char_timer"] = 0.0
                idx = random.randint(0, col["length"] - 1)
                col["chars"][idx] = random.choice("01" * 8 + "0123456789ABCDEF")
            if col["y"] > 1.5:
                self.rain_cols.remove(col)
                self.rain_cols.append(self._make_rain_col())

        self.update()

    def _partial_reconnect(self):
        sample_size = max(1, self.NUM_NODES // 20)
        changed_nodes = set(random.sample(range(self.NUM_NODES), sample_size))

        self.connections = [(a, b) for (a, b) in self.connections
                            if a not in changed_nodes and b not in changed_nodes]

        for i in changed_nodes:
            xi, yi, zi = self._node_3d_now(i)
            dists = []
            for j in range(self.NUM_NODES):
                if i == j:
                    continue
                xj, yj, zj = self._node_3d_now(j)
                d = (xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2
                dists.append((d, j))
            dists.sort()
            for d, j in dists[:self.K]:
                self.connections.append((min(i, j), max(i, j)))
        self.connections = list(set(self.connections))

    def _breath_factor(self):
        phase = 0.5 + 0.5 * math.sin(self.t * self.BREATH_SPEED + self.scale_phase)
        max_amp = 2.75 * (1.0 - 0.7 * self.busy)
        return 1.0 + max_amp * phase

    def _node_3d_now(self, i):
        bf = self._breath_factor()
        dx, dy, dz = self.nodes_dir[i]
        r = self.nodes_r[i] * self.R_BASE * bf
        x = dx * r
        y = dy * r * self.Y_FLATTEN
        z = dz * r

        drift_amp = 0.07 * bf
        drift = drift_amp * math.sin(self.t * self.drift_speeds[i] + self.drift_phases[i])
        ddx, ddy, ddz = self.drift_dirs[i]
        x += ddx * drift
        y += ddy * drift
        z += ddz * drift

        indiv = 1.0 + 0.03 * math.sin(self.t * self.node_speeds[i] + self.node_phases[i])
        return x * indiv, y * indiv, z * indiv

    def _spawn_traveler(self):
        if not self.connections:
            return
        a, b = random.choice(self.connections)
        path = [a, b]
        for _ in range(random.randint(0, 2)):
            last = path[-1]
            neighbors = []
            for (x, y) in self.connections:
                if x == last:
                    neighbors.append(y)
                elif y == last:
                    neighbors.append(x)
            if not neighbors:
                break
            path.append(random.choice(neighbors))
        has_word = random.random() < 0.55
        text = random.choice(WORDS) if has_word else None
        self.travelers.append({
            "path": path, "seg": 0, "t": 0.0,
            "speed": random.uniform(self.TRAVELER_SPEED_MIN, self.TRAVELER_SPEED_MAX),
            "text": text,
            "fade_in": True,
            "fading": False,
            "fade_alpha": 0.0,
        })

    def _rotate(self, x, y, z):
        cos_y = math.cos(self.yaw)
        sin_y = math.sin(self.yaw)
        xr = x * cos_y - z * sin_y
        zr = x * sin_y + z * cos_y
        cos_p = math.cos(self.pitch)
        sin_p = math.sin(self.pitch)
        yr2 = y * cos_p - zr * sin_p
        zr2 = y * sin_p + zr * cos_p
        return xr, yr2, zr2

    def _get_body_rect(self):
        return (0, self.header_h,
                self.width(),
                self.height() - self.header_h - self.bar_h)

    def _base_scale(self):
        """
        球体尺寸系数: 0.32 × 1.4 = 0.448
        """
        bx, by, bw, bh = self._get_body_rect()
        short_side = min(bw, bh)
        return short_side * 0.448 * self.SIZE_MULT / self.R_BASE

    def _project(self, x, y, z):
        bx, by, bw, bh = self._get_body_rect()
        cx = bx + bw / 2.0
        cy = by + bh / 2.0
        base_scale = self._base_scale()
        perspective = 1.0 + z * 0.12
        sx = cx + x * base_scale * perspective
        sy = cy - y * base_scale * perspective
        return sx, sy, z

    def _get_node_screen(self, i):
        x, y, z = self._node_3d_now(i)
        pitch = 0.28 + 0.18 * math.sin(self.t * 0.3 + self.pitch_phase)
        self.pitch = pitch
        xr, yr, zr = self._rotate(x, y, z)
        sx, sy, depth = self._project(xr, yr, zr)
        return sx, sy, depth

    def _mix_color(self, base_r, base_g, base_b, alpha):
        intensity = self.hue_mix * self.BUSY_HUE_STRENGTH
        intensity = intensity * (1.0 + self.flash)
        intensity = max(0.0, min(1.0, intensity))
        red_r, red_g, red_b = 255, 70, 50
        r = int(base_r + (red_r - base_r) * intensity)
        g = int(base_g + (red_g - base_g) * intensity)
        b = int(base_b + (red_b - base_b) * intensity)
        return QColor(r, g, b, alpha)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        bx, by, bw, bh = self._get_body_rect()

        bg_intensity = self.hue_mix * self.BUSY_HUE_STRENGTH * (1.0 + self.flash)
        bg_intensity = max(0.0, min(1.0, bg_intensity))
        bg_r = int(20 * bg_intensity)
        painter.fillRect(self.rect(), QColor(bg_r, 0, 0))

        painter.save()
        painter.setClipRect(bx, by, bw, bh)

        cx = bx + bw / 2.0
        cy = by + bh / 2.0
        bf = self._breath_factor()
        sphere_radius_px = self._base_scale() * self.R_BASE * bf

        small_mode = (min(bw, bh) < 100)

        if not small_mode:
            rain_font = QFont("Consolas", 7, QFont.Bold)
            painter.setFont(rain_font)
            fm = painter.fontMetrics()
            row_h = fm.height()
            for col in self.rain_cols:
                col_x = col["x"] * w
                base_y = col["y"] * bh + by
                for k in range(col["length"]):
                    char_y = base_y - k * row_h
                    if char_y < by - row_h or char_y > by + bh + row_h:
                        continue
                    fade = 1.0 - (k / float(col["length"]))
                    alpha = int(col["alpha"] * fade)
                    d = math.sqrt((col_x - cx) ** 2 + (char_y - cy) ** 2)
                    if d < sphere_radius_px * 0.9:
                        absorb = d / (sphere_radius_px * 0.9)
                        alpha = int(alpha * (absorb ** 1.6))
                    if alpha <= 0:
                        continue
                    color = self._mix_color(60, 110, 160, alpha)
                    painter.setPen(color)
                    painter.drawText(int(col_x), int(char_y), col["chars"][k])

        painter.setPen(Qt.NoPen)
        for s in self.bg_stars_far:
            twinkle = 0.5 + 0.5 * math.sin(self.t * s["twinkle_speed"] + s["twinkle_phase"])
            alpha = int(s["alpha"] * (0.5 + 0.5 * twinkle))
            px = s["x"] * w
            py = by + s["y"] * bh
            d = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if d < sphere_radius_px * 0.9:
                absorb = d / (sphere_radius_px * 0.9)
                alpha = int(alpha * (absorb ** 1.6))
            if alpha <= 0:
                continue
            painter.setBrush(self._mix_color(150, 170, 200, alpha))
            painter.drawEllipse(QPointF(px, py), s["size"], s["size"])

        halo_radius = min(sphere_radius_px * 1.2, max(bw, bh) * 1.2)
        if halo_radius > 0:
            halo_grad = QRadialGradient(QPointF(cx, cy), halo_radius)
            halo_grad.setColorAt(0.0, QColor(0, 0, 0, 160))
            halo_grad.setColorAt(0.7, QColor(0, 0, 0, 80))
            halo_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(bx, by, bw, bh, halo_grad)

        node_screen = [self._get_node_screen(i) for i in range(self.NUM_NODES)]

        elements = []
        for (a, b) in self.connections:
            x1, y1, d1 = node_screen[a]
            x2, y2, d2 = node_screen[b]
            elements.append(("line", QPointF(x1, y1), QPointF(x2, y2), (d1 + d2) / 2.0))
        for i in range(self.NUM_NODES):
            x, y, d = node_screen[i]
            elements.append(("node", QPointF(x, y), None, d))

        for tr in self.travelers:
            path = tr["path"]
            if tr.get("fading", False):
                seg = len(path) - 2
                x1, y1, d1 = node_screen[path[seg]]
                x2, y2, d2 = node_screen[path[seg + 1]]
                px, py, pd = x2, y2, d2
            elif tr.get("fade_in", False):
                x1, y1, d1 = node_screen[path[0]]
                px, py, pd = x1, y1, d1
            else:
                seg = tr["seg"]; t = tr["t"]
                if seg >= len(path) - 1:
                    continue
                x1, y1, d1 = node_screen[path[seg]]
                x2, y2, d2 = node_screen[path[seg + 1]]
                px = x1 + (x2 - x1) * t
                py = y1 + (y2 - y1) * t
                pd = d1 + (d2 - d1) * t
            elements.append(("traveler", QPointF(px, py), tr["text"], pd, tr["fade_alpha"]))

        elements.sort(key=lambda e: e[3])

        if not small_mode:
            painter.setFont(QFont("Consolas", 7, QFont.Bold))
            fm2 = painter.fontMetrics()
        else:
            fm2 = None

        for elem in elements:
            kind = elem[0]
            p = elem[1]
            depth = elem[3]
            tn = max(0.0, min(1.0, (depth + 1.0) / 2.0))
            alpha_scale = 0.15 + 0.85 * tn

            if kind == "line":
                p2 = elem[2]
                alpha = int(140 * alpha_scale)
                width = 0.35 + 0.45 * tn
                painter.setPen(QPen(self._mix_color(170, 195, 225, alpha), width))
                painter.drawLine(p, p2)

            elif kind == "node":
                alpha = int(255 * alpha_scale)
                size = 0.7 + 0.9 * tn
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._mix_color(255, 255, 255, alpha))
                painter.drawEllipse(p, size, size)

            elif kind == "traveler":
                text = elem[2]
                fade_alpha = elem[4]
                alpha = int(255 * alpha_scale * fade_alpha)
                if alpha <= 0:
                    continue
                size = 1.4 + 0.9 * tn
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._mix_color(255, 255, 255, alpha))
                painter.drawEllipse(p, size, size)
                if text and fm2 is not None:
                    tw = fm2.horizontalAdvance(text)
                    painter.setPen(self._mix_color(255, 255, 255, alpha))
                    painter.drawText(int(p.x() - tw / 2), int(p.y() - 6), text)

        painter.restore()

        header_color = self._mix_color(0xd4, 0x62, 0x1e, 255)
        painter.fillRect(0, 0, w, self.header_h, header_color)

        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        painter.setPen(QColor("#000000"))
        painter.drawText(6, self.header_h - 4, self.header_left)

        fm_header = painter.fontMetrics()
        rw = fm_header.horizontalAdvance(self.header_right)
        if rw + 12 < w * 0.6:
            painter.drawText(w - rw - 6, self.header_h - 4, self.header_right)

        bar_y = h - self.bar_h
        painter.fillRect(0, bar_y, w, self.bar_h, QColor("#000000"))
        painter.setPen(QPen(QColor("#27272a"), 1.0))
        painter.drawRect(0, bar_y, w - 1, self.bar_h - 1)
        fill_w = int((w - 4) * self.progress)
        if fill_w > 0:
            bar_color = self._mix_color(0x00, 0xa8, 0xff, 255)
            painter.fillRect(2, bar_y + 2, fill_w, self.bar_h - 4, bar_color)
            head_color = self._mix_color(0xa0, 0xe0, 0xff, 255)
            painter.fillRect(2 + fill_w - 2, bar_y + 2, 2, self.bar_h - 4, head_color)


class DemoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("状态指示球体 - v48")
        self.resize(420, 420)
        self.setStyleSheet("QWidget { background-color: #0b0b0e; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # 外层 frame 不再限制尺寸，让 widget 自己决定
        frame = QFrame()
        frame.setStyleSheet("QFrame { background-color: #000; border: 1px solid #27272f; }")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)

        self.widget = IndicatorSphere()
        fl.addWidget(self.widget)

        layout.addWidget(frame, alignment=Qt.AlignCenter)
        layout.addStretch()

        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self._advance_progress)
        self.progress_timer.start(100)
        self.progress_val = 0.0

    def _advance_progress(self):
        self.progress_val += 0.005
        if self.progress_val > 1.0:
            self.progress_val = 0.0
        self.widget.set_progress(self.progress_val)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DemoWindow()
    win.show()
    sys.exit(app.exec())