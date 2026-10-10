# -*- coding: utf-8 -*-
"""
boot_beep.py - 开机自检蜂鸣 (内存 WAV 合成, 零第三方依赖)

比 winsound.Beep 强在哪:
  Beep 每次调用要重启内核蜂鸣器, 两下之间必有物理缝, sleep 压到 0 也去不掉。
  这里直接合成一段 WAV 丢给 PlaySound(SND_MEMORY), 两声之间的静默是音频流里的
  零采样, 间隔精确到毫秒, 想多紧有多紧。
"""

import io
import math
import struct
import threading

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


def _make_beep_wav(freq=2000, beep_ms=100, gap_ms=40, repeat=2, rate=44100, volume=0.5):
    """合成 repeat 声 freq 短音, 每声 beep_ms, 中间 gap_ms 静默, 返回完整 WAV 字节。

    freq     : 音高 Hz
    beep_ms  : 每声时长 ms
    gap_ms   : 两声之间的静默 ms
    repeat   : 响几声
    rate     : 采样率
    volume   : 0.0~1.0 音量 (线性)
    """
    peak = int(32767 * max(0.0, min(1.0, volume)))
    env_len = max(1, int(rate * 0.004))  # 4ms 淡入淡出, 消除爆音
    beep_n = int(rate * beep_ms / 1000)
    gap_n = int(rate * gap_ms / 1000)

    frames = []
    pack = struct.Struct('<h').pack
    two_pi_f = 2.0 * math.pi * freq / rate

    for _ in range(repeat):
        for i in range(beep_n):
            env = 1.0
            if i < env_len:
                env = i / env_len
            elif i > beep_n - env_len:
                env = (beep_n - i) / env_len
            v = int(peak * env * math.sin(two_pi_f * i))
            frames.append(pack(v))
        for _ in range(gap_n):
            frames.append(pack(0))

    data = b''.join(frames)
    n = len(data)
    hdr = (
        b'RIFF' + struct.pack('<I', 36 + n) + b'WAVE'
        + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16)
        + b'data' + struct.pack('<I', n)
    )
    return hdr + data


def play_boot_beep(freq=2000, beep_ms=100, gap_ms=40, repeat=2, volume=0.5):
    """在后台线程播放开机蜂鸣, 不阻塞调用方 (GUI 线程)。

    无 winsound (非 Windows) 时静默返回, 绝不抛异常。
    """
    if not HAS_WINSOUND:
        return

    def _worker():
        try:
            wav = _make_beep_wav(freq=freq, beep_ms=beep_ms,
                                 gap_ms=gap_ms, repeat=repeat, volume=volume)
            winsound.PlaySound(wav, winsound.SND_MEMORY)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


if __name__ == '__main__':
    # 独立试听: 改参数直接跑 python boot_beep.py
    import time
    print('滴滴两声 (2000Hz / 100ms / 间隔40ms)...')
    play_boot_beep(freq=2000, beep_ms=100, gap_ms=40, repeat=2)
    time.sleep(1.0)
    print('三声连击 (1500Hz / 60ms / 间隔25ms)...')
    play_boot_beep(freq=1500, beep_ms=60, gap_ms=25, repeat=3)
    time.sleep(1.0)
    print('完成')