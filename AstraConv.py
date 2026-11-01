# -*- coding: utf-8 -*-
"""
AstraConv v0.0.7 — by black
MIDI / Audio → клавиатурная раскладка
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from bisect import bisect_right
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from PyQt6 import QtWidgets, QtCore, QtGui


# ══════════════════════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════
LOG_FILE = "astraconv.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("AstraConv")


# ══════════════════════════════════════════════════════════════════════
#  ENGINE
# ══════════════════════════════════════════════════════════════════════
CTRL_PREFIX = "~"
G0_KEYS = "1234567890qwertyuiopasdfghjklzxcvbnm"
G1_LOW = "1234567890qwert"
G1_HIGH = "yuiopasdfghj"
SHIFT_DIGITS = dict(zip("1234567890", "!@#$%^&*()"))


def _build_layout():
    white = [12 * (o + 1) + s for o in range(2, 7) for s in (0, 2, 4, 5, 7, 9, 11)]
    white.append(96)
    g0 = dict(zip(white, G0_KEYS))
    main = dict(g0)
    for p, k in g0.items():
        if p + 1 not in g0:
            main[p + 1] = SHIFT_DIGITS.get(k, k.upper())
    full = dict(main)
    for p, k in zip(range(21, 36), G1_LOW):
        full[p] = CTRL_PREFIX + k
    for p, k in zip(range(97, 109), G1_HIGH):
        full.setdefault(p, CTRL_PREFIX + k)
    return main, full


TOK_MAIN, TOK_FULL = _build_layout()
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def midi_to_name(n):
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def fold_pitch(p):
    while p < 36:
        p += 12
    while p > 97:
        p -= 12
    return p


def _vlq(data, i):
    v = 0
    for _ in range(5):
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return v, i


def read_midi(path, include_drums=False):
    data = Path(path).read_bytes()
    if data[:4] != b"MThd":
        raise ValueError(f"{path}: не MIDI-файл")
    hlen = int.from_bytes(data[4:8], "big")
    _fmt, _ntrk, div = struct.unpack(">HHH", data[8:14])
    pos = 8 + hlen
    tempos = [(0, 500000)]
    events = []
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        clen = int.from_bytes(data[pos + 4:pos + 8], "big")
        body = data[pos + 8:pos + 8 + clen]
        pos += 8 + clen
        if cid != b"MTrk":
            continue
        i, tick, status, n = 0, 0, 0, len(body)
        try:
            while i < n:
                d, i = _vlq(body, i)
                tick += d
                if body[i] >= 0x80:
                    status = body[i]
                    i += 1
                if status == 0xFF:
                    mtype = body[i]
                    ln, j = _vlq(body, i + 1)
                    if mtype == 0x51 and ln == 3:
                        tempos.append((tick, int.from_bytes(body[j:j + 3], "big")))
                    i = j + ln
                    status = 0
                    if mtype == 0x2F:
                        break
                elif status in (0xF0, 0xF7):
                    ln, j = _vlq(body, i)
                    i = j + ln
                    status = 0
                elif status < 0x80:
                    break
                else:
                    kind, ch = status & 0xF0, status & 0x0F
                    if kind in (0xC0, 0xD0):
                        i += 1
                    else:
                        a, b = body[i] & 0x7F, body[i + 1] & 0x7F
                        i += 2
                        if kind == 0x90 and b > 0:
                            events.append((tick, 1, ch, a, b))
                        elif kind in (0x80, 0x90):
                            events.append((tick, 0, ch, a, 0))
        except IndexError:
            pass

    if div & 0x8000:
        tps = (256 - (div >> 8)) * (div & 0xFF)

        def to_sec(t):
            return t / tps
    else:
        tpq = div or 480
        tempos.sort(key=lambda x: x[0])
        ticks, secs, tempo_at = [0], [0.0], [500000]
        for tk_, tp in tempos:
            if tk_ == ticks[-1]:
                tempo_at[-1] = tp
            else:
                secs.append(secs[-1] + (tk_ - ticks[-1]) * tempo_at[-1] / 1e6 / tpq)
                ticks.append(tk_)
                tempo_at.append(tp)

        def to_sec(t):
            idx = bisect_right(ticks, t) - 1
            return secs[idx] + (t - ticks[idx]) * tempo_at[idx] / 1e6 / tpq

    events.sort(key=lambda e: e[0])
    active = defaultdict(deque)
    notes = []
    end_t = 0.0
    for tick, is_on, ch, pitch, vel in events:
        if ch == 9 and not include_drums:
            continue
        t = to_sec(tick)
        end_t = t
        if is_on:
            active[(ch, pitch)].append((t, vel))
        else:
            st = active.get((ch, pitch))
            if st:
                on, v = st.popleft()
                notes.append((on, t, pitch, v))
    for (ch, pitch), st in active.items():
        for on, v in st:
            notes.append((on, max(end_t, on), pitch, v))
    notes.sort()
    return notes


BD_CKPT = Path.home() / "piano_transcription_inference_data" / \
    "note_F1=0.9677_pedal_F1=0.9186.pth"
BD_URL = ("https://zenodo.org/record/4034264/files/"
          "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1")


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg не найден. Установите его или: pip install imageio-ffmpeg")


def extract_audio(src, wav):
    cmd = [find_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src),
           "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(wav)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not Path(wav).exists():
        raise RuntimeError("ffmpeg: не смог извлечь звук\n" + r.stderr.strip())


def pick_backend(choice):
    have_tk = importlib.util.find_spec("transkun") is not None
    have_bd = importlib.util.find_spec("piano_transcription_inference") is not None
    if choice == "auto":
        if have_tk:
            return "transkun"
        if have_bd:
            return "bytedance"
        raise RuntimeError(
            "Для аудио/видео нужна нейросеть:\n"
            "  pip install transkun\n"
            "  pip install piano_transcription_inference")
    if choice == "transkun" and not have_tk:
        raise RuntimeError("Transkun не установлен: pip install transkun")
    if choice == "bytedance" and not have_bd:
        raise RuntimeError("Не установлен: pip install piano_transcription_inference")
    return choice


def pick_device(choice):
    if choice != "auto":
        return choice
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def transcribe_audio(src, backend_choice, device_choice, log=print):
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        mid = Path(td) / "transcribed.mid"
        backend = pick_backend(backend_choice)
        device = pick_device(device_choice)
        log("Извлекаю звук (ffmpeg)…")
        extract_audio(src, wav)

        if backend == "transkun":
            log(f"Распознаю ноты (Transkun, {device}) — может занять минуты…")
            exe = shutil.which("transkun")
            if not exe:
                raise RuntimeError("CLI 'transkun' не найден в PATH")
            r = subprocess.run([exe, str(wav), str(mid), "--device", device], check=False)
            if r.returncode != 0 or not Path(mid).exists():
                raise RuntimeError("Transkun завершился с ошибкой")
        else:
            if not (BD_CKPT.exists() and BD_CKPT.stat().st_size > 1.6e8):
                log("Скачиваю веса ByteDance (~165 МБ), один раз…")
                BD_CKPT.parent.mkdir(parents=True, exist_ok=True)
                part = BD_CKPT.with_suffix(".part")
                urllib.request.urlretrieve(BD_URL, part)
                part.replace(BD_CKPT)
            from piano_transcription_inference import (
                PianoTranscription, sample_rate, load_audio)
            log(f"Распознаю ноты (ByteDance, {device})…")
            with contextlib.redirect_stdout(sys.stderr):
                audio, _ = load_audio(str(wav), sr=sample_rate, mono=True)
                PianoTranscription(
                    device=device, checkpoint_path=str(BD_CKPT)
                ).transcribe(audio, str(mid))

        if not Path(mid).exists():
            raise RuntimeError("нейросеть не создала MIDI-файл")
        return read_midi(mid, include_drums=True)


def best_phase(times, step, samples=96):
    if len(times) > 20000:
        times = times[::len(times) // 20000 + 1]
    best_err, best_ph = float("inf"), 0.0
    for k in range(samples):
        ph = step * k / samples
        err = 0.0
        for t in times:
            r = (t - ph) % step
            err += r if r < step - r else step - r
        if err < best_err:
            best_err, best_ph = err, ph
    return best_ph


def quantize(notes, step, chord_window):
    window = min(chord_window, step / 2)
    clusters, i, n = [], 0, len(notes)
    while i < n:
        t0 = notes[i][0]
        j = i + 1
        while j < n and notes[j][0] - t0 <= window:
            j += 1
        grp = notes[i:j]
        clusters.append((sum(x[0] for x in grp) / len(grp), grp))
        i = j
    phase = best_phase([c[0] for c in clusters], step)
    slots = defaultdict(dict)
    err_sum = err_max = 0.0
    for t, grp in clusters:
        k = round((t - phase) / step)
        grid_t = phase + k * step
        for on, off, p, v in grp:
            e = abs(on - grid_t)
            err_sum += e
            err_max = max(err_max, e)
            dur = off - on
            cur = slots[k].get(p)
            slots[k][p] = (v, dur) if cur is None else (
                max(cur[0], v), max(cur[1], dur))
    return slots, {"err_mean": err_sum / max(n, 1), "err_max": err_max}


def trim_chord(items, limit):
    pitches = sorted(items)
    if len(pitches) <= limit:
        return pitches
    keep = {pitches[-1]}
    if limit >= 2:
        keep.add(pitches[0])
    rest = sorted((p for p in pitches if p not in keep),
                  key=lambda p: items[p][0] * (0.25 + min(items[p][1], 1.0)),
                  reverse=True)
    for p in rest:
        if len(keep) >= limit:
            break
        keep.add(p)
    return sorted(keep)


def render_tokens(slots, table, rests, max_rests, max_chord):
    tokens, prev, trimmed, chords = [], None, 0, 0
    for k in sorted(slots):
        if rests and prev is not None and k - prev > 1:
            tokens += ["|"] * min(k - prev - 1, max_rests)
        prev = k
        items = slots[k]
        pitches = trim_chord(items, max_chord) if max_chord else sorted(items)
        trimmed += len(items) - len(pitches)
        keys = "".join(table[p] for p in pitches)
        if len(pitches) > 1:
            chords += 1
            keys = f"[{keys}]"
        tokens.append(keys)
    return tokens, trimmed, chords


# ══════════════════════════════════════════════════════════════════════
#  ТЕМЫ
# ══════════════════════════════════════════════════════════════════════
def _to_rgba(hex_color, alpha):
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"


def _mk_theme(key, name_key, is_dark, bg, bg_alt, panel, panel_alt, inp,
              text, text_muted, text_dim, accent, accent_hover, accent_press,
              accent_text, border):
    return {
        "key": key, "name_key": name_key, "is_dark": is_dark,
        "bg": bg, "bg_alt": bg_alt,
        "panel": panel, "panel_alt": panel_alt, "input": inp,
        "text": text, "text_muted": text_muted, "text_dim": text_dim,
        "accent": accent, "accent_hover": accent_hover, "accent_press": accent_press,
        "accent_text": accent_text,
        "accent_soft": _to_rgba(accent, 0.10),
        "border": border, "border_accent": _to_rgba(accent, 0.30),
        "selection": _to_rgba(accent, 0.22),
        "scrollbar": panel_alt, "scrollbar_hover": border,
        "danger": "#e05a4d", "success": "#5cb85c",
    }


THEMES = {
    "gold":   _mk_theme("gold",   "Золото",       True, "#0a0a0a", "#0f0f0f", "#151515", "#1c1c1c", "#181818", "#f5f3f1", "#8a8a8a", "#5a5a5a", "#d4af37", "#ffd86a", "#b8942a", "#0a0a0a", "#262626"),
    "sand":   _mk_theme("sand",   "Песок",       False, "#f5efe1", "#ece4d0", "#ffffff", "#faf6ec", "#ffffff", "#2b2418", "#7c7160", "#ab9f88", "#a67c00", "#c99612", "#8a6508", "#ffffff", "#e6dcc3"),
    "blue":   _mk_theme("blue",   "Синий",        True, "#08121e", "#0b1824", "#0f1e2e", "#142838", "#101f2d", "#e8f2ff", "#7a90a8", "#4a5d72", "#4ea3ff", "#82c0ff", "#2d7ed4", "#001018", "#1a2e44"),
    "purple": _mk_theme("purple", "Фиолетовый",  True, "#100a1e", "#160f28", "#1d1433", "#241a40", "#1a1230", "#f0e8ff", "#9488b0", "#5e5578", "#a060ff", "#c896ff", "#7d3fd8", "#0a0618", "#2a1f4a"),
    "green":  _mk_theme("green",  "Зелёный",      True, "#081410", "#0c1c16", "#10281e", "#163428", "#122c22", "#e8fff0", "#80a890", "#4a6a58", "#4dcc80", "#80e8a0", "#2da060", "#041810", "#1c3e30"),
    "pink":   _mk_theme("pink",   "Розовый",      True, "#1a0812", "#240c1a", "#2e1022", "#3a162c", "#2a0e20", "#ffe8f2", "#b088a0", "#755868", "#ff5ca8", "#ff8cc4", "#d43a82", "#180610", "#3e1a2e"),
    "red":    _mk_theme("red",    "Красный",      True, "#1a0808", "#240c0c", "#2e1010", "#3a1616", "#2a0e0e", "#ffe8e8", "#b08888", "#755858", "#ff5050", "#ff8080", "#d43030", "#180404", "#3e1a1a"),
    "cyan":   _mk_theme("cyan",   "Голубой",      True, "#081618", "#0c1c20", "#10282e", "#163438", "#122c30", "#e8feff", "#80a8b0", "#4a6870", "#3cd0e0", "#70e8f0", "#20a0b0", "#041418", "#1c3a3e"),
    "orange": _mk_theme("orange", "Оранжевый",    True, "#1a1008", "#24160c", "#2e1c10", "#3a2416", "#2a1a0e", "#ffeee0", "#b09880", "#756858", "#ff8c30", "#ffb060", "#d46a10", "#180c04", "#3e2818"),
    "mono":   _mk_theme("mono",   "Моно",         True, "#0a0a0a", "#101010", "#161616", "#1e1e1e", "#181818", "#f0f0f0", "#909090", "#606060", "#d0d0d0", "#ffffff", "#a8a8a8", "#0a0a0a", "#282828"),
}

_current_theme_key = "gold"


def get_theme():
    return THEMES.get(_current_theme_key, THEMES["gold"])


def _parse_color(s):
    try:
        if s.startswith('#'):
            h = s[1:]
            if len(h) == 3:
                h = ''.join(c * 2 for c in h)
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if s.startswith('rgba'):
            p = s[5:-1].split(',')
            return (int(float(p[0])), int(float(p[1])), int(float(p[2])),
                    int(float(p[3]) * 255))
        if s.startswith('rgb'):
            p = s[4:-1].split(',')
            return (int(float(p[0])), int(float(p[1])), int(float(p[2])), 255)
    except Exception:
        pass
    return (255, 255, 255, 255)


def _rgba_to_str(c):
    r, g, b, a = (max(0, min(255, int(x))) for x in c)
    if a >= 255:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r},{g},{b},{a / 255:.3f})"


def _lerp_rgba(c1, c2, t):
    return tuple(a + (b - a) * t for a, b in zip(c1, c2))


def build_qss(t):
    return f"""
    QWidget {{
        background: {t['bg']}; color: {t['text']};
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
        font-size: 9pt;
    }}
    QToolTip {{
        background: {t['panel']}; color: {t['text']};
        border: 1px solid {t['border_accent']};
        padding: 4px 8px; border-radius: 4px;
    }}
    QPushButton {{
        background: {t['panel_alt']}; color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 7px; padding: 6px 14px;
        min-height: 20px; font-weight: 500;
    }}
    QPushButton:hover {{
        background: {t['panel']}; border-color: {t['border_accent']};
    }}
    QPushButton:pressed {{ background: {t['bg_alt']}; }}
    QPushButton:disabled {{
        color: {t['text_dim']}; border-color: {t['border']};
        background: {t['bg_alt']};
    }}
    QPushButton[role="primary"] {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {t['accent_hover']}, stop:1 {t['accent']});
        color: {t['accent_text']};
        border: 1px solid {t['accent']}; font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{
        background: {t['accent_hover']}; border-color: {t['accent_hover']};
    }}
    QPushButton[role="primary"]:pressed {{ background: {t['accent_press']}; }}
    QPushButton[role="icon"] {{
        background: transparent; border: 1px solid transparent;
        border-radius: 7px; padding: 0 6px; font-size: 12pt;
    }}
    QPushButton[role="icon"]:hover {{
        background: {t['accent_soft']}; border-color: {t['border_accent']};
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
        background: {t['input']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 7px;
        padding: 6px 9px;
        selection-background-color: {t['accent']};
        selection-color: {t['accent_text']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {t['accent']}; }}
    QComboBox {{
        background: {t['input']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 7px;
        padding: 5px 10px; min-height: 22px;
    }}
    QComboBox:hover {{ border-color: {t['border_accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {t['panel']}; color: {t['text']};
        border: 1px solid {t['border_accent']}; border-radius: 7px;
        selection-background-color: {t['selection']};
        selection-color: {t['text']}; outline: none; padding: 4px;
    }}
    QCheckBox {{ color: {t['text']}; spacing: 8px; padding: 2px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1.5px solid {t['border_accent']};
        border-radius: 4px; background: {t['input']};
    }}
    QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
    QListWidget, QTreeWidget, QTableWidget {{
        background: {t['panel']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 10px;
        outline: none; padding: 4px;
    }}
    QListWidget::item {{ padding: 6px 10px; border-radius: 5px; min-height: 18px; }}
    QListWidget::item:hover {{ background: {t['panel_alt']}; }}
    QListWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
    QTabWidget::pane {{
        border: 1px solid {t['border']}; border-radius: 10px;
        top: -1px; background: {t['panel']};
    }}
    QTabBar::tab {{
        background: transparent; color: {t['text_muted']};
        padding: 8px 18px; border: none;
        border-bottom: 2px solid transparent;
        margin-right: 2px; font-weight: 500;
    }}
    QTabBar::tab:hover {{ color: {t['text']}; }}
    QTabBar::tab:selected {{ color: {t['accent']}; border-bottom: 2px solid {t['accent']}; }}
    QGroupBox {{
        border: 1px solid {t['border']}; border-radius: 10px;
        margin-top: 14px; padding-top: 12px;
        color: {t['text_muted']}; font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 14px;
        padding: 0 6px; color: {t['accent']};
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['scrollbar']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['scrollbar_hover']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; }}
    QScrollBar::handle:horizontal {{ background: {t['scrollbar']}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t['scrollbar_hover']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    QFrame#titlebar {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {t['bg_alt']}, stop:1 {t['bg']});
        border: none; border-bottom: 1px solid {t['border']};
    }}
    QFrame#accent_line {{ background: {t['accent']}; max-height: 1px; min-height: 1px; border: none; }}
    QLabel#app_title {{ font-size: 13pt; font-weight: 700; color: {t['accent']}; background: transparent; }}
    QLabel#app_credit {{ color: {t['text_muted']}; font-size: 9pt; background: transparent; }}
    QLabel#section_label {{
        color: {t['text_muted']}; font-size: 8pt; font-weight: 700;
        letter-spacing: 2px; background: transparent;
    }}
    QLabel#status_normal {{ color: {t['text_muted']}; font-size: 8pt; background: transparent; }}
    QLabel#status_accent {{ color: {t['accent']}; font-size: 9pt; font-weight: 600; background: transparent; }}
    QLabel#status_pos {{
        color: {t['text_dim']}; font-size: 8pt;
        font-family: 'Consolas', 'Courier New', monospace;
        background: transparent;
    }}
    QTextEdit#output {{
        background: {t['input']};
        border: 1px solid {t['border']}; border-radius: 10px;
        padding: 10px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 10pt;
    }}
    QDialog {{ background: {t['bg']}; }}
    QMessageBox {{ background: {t['panel']}; }}
    QMessageBox QLabel {{ color: {t['text']}; }}
    QProgressBar {{
        background: {t['input']}; border: 1px solid {t['border']};
        border-radius: 5px; height: 8px;
        text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t['accent']}, stop:1 {t['accent_hover']});
        border-radius: 4px;
    }}
    """


def apply_theme(app):
    if app is None:
        return
    app.setStyleSheet(build_qss(get_theme()))


# ══════════════════════════════════════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════════════════════════════════════
SETTINGS_FILE = "astraconv_settings.json"


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  HOVER BUTTON
# ══════════════════════════════════════════════════════════════════════
class HoverButton(QtWidgets.QPushButton):
    _HOVER_OPACITY = 0.82
    _DURATION = 140

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._eff = QtWidgets.QGraphicsOpacityEffect(self)
        self._eff.setOpacity(1.0)
        self.setGraphicsEffect(self._eff)
        self._anim = QtCore.QPropertyAnimation(self._eff, b"opacity")
        self._anim.setDuration(self._DURATION)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def _animate(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._eff.opacity())
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):
        self._animate(self._HOVER_OPACITY)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(1.0)
        super().leaveEvent(event)


# ══════════════════════════════════════════════════════════════════════
#  ДИАЛОГ СВОЕЙ ТЕМЫ
# ══════════════════════════════════════════════════════════════════════
class CustomThemeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Свой цвет темы")
        self.setMinimumSize(380, 260)
        v = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.acc_btn = self._color_button("#d4af37")
        self.bg_btn = self._color_button("#0a0a0a")
        self.text_btn = self._color_button("#f5f3f1")
        form.addRow("Акцент:", self.acc_btn)
        form.addRow("Фон:", self.bg_btn)
        form.addRow("Текст:", self.text_btn)
        v.addLayout(form)
        v.addStretch()
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _color_button(self, initial):
        b = HoverButton(initial)
        b._color = initial
        b.clicked.connect(lambda: self._pick(b))
        b.setStyleSheet(f"background: {initial}; color: {initial}; min-height: 28px;")
        return b

    def _pick(self, btn):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(btn._color), self)
        if c.isValid():
            hx = c.name()
            btn._color = hx
            btn.setText(hx)
            btn.setStyleSheet(f"background: {hx}; color: {hx}; min-height: 28px;")

    def get_colors(self):
        return self.acc_btn._color, self.bg_btn._color, self.text_btn._color


# ══════════════════════════════════════════════════════════════════════
#  ДИАЛОГ ЛОГА (рабочий)
# ══════════════════════════════════════════════════════════════════════
class LogViewerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self.setWindowTitle("Лог")
        self.setMinimumSize(860, 560)
        v = QtWidgets.QVBoxLayout(self)

        self.tabs = QtWidgets.QTabWidget()

        self.session_edit = QtWidgets.QPlainTextEdit()
        self.session_edit.setReadOnly(True)
        self.session_edit.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 9pt;")
        self.tabs.addTab(self.session_edit, "Текущая сессия")

        self.file_edit = QtWidgets.QPlainTextEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 9pt;")
        self.tabs.addTab(self.file_edit, f"Файл {LOG_FILE}")

        v.addWidget(self.tabs)

        row = QtWidgets.QHBoxLayout()
        refresh_btn = HoverButton("Обновить")
        refresh_btn.clicked.connect(self._refresh)
        row.addWidget(refresh_btn)

        copy_btn = HoverButton("Копировать")
        copy_btn.clicked.connect(self._copy_current)
        row.addWidget(copy_btn)

        export_btn = HoverButton("Сохранить…")
        export_btn.clicked.connect(self._export)
        row.addWidget(export_btn)

        clear_btn = HoverButton("Очистить")
        clear_btn.clicked.connect(self._clear)
        row.addWidget(clear_btn)

        row.addStretch()

        close_btn = HoverButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)

        v.addLayout(row)

        self._refresh()

    def _refresh(self):
        # сессия
        lines = []
        if self._parent is not None and hasattr(self._parent, "log_lines"):
            lines = self._parent.log_lines
        self.session_edit.setPlainText("\n".join(lines) if lines else "(пусто)")
        sb = self.session_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

        # файл
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    content = f.readlines()
                self.file_edit.setPlainText("".join(content[-3000:]))
                sb2 = self.file_edit.verticalScrollBar()
                sb2.setValue(sb2.maximum())
            except Exception as e:
                self.file_edit.setPlainText(f"Ошибка чтения файла: {e}")
        else:
            self.file_edit.setPlainText("(файл ещё не создан)")

    def _current_text(self):
        idx = self.tabs.currentIndex()
        return (self.session_edit if idx == 0 else self.file_edit).toPlainText()

    def _copy_current(self):
        QtWidgets.QApplication.clipboard().setText(self._current_text())

    def _export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить лог", "astraconv_export.log", "*.log;;*.txt;;Все файлы (*)")
        if path:
            try:
                Path(path).write_text(self._current_text(), encoding="utf-8")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))

    def _clear(self):
        if self._parent is not None and hasattr(self._parent, "log_lines"):
            self._parent.log_lines.clear()
        self._refresh()


# ══════════════════════════════════════════════════════════════════════
#  ГЛАВНОЕ ОКНО
# ══════════════════════════════════════════════════════════════════════
class AstraConvWindow(QtWidgets.QWidget):
    _log_signal = QtCore.pyqtSignal(str, str)   # level, msg
    _done_signal = QtCore.pyqtSignal(str, str, object)
    _err_signal = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AstraConv v0.0.7 — by black")
        self.setMinimumSize(1080, 700)
        self.setWindowOpacity(0.0)

        self.settings = load_settings()
        global _current_theme_key
        if self.settings.get("theme") in THEMES:
            _current_theme_key = self.settings["theme"]

        self.midi_path = ""
        self.slots = None
        self.step_sec = 0.0
        self.bpm = 120.0
        self.div = 4
        self.processing = False
        self.log_lines = []
        self._theme_anim = None

        self._log_signal.connect(self._on_log)
        self._done_signal.connect(self._on_done)
        self._err_signal.connect(self._on_error)

        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen.width() // 2 - 640, screen.height() // 2 - 400, 1280, 800)

        self._build_ui()
        apply_theme(QtWidgets.QApplication.instance())
        QtCore.QTimer.singleShot(80, self._fade_in)

        logger.info("AstraConv v0.0.7 запущен")
        self._log_local("INFO", "AstraConv v0.0.7 — by black")
        self._log_local("INFO", "Приложение готово к работе")

    # ── локальное логирование ───────────────────────────────────────
    def _log_local(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {level}: {msg}"
        self.log_lines.append(entry)
        if len(self.log_lines) > 3000:
            self.log_lines = self.log_lines[-1500:]

    def _on_log(self, level, msg):
        self._log_local(level, msg)
        if level == "ERROR":
            self.status_label.setText(f"❌ {msg}")
        elif level == "WARNING":
            self.status_label.setText(f"⚠️ {msg}")
        else:
            self.status_label.setText(msg)

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tb = QtWidgets.QFrame()
        tb.setObjectName("titlebar")
        tb.setFixedHeight(46)
        tbl = QtWidgets.QHBoxLayout(tb)
        tbl.setContentsMargins(18, 0, 14, 0)
        tbl.setSpacing(8)

        title = QtWidgets.QLabel("AstraConv")
        title.setObjectName("app_title")
        tbl.addWidget(title)

        credit = QtWidgets.QLabel("— by black")
        credit.setObjectName("app_credit")
        tbl.addWidget(credit)

        tbl.addStretch()

        self.theme_btn = self._icon_btn("🎨", "Сменить тему")
        self.theme_btn.clicked.connect(self._cycle_theme)
        tbl.addWidget(self.theme_btn)

        self.custom_theme_btn = self._icon_btn("🖌", "Свой цвет темы")
        self.custom_theme_btn.clicked.connect(self._open_custom_theme)
        tbl.addWidget(self.custom_theme_btn)

        self.log_btn = self._icon_btn("📋", "Лог")
        self.log_btn.clicked.connect(self._show_log)
        tbl.addWidget(self.log_btn)

        self.about_btn = self._icon_btn("ⓘ", "О программе")
        self.about_btn.clicked.connect(self._show_about)
        tbl.addWidget(self.about_btn)

        root.addWidget(tb)

        accent = QtWidgets.QFrame()
        accent.setObjectName("accent_line")
        accent.setFixedHeight(1)
        root.addWidget(accent)

        body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(10)

        file_row = QtWidgets.QHBoxLayout()
        file_row.setSpacing(8)
        self.file_label = QtWidgets.QLabel("Файл не выбран")
        self.file_label.setObjectName("status_normal")
        file_row.addWidget(self.file_label, 1)
        open_btn = HoverButton("📂 Открыть…")
        open_btn.clicked.connect(self._open_file)
        file_row.addWidget(open_btn)
        bl.addLayout(file_row)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_process_tab(), "Обработка")
        self.tabs.addTab(self._build_settings_tab(), "Настройки")
        bl.addWidget(self.tabs, 1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        bl.addWidget(self.progress)

        root.addWidget(body, 1)

        sb = QtWidgets.QFrame()
        sb.setFixedHeight(28)
        sbl = QtWidgets.QHBoxLayout(sb)
        sbl.setContentsMargins(18, 0, 18, 0)
        self.status_label = QtWidgets.QLabel("Готов")
        self.status_label.setObjectName("status_accent")
        sbl.addWidget(self.status_label)
        self.info_label = QtWidgets.QLabel("")
        self.info_label.setObjectName("status_normal")
        sbl.addWidget(self.info_label)
        sbl.addStretch()
        self.pos_label = QtWidgets.QLabel("0/0")
        self.pos_label.setObjectName("status_pos")
        sbl.addWidget(self.pos_label)
        root.addWidget(sb)

    def _build_process_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        grp = QtWidgets.QGroupBox("Параметры обработки")
        g = QtWidgets.QGridLayout(grp)
        g.setSpacing(8)

        g.addWidget(QtWidgets.QLabel("BPM:"), 0, 0)
        self.bpm_spin = QtWidgets.QSpinBox()
        self.bpm_spin.setRange(20, 400)
        self.bpm_spin.setValue(int(self.settings.get("bpm", 120)))
        g.addWidget(self.bpm_spin, 0, 1)

        g.addWidget(QtWidgets.QLabel("Шагов на долю:"), 0, 2)
        self.div_spin = QtWidgets.QSpinBox()
        self.div_spin.setRange(1, 16)
        self.div_spin.setValue(int(self.settings.get("div", 4)))
        g.addWidget(self.div_spin, 0, 3)

        g.addWidget(QtWidgets.QLabel("Окно аккорда, мс:"), 0, 4)
        self.cw_spin = QtWidgets.QSpinBox()
        self.cw_spin.setRange(0, 500)
        self.cw_spin.setValue(int(self.settings.get("cw_ms", 30)))
        g.addWidget(self.cw_spin, 0, 5)

        g.addWidget(QtWidgets.QLabel("Макс. нот в аккорде:"), 1, 0)
        self.mc_spin = QtWidgets.QSpinBox()
        self.mc_spin.setRange(0, 10)
        self.mc_spin.setValue(int(self.settings.get("max_chord", 0)))
        g.addWidget(self.mc_spin, 1, 1)

        g.addWidget(QtWidgets.QLabel("Вне диапазона:"), 1, 2)
        self.range_combo = QtWidgets.QComboBox()
        self.range_combo.addItems(["ctrl", "fold", "drop"])
        self.range_combo.setCurrentText(self.settings.get("range_mode", "ctrl"))
        g.addWidget(self.range_combo, 1, 3)

        g.addWidget(QtWidgets.QLabel("Перенос, токенов:"), 1, 4)
        self.wrap_spin = QtWidgets.QSpinBox()
        self.wrap_spin.setRange(0, 500)
        self.wrap_spin.setValue(int(self.settings.get("wrap", 0)))
        g.addWidget(self.wrap_spin, 1, 5)

        self.rests_chk = QtWidgets.QCheckBox("Паузы ( | )")
        self.rests_chk.setChecked(bool(self.settings.get("rests", False)))
        g.addWidget(self.rests_chk, 2, 0, 1, 3)

        v.addWidget(grp)

        out_grp = QtWidgets.QGroupBox("Результат")
        ov = QtWidgets.QVBoxLayout(out_grp)
        self.result_edit = QtWidgets.QTextEdit()
        self.result_edit.setObjectName("output")
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlainText("Загрузите файл и нажмите «Обработать»…")
        ov.addWidget(self.result_edit)
        v.addWidget(out_grp, 1)

        btns = QtWidgets.QHBoxLayout()
        proc_btn = HoverButton("Обработать")
        proc_btn.setProperty("role", "primary")
        proc_btn.clicked.connect(self._process)
        btns.addWidget(proc_btn)
        btns.addWidget(self._make_btn("Сохранить", lambda: self._save_widget(self.result_edit, ".txt")))
        btns.addWidget(self._make_btn("Копировать", lambda: self._copy_widget(self.result_edit)))
        btns.addWidget(self._make_btn("Очистить", self._clear_result))
        btns.addStretch()
        v.addLayout(btns)
        return w

    def _build_settings_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        filt = QtWidgets.QGroupBox("Фильтры нот")
        fv = QtWidgets.QGridLayout(filt)
        fv.setSpacing(8)

        fv.addWidget(QtWidgets.QLabel("Мин. velocity (0..127):"), 0, 0)
        self.min_vel_spin = QtWidgets.QSpinBox()
        self.min_vel_spin.setRange(0, 127)
        self.min_vel_spin.setValue(int(self.settings.get("min_vel", 0)))
        fv.addWidget(self.min_vel_spin, 0, 1)

        fv.addWidget(QtWidgets.QLabel("Мин. длительность (мс):"), 0, 2)
        self.min_dur_spin = QtWidgets.QSpinBox()
        self.min_dur_spin.setRange(0, 5000)
        self.min_dur_spin.setValue(int(self.settings.get("min_dur_ms", 0)))
        fv.addWidget(self.min_dur_spin, 0, 3)

        self.drums_chk = QtWidgets.QCheckBox("Включать 10-й MIDI-канал (ударные)")
        self.drums_chk.setChecked(bool(self.settings.get("include_drums", False)))
        fv.addWidget(self.drums_chk, 1, 0, 1, 4)
        v.addWidget(filt)

        au = QtWidgets.QGroupBox("Аудио / видео транскрипция")
        av = QtWidgets.QHBoxLayout(au)
        av.addWidget(QtWidgets.QLabel("Backend:"))
        self.backend_combo = QtWidgets.QComboBox()
        self.backend_combo.addItems(["auto", "transkun", "bytedance"])
        self.backend_combo.setCurrentText(self.settings.get("backend", "auto"))
        av.addWidget(self.backend_combo)
        av.addWidget(QtWidgets.QLabel("Устройство:"))
        self.device_combo = QtWidgets.QComboBox()
        self.device_combo.addItems(["auto", "cpu", "cuda"])
        self.device_combo.setCurrentText(self.settings.get("device", "auto"))
        av.addWidget(self.device_combo)
        av.addStretch()
        v.addWidget(au)

        hint = QtWidgets.QLabel(
            "Для аудио нужна нейросеть: pip install transkun "
            "(или piano_transcription_inference). ffmpeg должен быть в PATH.")
        hint.setObjectName("status_normal")
        hint.setWordWrap(True)
        v.addWidget(hint)

        theme_grp = QtWidgets.QGroupBox("Тема оформления")
        tv = QtWidgets.QVBoxLayout(theme_grp)
        self.theme_combo = QtWidgets.QComboBox()
        for key, th in THEMES.items():
            self.theme_combo.addItem(th["name_key"], key)
        idx = self.theme_combo.findData(_current_theme_key)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(
            lambda i: self._animate_theme(self.theme_combo.itemData(i)))
        tv.addWidget(self.theme_combo)

        custom_btn = HoverButton("Свой цвет…")
        custom_btn.clicked.connect(self._open_custom_theme)
        tv.addWidget(custom_btn)
        v.addWidget(theme_grp)

        v.addStretch()
        return w

    def _make_btn(self, text, cb):
        b = HoverButton(text)
        b.clicked.connect(cb)
        return b

    def _icon_btn(self, text, tip):
        b = HoverButton(text)
        b.setProperty("role", "icon")
        b.setFixedSize(32, 32)
        b.setToolTip(tip)
        return b

    # ── темы ────────────────────────────────────────────────────────
    def _cycle_theme(self):
        keys = list(THEMES.keys())
        i = keys.index(_current_theme_key) if _current_theme_key in keys else 0
        self._animate_theme(keys[(i + 1) % len(keys)])

    def _animate_theme(self, target_key, duration=260):
        global _current_theme_key
        if target_key not in THEMES:
            return
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        if self._theme_anim is not None:
            try:
                self._theme_anim.stop()
            except Exception:
                pass

        from_theme = dict(get_theme())
        to_theme = dict(THEMES[target_key])
        _current_theme_key = target_key
        if hasattr(self, "theme_combo"):
            idx = self.theme_combo.findData(target_key)
            if idx >= 0 and self.theme_combo.currentIndex() != idx:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(idx)
                self.theme_combo.blockSignals(False)

        color_keys = [k for k, v in to_theme.items()
                      if isinstance(v, str) and (v.startswith('#') or v.startswith('rgb'))]
        from_parsed = {k: _parse_color(from_theme.get(k, to_theme[k])) for k in color_keys}
        to_parsed = {k: _parse_color(to_theme[k]) for k in color_keys}

        anim = QtCore.QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        def tick(t):
            merged = dict(to_theme)
            for k in color_keys:
                merged[k] = _rgba_to_str(_lerp_rgba(from_parsed[k], to_parsed[k], t))
            app.setStyleSheet(build_qss(merged))

        def done():
            apply_theme(app)
            self.settings["theme"] = target_key
            save_settings(self.settings)
            self._theme_anim = None
            self._log_local("INFO", f"Тема: {THEMES[target_key]['name_key']}")

        anim.valueChanged.connect(tick)
        anim.finished.connect(done)
        self._theme_anim = anim
        anim.start()

    def _open_custom_theme(self):
        dlg = CustomThemeDialog(self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            accent, bg, text = dlg.get_colors()
            is_dark = QtGui.QColor(bg).lightness() < 128
            panel = QtGui.QColor(bg).lighter(115).name() if is_dark else QtGui.QColor(bg).darker(105).name()
            panel_alt = QtGui.QColor(bg).lighter(125).name() if is_dark else QtGui.QColor(bg).darker(110).name()
            inp = QtGui.QColor(bg).lighter(110).name() if is_dark else QtGui.QColor(bg).darker(103).name()
            border = QtGui.QColor(bg).lighter(150).name() if is_dark else QtGui.QColor(bg).darker(130).name()
            text_muted = QtGui.QColor(text).darker(140).name() if is_dark else QtGui.QColor(text).lighter(140).name()
            text_dim = QtGui.QColor(text).darker(180).name() if is_dark else QtGui.QColor(text).lighter(180).name()
            THEMES["custom"] = _mk_theme(
                "custom", "Свой цвет", is_dark,
                bg, panel_alt, panel, panel_alt, inp, text, text_muted, text_dim,
                accent, accent, accent, text if is_dark else bg, border)
            if hasattr(self, "theme_combo") and self.theme_combo.findData("custom") < 0:
                self.theme_combo.addItem("Свой цвет", "custom")
            self._animate_theme("custom", duration=200)

    # ── файл / обработка ────────────────────────────────────────────
    def _save_inputs(self):
        self.settings.update({
            "bpm": self.bpm_spin.value(),
            "div": self.div_spin.value(),
            "cw_ms": self.cw_spin.value(),
            "max_chord": self.mc_spin.value(),
            "range_mode": self.range_combo.currentText(),
            "wrap": self.wrap_spin.value(),
            "rests": self.rests_chk.isChecked(),
            "min_vel": self.min_vel_spin.value(),
            "min_dur_ms": self.min_dur_spin.value(),
            "include_drums": self.drums_chk.isChecked(),
            "backend": self.backend_combo.currentText(),
            "device": self.device_combo.currentText(),
            "theme": _current_theme_key,
        })
        save_settings(self.settings)

    def _open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Открыть файл", "",
            "Поддерживаемые (*.mid *.midi *.kar *.mp3 *.wav *.flac *.m4a *.ogg "
            "*.mp4 *.mkv *.mov *.webm);;MIDI (*.mid *.midi *.kar);;"
            "Аудио (*.mp3 *.wav *.flac *.m4a *.ogg);;"
            "Видео (*.mp4 *.mkv *.mov *.webm);;Все файлы (*)")
        if path:
            self.midi_path = path
            self.file_label.setText(f"📄 {Path(path).name}")
            self.status_label.setText("Файл загружен — нажмите «Обработать»")
            self._log_local("INFO", f"Файл: {path}")

    def _process(self):
        if not self.midi_path:
            QtWidgets.QMessageBox.warning(self, "Файл не выбран",
                                          "Сначала загрузите файл.")
            return
        if self.processing:
            return
        params = {
            "path": self.midi_path,
            "bpm": float(self.bpm_spin.value()),
            "div": int(self.div_spin.value()),
            "cw_ms": float(self.cw_spin.value()),
            "max_chord": int(self.mc_spin.value()),
            "rests": bool(self.rests_chk.isChecked()),
            "range_mode": self.range_combo.currentText(),
            "wrap": int(self.wrap_spin.value()),
            "min_vel": int(self.min_vel_spin.value()),
            "min_dur_ms": float(self.min_dur_spin.value()),
            "include_drums": bool(self.drums_chk.isChecked()),
            "backend": self.backend_combo.currentText(),
            "device": self.device_combo.currentText(),
        }
        self.processing = True
        self.progress.setVisible(True)
        self.status_label.setText("Обработка…")
        self.result_edit.setPlainText("Обработка…\n")
        self._save_inputs()
        self._log_local("INFO",
                        f"Запуск обработки: BPM={params['bpm']:g}, "
                        f"div={params['div']}, cw={params['cw_ms']:g}мс, "
                        f"диапазон={params['range_mode']}")
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _worker(self, p):
        try:
            ext = Path(p["path"]).suffix.lower()
            if ext in (".mid", ".midi", ".kar"):
                self._log_signal.emit("INFO", "Читаю MIDI…")
                notes = read_midi(p["path"], include_drums=p["include_drums"])
            else:
                notes = transcribe_audio(
                    p["path"], p["backend"], p["device"],
                    log=lambda m: self._log_signal.emit("INFO", m))
            if not notes:
                raise RuntimeError("Нот не найдено.")
            self._log_signal.emit("INFO", f"Нот на входе: {len(notes)}")

            table = TOK_FULL if p["range_mode"] == "ctrl" else TOK_MAIN
            min_dur = p["min_dur_ms"] / 1000.0

            prepared, dropped_f, dropped_r = [], 0, 0
            for on, off, pit, vel in notes:
                if vel < p["min_vel"] or (off - on) < min_dur:
                    dropped_f += 1
                    continue
                if pit not in table:
                    if p["range_mode"] == "fold":
                        pit = fold_pitch(pit)
                    else:
                        dropped_r += 1
                        continue
                prepared.append((on, off, pit, vel))

            if not prepared:
                raise RuntimeError("После фильтрации не осталось нот.")
            self._log_signal.emit(
                "INFO",
                f"Фильтр: отброшено {dropped_f}, вне диапазона {dropped_r}, "
                f"осталось {len(prepared)}")

            step = 60.0 / (p["bpm"] * p["div"])
            slots, qs = quantize(prepared, step, p["cw_ms"] / 1000.0)
            tokens, trimmed, chords = render_tokens(
                slots, table,
                rests=p["rests"], max_rests=16,
                max_chord=p["max_chord"])

            if p["wrap"] > 0:
                text = "\n".join(
                    " ".join(tokens[i:i + p["wrap"]])
                    for i in range(0, len(tokens), p["wrap"]))
            else:
                text = " ".join(tokens)

            stats = (
                f"Нот: {len(prepared)} из {len(notes)} "
                f"(фильтр {dropped_f}, вне диапазона {dropped_r}) · "
                f"Аккордов: {chords} (срезано {trimmed}) · "
                f"Шаг сетки: {step * 1000:.1f} мс · "
                f"Сдвиг: средний {qs['err_mean'] * 1000:.1f} мс, "
                f"макс {qs['err_max'] * 1000:.1f} мс")

            self._log_signal.emit("INFO", "Готово")
            self._done_signal.emit(text, stats, (slots, step))
        except Exception as e:
            self._log_signal.emit("ERROR", str(e))
            self._err_signal.emit(str(e))
        finally:
            self.processing = False

    def _on_done(self, text, stats, payload):
        self.progress.setVisible(False)
        self.result_edit.setPlainText(text)
        self.info_label.setText(stats)
        self.status_label.setText("Готово")
        if payload:
            self.slots, self.step_sec = payload
            self.pos_label.setText(f"{len(self.slots)} слотов")
        self._log_local("INFO", stats)

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.status_label.setText("Ошибка")
        self.result_edit.setPlainText(f"Ошибка: {msg}")
        QtWidgets.QMessageBox.critical(self, "Ошибка", msg)

    def _copy_widget(self, w):
        txt = w.toPlainText().strip()
        if txt:
            QtWidgets.QApplication.clipboard().setText(txt)
            self.status_label.setText("Скопировано в буфер")
            self._log_local("INFO", f"Скопировано: {len(txt)} символов")

    def _save_widget(self, w, ext):
        txt = w.toPlainText().strip()
        if not txt:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить", "", f"*{ext};;Все файлы (*)")
        if path:
            try:
                Path(path).write_text(txt, encoding="utf-8")
                self.status_label.setText(f"Сохранено: {Path(path).name}")
                self._log_local("INFO", f"Сохранено: {path}")
            except Exception as e:
                self._log_local("ERROR", f"Ошибка сохранения: {e}")
                QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))

    def _clear_result(self):
        self.result_edit.setPlainText("Загрузите файл и нажмите «Обработать»…")
        self.info_label.setText("")
        self._log_local("INFO", "Поле результата очищено")

    # ── служебное ───────────────────────────────────────────────────
    def _fade_in(self):
        anim = QtCore.QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(380)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        anim.start()
        self._fade_anim = anim

    def _show_log(self):
        LogViewerDialog(self).exec()

    def _show_about(self):
        QtWidgets.QMessageBox.about(
            self, "О программе",
            "AstraConv v0.0.7\nby black\n\n"
            "MIDI / Audio → клавиатурная раскладка.")

    def closeEvent(self, event):
        self._save_inputs()
        logger.info("AstraConv закрыт")
        event.accept()


# ══════════════════════════════════════════════════════════════════════
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QtGui.QFont("Segoe UI", 9))

    win = AstraConvWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
