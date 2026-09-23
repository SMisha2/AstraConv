import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os, io, sys, time, json, tempfile, contextlib, traceback, threading
import subprocess
from pathlib import Path

import logging, warnings

logging.disable(logging.CRITICAL)
for _h in logging.root.handlers[:]:
    logging.root.removeHandler(_h)
logging.root.addHandler(logging.NullHandler())
logging.root.setLevel(logging.CRITICAL + 10)
logging.root.propagate = False
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["PYTHONWARNINGS"] = "ignore"

try:
    import mido
except ImportError:
    mido = None

try:
    import requests
except ImportError:
    requests = None

from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple, Set


# ═══════════════════════════════════════════════════════════════════
#                          VERSION / UPDATE
# ═══════════════════════════════════════════════════════════════════

CURRENT_VERSION = "0.0.1"
GITHUB_OWNER = "SMisha2"
GITHUB_REPO = "AstraConv"
ASSET_NAME = "AstraConv.exe"
SETTINGS_FILE = "astraconv_settings.json"


def version_tuple(v):
    try:
        parts = []
        for p in str(v).strip().lstrip("v").split("."):
            num = ""
            for ch in p:
                if ch.isdigit():
                    num += ch
                else:
                    break
            parts.append(int(num) if num else 0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)


def fetch_latest_release_info():
    """Запрашивает последний релиз с GitHub API."""
    if requests is None:
        return None, "Библиотека requests не установлена.\nУстановите: pip install requests"
    api = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    try:
        r = requests.get(api, timeout=10,
                         headers={"Accept": "application/vnd.github+json"})
        if r.status_code == 404:
            return None, "Релиз не найден на GitHub"
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def download_asset_to_file(url, dest, progress_callback=None,
                            chunk_size=65536, max_retries=3):
    """Скачивает файл с прогрессом и повторами."""
    if requests is None:
        return False, "requests недоступен"
    for attempt in range(max_retries):
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = r.headers.get("content-length")
                total = int(total) if total else None
                written = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                            if progress_callback and total:
                                progress_callback(int(written * 100 // total))
                if total is None or os.path.getsize(dest) == total:
                    if progress_callback:
                        progress_callback(100)
                    return True, None
                if attempt < max_retries - 1:
                    time.sleep(1)
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                    continue
                return False, "Размер файла не совпал"
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                try:
                    if os.path.exists(dest):
                        os.remove(dest)
                except Exception:
                    pass
            else:
                return False, str(e)
    return False, "Превышено число попыток"


def perform_replacement_and_restart(new_file, target_name, is_frozen):
    """
    Заменяет текущий exe на скачанный и перезапускает.
    На Windows создаётся .bat, который ждёт завершения процесса,
    подменяет файл и запускает заново.
    """
    try:
        if is_frozen or (sys.argv and sys.argv[0].lower().endswith(".exe")):
            current = os.path.basename(sys.argv[0])
            backup = current + ".bak"
            bat_path = os.path.join(tempfile.gettempdir(), "astraconv_update.bat")
            bat = f"""@echo off
setlocal
:waitloop
taskkill /f /im "{current}" >nul 2>&1
timeout /t 1 /nobreak >nul
tasklist /fi "IMAGENAME eq {current}" 2>nul | findstr /i "{current}" >nul && goto waitloop
timeout /t 1 /nobreak >nul
if exist "{backup}" del /f /q "{backup}" >nul 2>&1
if exist "{current}" move /y "{current}" "{backup}" >nul 2>&1
if exist "{new_file}" move /y "{new_file}" "{target_name}" >nul 2>&1
if exist "{target_name}" (
    start "" "{target_name}"
    del /f /q "{backup}" >nul 2>&1
) else (
    if exist "{backup}" (
        move /y "{backup}" "{current}" >nul 2>&1
        start "" "{current}"
    )
)
del /f /q "%~f0" >nul 2>&1 & exit
"""
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat)
            subprocess.Popen(["cmd", "/c", "start", "", bat_path],
                             shell=False, close_fds=True)
            sys.exit(0)
        else:
            target = os.path.abspath(sys.argv[0]) if sys.argv else None
            if target and target.endswith(".py"):
                try:
                    os.replace(new_file, target)
                except Exception as e:
                    raise RuntimeError(f"Не удалось заменить файл: {e}")
                os.execv(sys.executable, [sys.executable, target])
            else:
                raise RuntimeError("Не удалось определить путь для замены")
    except Exception as e:
        raise RuntimeError(f"Ошибка замены: {e}")


def load_local_settings() -> dict:
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def save_local_settings(s: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
#                              ТЕМА
# ═══════════════════════════════════════════════════════════════════

class Theme:
    BG       = "#0a0a0a"
    SURFACE  = "#141414"
    SURFACE2 = "#1e1e1e"
    BORDER   = "#2e2a1a"
    TEXT     = "#f5e6b8"
    MUTED    = "#8a7a4a"
    ACCENT   = "#d4af37"
    ACCENT2  = "#f0c75e"
    SUCCESS  = "#7dd87d"
    ERROR    = "#ff5c5c"
    WARNING  = "#e6b800"
    SELECT   = "#3a2f10"


AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.opus'}
MIDI_EXTS  = {'.mid', '.midi'}

TRANSCRIBE_LOG = os.path.join(tempfile.gettempdir(), "astraconv_transcribe.log")


# ═══════════════════════════════════════════════════════════════════
#                    КОНФИГ FREEPIANO (88 клавиш)
# ═══════════════════════════════════════════════════════════════════

CONFIG_TEXT = """
GroupCount	2
Group	Set	0
KeySignature	Set	0
Velocity	In_0	Set	80
Velocity	In_1	Set	100
Sustain	Out_0	Set	127
Keydown	F5	Record
Keydown	1	Note	In_0	C2
Label	1	1
Keydown	2	Note	In_0	D2
Label	2	2
Keydown	3	Note	In_0	E2
Label	3	3
Keydown	4	Note	In_0	F2
Label	4	4
Keydown	5	Note	In_0	G2
Label	5	5
Keydown	6	Note	In_0	A2
Label	6	6
Keydown	7	Note	In_0	B2
Label	7	7
Keydown	8	Note	In_0	C3
Label	8	8
Keydown	9	Note	In_0	D3
Label	9	9
Keydown	0	Note	In_0	E3
Label	0	0
Keydown	Q	Note	In_0	F3
Label	Q	Q
Keydown	W	Note	In_0	G3
Label	W	W
Keydown	E	Note	In_0	A3
Label	E	E
Keydown	R	Note	In_0	B3
Label	R	R
Keydown	T	Note	In_0	C4
Label	T	T
Keydown	Y	Note	In_0	D4
Label	Y	Y
Keydown	U	Note	In_0	E4
Label	U	U
Keydown	I	Note	In_0	F4
Label	I	I
Keydown	O	Note	In_0	G4
Label	O	O
Keydown	P	Note	In_0	A4
Label	P	P
Keydown	A	Note	In_0	B4
Label	A	A
Keydown	S	Note	In_0	C5
Label	S	S
Keydown	D	Note	In_0	D5
Label	D	D
Keydown	F	Note	In_0	E5
Label	F	F
Keydown	G	Note	In_0	F5
Label	G	G
Keydown	H	Note	In_0	G5
Label	H	H
Keydown	J	Note	In_0	A5
Label	J	J
Keydown	K	Note	In_0	B5
Label	K	K
Keydown	L	Note	In_0	C6
Label	L	L
Keydown	Z	Note	In_0	D6
Label	Z	Z
Keydown	X	Note	In_0	E6
Label	X	X
Keydown	C	Note	In_0	F6
Label	C	C
Keydown	V	Note	In_0	G6
Label	V	V
Keydown	B	Note	In_0	A6
Label	B	B
Keydown	N	Note	In_0	B6
Label	N	N
Keydown	M	Note	In_0	C7
Label	M	M
Keydown	"	Sustain	In_1	Flip	127
Keydown	Space	Sustain	In_1	Flip	127
Keyup	Space	Sustain	In_1	Flip	127
Label	Space	VP
Keydown	Ctrl	Group	Set	1
Keyup	Ctrl	Group	Set	0
Keydown	Up	Transpose	In_0	Inc	1
Keydown	Down	Transpose	In_0	Dec	1
Group	Set	1
KeySignature	Set	0
Velocity	In_0	Set	80
Velocity	In_1	Set	100
Keydown	1	Note	In_0	C#2
Label	1	1#
Keydown	2	Note	In_0	D#2
Label	2	2#
Keydown	3	Note	In_0	F#2
Label	3	4#
Keydown	4	Note	In_0	G#2
Label	4	5#
Keydown	5	Note	In_0	A#2
Label	5	6#
Keydown	6	Note	In_0	C#3
Label	6	8#
Keydown	7	Note	In_0	D#3
Label	7	9#
Keydown	8	Note	In_0	F#3
Label	8	Q#
Keydown	9	Note	In_0	G#3
Label	9	W#
Keydown	0	Note	In_0	A#3
Label	0	E#
Keydown	Q	Note	In_0	C#4
Label	Q	T#
Keydown	W	Note	In_0	D#4
Label	W	Y#
Keydown	E	Note	In_0	F#4
Label	E	I#
Keydown	R	Note	In_0	G#4
Label	R	O#
Keydown	T	Note	In_0	A#4
Label	T	P#
Keydown	Y	Note	In_0	C#5
Label	Y	S#
Keydown	U	Note	In_0	D#5
Label	U	D5#
Keydown	I	Note	In_0	F#5
Label	I	G5#
Keydown	O	Note	In_0	G#5
Label	O	H#
Keydown	P	Note	In_0	A#5
Label	P	J#
Keydown	A	Note	In_0	C#6
Label	A	L#
Keydown	S	Note	In_0	D#6
Label	S	Z#
Keydown	D	Note	In_0	F#6
Label	D	X#
Keydown	F	Note	In_0	G#6
Label	F	C6#
Keydown	G	Note	In_0	A#6
Label	G	V#
Keydown	H	Note	In_0	C#7
Label	H	N#
Keydown	J	Note	In_0	D#7
Label	J	M#
Keydown	K	Note	In_0	F#7
Label	K	B#
Keydown	L	Note	In_0	G#7
Label	L	C8
"""


# ═══════════════════════════════════════════════════════════════════
#                          MIDI-ЛОГИКА
# ═══════════════════════════════════════════════════════════════════

@dataclass
class KeyMap:
    note: int
    key: str
    group: int


@dataclass
class NoteEvent:
    midi: int
    start_tick: int
    end_tick: int
    velocity: int
    shift: int = 0
    original_midi: int = 0


@dataclass
class ChordData:
    notes: List[NoteEvent]
    key_tokens: List[str]
    index: int = 0
    is_break: bool = False
    comment: str = ""
    is_comment: bool = False


def note_to_midi(note: str) -> Optional[int]:
    notes = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
    if not note or note[0] not in notes:
        return None
    base = notes[note[0]]
    idx = 1
    sharp = 0
    if len(note) > 1 and note[1] == '#':
        sharp = 1
        idx = 2
    try:
        octave = int(note[idx:])
    except ValueError:
        return None
    return (octave + 1) * 12 + base + sharp


def parse_freepiano_config(config_text: str) -> List[KeyMap]:
    mappings = []
    current_group = 0
    skip_keys = {'Ctrl', 'Shift', 'RShift', 'Space', '"',
                 'Up', 'Down', 'F5', 'Tab', 'Esc'}
    for line in config_text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) >= 3 and parts[0] == 'Group' and parts[1] == 'Set':
            current_group = int(parts[2])
            continue
        if (len(parts) >= 5 and parts[0] == 'Keydown'
                and parts[2] == 'Note'):
            key_name = parts[1]
            note_name = parts[4]
            if key_name in skip_keys:
                continue
            midi_note = note_to_midi(note_name)
            if midi_note is None:
                continue
            mappings.append(KeyMap(note=midi_note, key=key_name,
                                   group=current_group))
    return mappings


def build_maps(mappings: List[KeyMap]) -> Tuple[Dict[int, str], Set[int]]:
    note_to_key: Dict[int, str] = {}
    ctrl_notes: Set[int] = set()
    for m in mappings:
        if m.group == 0:
            note_to_key[m.note] = m.key
        else:
            ctrl_notes.add(m.note)
    return note_to_key, ctrl_notes


# ═══════════════════════════════════════════════════════════════════
#                    basic-pitch (MP3 → MIDI)
# ═══════════════════════════════════════════════════════════════════

def _find_working_model() -> Optional[str]:
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except Exception:
        return None
    base = Path(str(ICASSP_2022_MODEL_PATH))
    candidates = [
        base.with_suffix(base.suffix + ".onnx") if base.suffix != ".onnx"
        else base,
        Path(str(base) + ".onnx"),
        base,
        Path(str(base) + ".tflite"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            from basic_pitch.inference import Model
            Model(str(path))
            return str(path)
        except Exception:
            continue
    return None


def _write_log(lines):
    try:
        with open(TRANSCRIBE_LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def transcribe_audio_to_midi(audio_path: str,
                             onset_threshold: float = 0.5,
                             frame_threshold: float = 0.3,
                             min_note_ms: float = 80.0,
                             post_min_note_ms: float = 40.0,
                             merge_gap_ms: float = 15.0) -> str:
    log = ["=== AstraConv / basic-pitch ==="]
    log.append(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log.append(f"File: {audio_path}")

    try:
        size = os.path.getsize(audio_path)
    except OSError as e:
        raise RuntimeError(f"Не удаётся прочитать файл: {e}")
    if size < 1024:
        raise RuntimeError(f"Файл слишком мал ({size} байт)")

    import_log = io.StringIO()
    prev = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.redirect_stdout(import_log), \
                    contextlib.redirect_stderr(import_log):
                from basic_pitch.inference import predict
    except ImportError as e:
        logging.disable(prev)
        raise RuntimeError(f"basic-pitch не установлен: {e}")

    model_path = _find_working_model()
    if not model_path:
        logging.disable(prev)
        raise RuntimeError(
            "Не найдена рабочая модель basic-pitch.\n"
            "Установите: pip install --force-reinstall basic-pitch[onnx]")

    log.append(f"Model: {model_path}")
    captured = io.StringIO()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.redirect_stdout(captured), \
                    contextlib.redirect_stderr(captured):
                _, midi_data, note_events = predict(
                    audio_path, model_or_model_path=model_path,
                    onset_threshold=onset_threshold,
                    frame_threshold=frame_threshold,
                    minimum_note_length=min_note_ms)
    except BaseException as e:
        logging.disable(prev)
        log.append(captured.getvalue())
        log.append(f"EXCEPTION: {type(e).__name__}: {e}")
        log.append(traceback.format_exc())
        _write_log(log)
        raise RuntimeError(f"Транскрипция не удалась: {e}")

    logging.disable(prev)
    if midi_data is None:
        raise RuntimeError("basic-pitch не вернул MIDI")

    min_sec, merge_sec = post_min_note_ms / 1000, merge_gap_ms / 1000
    for inst in midi_data.instruments:
        notes = [n for n in inst.notes if (n.end - n.start) >= min_sec]
        notes.sort(key=lambda n: (n.pitch, n.start))
        merged = []
        for n in notes:
            if merged and merged[-1].pitch == n.pitch and \
                    (n.start - merged[-1].end) <= merge_sec:
                if n.end > merged[-1].end:
                    merged[-1].end = n.end
                if n.velocity > merged[-1].velocity:
                    merged[-1].velocity = n.velocity
            else:
                merged.append(n)
        inst.notes = merged

    out_path = os.path.join(tempfile.gettempdir(),
                            f"astraconv_{os.getpid()}_{int(time.time()*1000)}.mid")
    midi_data.write(out_path)
    _write_log(log)
    return out_path


# ═══════════════════════════════════════════════════════════════════
#                          ПАРСИНГ MIDI
# ═══════════════════════════════════════════════════════════════════

def load_midi_events(path: str) -> dict:
    if mido is None:
        raise RuntimeError("Библиотека mido не установлена")
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat or 480

    tracks_info = []
    for i, tr in enumerate(mid.tracks):
        name = tr.name if tr.name else f"Track {i+1}"
        notes = sum(1 for m in tr
                    if m.type == 'note_on' and m.velocity > 0)
        tracks_info.append({'index': i, 'name': name, 'notes': notes,
                            'selected': True})

    merged = mido.merge_tracks(mid.tracks)
    tempo_changes = []
    events = []
    tick = 0
    for msg in merged:
        tick += msg.time
        if msg.type == 'set_tempo':
            tempo_changes.append((tick, msg.tempo))
        elif msg.type == 'note_on' and msg.velocity > 0:
            events.append((tick, 1, msg.note, msg.velocity))
        elif msg.type == 'note_off' or \
                (msg.type == 'note_on' and msg.velocity == 0):
            events.append((tick, 0, msg.note, 0))
    events.sort(key=lambda e: (e[0], e[1]))

    return {
        'ticks_per_beat': tpb,
        'tempo_changes': tempo_changes,
        'events': events,
        'total_ticks': tick,
        'tracks_info': tracks_info,
        'path': path,
    }


def compute_timing(data: dict) -> Tuple[float, float]:
    tpb = data['ticks_per_beat']
    last_tick = data['total_ticks']
    if last_tick <= 0:
        return 120.0, 1.0

    total_ms = 0.0
    prev_tick, prev_tempo = 0, 500000
    for t, tempo in data['tempo_changes']:
        total_ms += ((t - prev_tick) / tpb) * (prev_tempo / 1000.0)
        prev_tick, prev_tempo = t, tempo
    total_ms += ((last_tick - prev_tick) / tpb) * (prev_tempo / 1000.0)

    total_beats = last_tick / tpb
    total_sec = total_ms / 1000.0
    bpm = (total_beats / total_sec * 60.0) if total_sec > 0 else 120.0
    ms_per_tick = total_ms / last_tick if last_tick > 0 else 1.0
    return bpm, ms_per_tick


def bpm_to_density(bpm: float) -> int:
    if bpm <= 0:
        return 2
    return max(0, min(8, round((200.0 - bpm) / 20.0)))


def best_transposition(notes: List[NoteEvent],
                       note_to_key: Dict[int, str],
                       ctrl_notes: Set[int]) -> int:
    best_shift = 0
    best_score = -1
    all_keys = set(note_to_key.keys()) | ctrl_notes
    for shift in range(-11, 12):
        score = 0
        for n in notes:
            candidate = n.original_midi + shift
            if candidate in all_keys:
                score += 1
            if candidate in note_to_key:
                score += 0.5
        if score > best_score:
            best_score = score
            best_shift = shift
    return best_shift


QUANTIZE_STEPS = {
    "off":  None,
    "1/4":  1.0,
    "1/8":  0.5,
    "1/16": 0.25,
    "1/32": 0.125,
}


def quantize_events(events: List[NoteEvent], tpb: int,
                    quantize: str) -> List[NoteEvent]:
    step_beats = QUANTIZE_STEPS.get(quantize)
    if step_beats is None:
        return events
    step_ticks = max(1, int(round(step_beats * tpb)))
    for n in events:
        n.start_tick = int(round(n.start_tick / step_ticks)) * step_ticks
        n.end_tick = int(round(n.end_tick / step_ticks)) * step_ticks
        if n.end_tick <= n.start_tick:
            n.end_tick = n.start_tick + step_ticks
    return events


def events_to_note_list(data: dict) -> List[NoteEvent]:
    active: Dict[int, Tuple[int, int]] = {}
    result: List[NoteEvent] = []
    for tick, kind, note, vel in data['events']:
        if kind == 1:
            active[note] = (tick, vel)
        else:
            if note in active:
                s, v = active.pop(note)
                result.append(NoteEvent(midi=note, start_tick=s, end_tick=tick,
                                        velocity=v, original_midi=note))
    last_tick = data['total_ticks']
    for note, (s, v) in active.items():
        result.append(NoteEvent(midi=note, start_tick=s, end_tick=last_tick,
                                velocity=v, original_midi=note))
    result.sort(key=lambda e: (e.start_tick, e.end_tick))
    return result


def group_into_chords(notes: List[NoteEvent],
                      note_to_key: Dict[int, str],
                      ctrl_notes: Set[int],
                      window_ms: float, ms_per_tick: float,
                      velocity_threshold: int,
                      auto_transpose: bool) -> List[ChordData]:
    tolerance_ticks = (max(0, int(round(window_ms / ms_per_tick)))
                       if ms_per_tick > 0 else 0)
    chords: List[ChordData] = []
    current: List[NoteEvent] = []
    current_end = -1

    def flush():
        nonlocal current, current_end
        if not current:
            return
        if auto_transpose:
            shift = best_transposition(current, note_to_key, ctrl_notes)
            for n in current:
                n.shift = shift
        tokens: List[str] = []
        for n in current:
            work = n.original_midi + n.shift
            if work in ctrl_notes:
                continue
            if work not in note_to_key:
                continue
            key = note_to_key[work]
            if n.shift != 0:
                key = key + "'"
            if key not in tokens:
                tokens.append(key)
        if tokens:
            chords.append(ChordData(notes=list(current),
                                    key_tokens=tokens))
        current = []
        current_end = -1

    for n in notes:
        if n.velocity < velocity_threshold:
            continue
        if not current:
            current.append(n)
            current_end = n.end_tick
            continue
        last_start = current[-1].start_tick
        if (n.start_tick - last_start) > tolerance_ticks \
                or n.start_tick > current_end:
            flush()
        current.append(n)
        current_end = max(current_end, n.end_tick)
    flush()
    return chords


def insert_breaks_realistic(chords: List[ChordData], data: dict
                            ) -> List[ChordData]:
    tpb = data['ticks_per_beat']
    bar_ticks = tpb * 4
    result: List[ChordData] = []
    last_bar = -1
    for ch in chords:
        if not ch.notes:
            result.append(ch)
            continue
        bar = ch.notes[0].start_tick // bar_ticks
        if last_bar >= 0 and bar > last_bar:
            result.append(ChordData(notes=[], key_tokens=[], is_break=True))
        last_bar = bar
        result.append(ch)
    return result


def inject_transpose_markers(chords: List[ChordData]) -> List[ChordData]:
    result: List[ChordData] = []
    prev_shift: Optional[int] = None
    for ch in chords:
        if ch.is_break or not ch.notes:
            result.append(ch)
            continue
        cur_shift = ch.notes[0].shift if ch.notes else 0
        if prev_shift is None or cur_shift != prev_shift:
            text = f"Transpose by: {-cur_shift:+d}"
            result.append(ChordData(notes=[], key_tokens=[],
                                    is_comment=True, comment=text))
            prev_shift = cur_shift
        result.append(ch)
    return result


# ═══════════════════════════════════════════════════════════════════
#                          ВИДЖЕТ КНОПКИ
# ═══════════════════════════════════════════════════════════════════

class StyledButton(tk.Frame):
    def __init__(self, parent, text, command, small=False):
        super().__init__(parent, bg=Theme.SURFACE2, cursor="arrow")
        self.command = command
        self.enabled = False
        self._bg_normal = Theme.SURFACE2
        self._bg_hover = Theme.ACCENT
        self._bg_disabled = Theme.SURFACE
        self._fg_normal = Theme.ACCENT
        self._fg_disabled = Theme.MUTED
        self._fg_hover = "#0a0a0a"

        pad_y = 6 if small else 11
        font_size = 9 if small else 10
        self.label = tk.Label(
            self, text=text, font=("Segoe UI", font_size, "bold"),
            bg=self._bg_normal, fg=self._fg_normal, padx=8, pady=pad_y)
        self.label.pack(fill="both", expand=True)

        for w in (self, self.label):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)
        self.set_enabled(False)

    def _on_enter(self, _):
        if self.enabled:
            self.configure(bg=self._bg_hover)
            self.label.configure(bg=self._bg_hover, fg=self._fg_hover)

    def _on_leave(self, _):
        if self.enabled:
            self.configure(bg=self._bg_normal)
            self.label.configure(bg=self._bg_normal, fg=self._fg_normal)

    def _on_click(self, _):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        bg = self._bg_normal if enabled else self._bg_disabled
        fg = self._fg_normal if enabled else self._fg_disabled
        self.configure(bg=bg, cursor="hand2" if enabled else "arrow")
        self.label.configure(bg=bg, fg=fg)

    def set_text(self, text):
        self.label.configure(text=text)


# ═══════════════════════════════════════════════════════════════════
#                       UPDATE DIALOG (tkinter)
# ═══════════════════════════════════════════════════════════════════

class UpdateDialog(tk.Toplevel):
    def __init__(self, parent, silent=False):
        super().__init__(parent)
        self.silent = silent
        self.title("Обновление AstraConv")
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.resizable(False, False)
        self.geometry("520x300")
        self.grab_set()
        self._after_id = None
        self._finished = False

        tk.Label(self, text="✦  Проверка обновлений",
                 font=("Segoe UI", 14, "bold"),
                 bg=Theme.BG, fg=Theme.ACCENT).pack(pady=(20, 6))

        self.status_lbl = tk.Label(
            self, text="Соединение с GitHub...",
            font=("Segoe UI", 10), bg=Theme.BG, fg=Theme.TEXT,
            wraplength=460, justify="center")
        self.status_lbl.pack(pady=(0, 10))

        self.version_lbl = tk.Label(
            self, text=f"Текущая версия: {CURRENT_VERSION}",
            font=("Consolas", 9), bg=Theme.BG, fg=Theme.MUTED)
        self.version_lbl.pack()

        self.progress = ttk.Progressbar(
            self, orient="horizontal", mode="determinate",
            style="Gold.Horizontal.TProgressbar", length=440)
        # спрячем прогресс до момента скачивания
        self._progress_packed = False

        btn_row = tk.Frame(self, bg=Theme.BG)
        btn_row.pack(side="bottom", fill="x", padx=20, pady=18)

        self.close_btn = StyledButton(btn_row, "Закрыть", self._on_close)
        self.close_btn.pack(side="right", fill="x", expand=True, padx=(6, 0))
        self.close_btn.set_enabled(True)

        self.retry_btn = StyledButton(btn_row, "Проверить снова",
                                       self._check_async)
        self.retry_btn.pack(side="right", fill="x", expand=True, padx=(0, 6))
        self.retry_btn.set_enabled(False)

        self._check_async()

    def _on_close(self):
        self._finished = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _set_status(self, text, color=Theme.TEXT):
        try:
            self.status_lbl.config(text=text, fg=color)
        except Exception:
            pass

    def _show_progress(self, show):
        if show and not self._progress_packed:
            self.progress.pack(pady=(0, 10))
            self._progress_packed = True
        elif not show and self._progress_packed:
            self.progress.pack_forget()
            self._progress_packed = False

    def _check_async(self):
        self.retry_btn.set_enabled(False)
        self._set_status("Соединение с GitHub...", Theme.MUTED)
        self._show_progress(False)
        self.progress['value'] = 0
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        info, err = fetch_latest_release_info()
        self.after(0, lambda: self._on_check_result(info, err))

    def _on_check_result(self, info, err):
        if self._finished:
            return
        if err or not info:
            self._set_status(f"Ошибка: {err}", Theme.ERROR)
            self.retry_btn.set_enabled(True)
            return

        tag = (info.get("tag_name") or info.get("name") or "").strip()
        latest = tag.lstrip("v").strip()
        if not latest:
            self._set_status("Не удалось определить версию из релиза",
                             Theme.WARNING)
            self.retry_btn.set_enabled(True)
            return

        self.version_lbl.config(
            text=f"Текущая: {CURRENT_VERSION}   ·   На GitHub: {latest}")

        if version_tuple(latest) <= version_tuple(CURRENT_VERSION):
            self._set_status("✓  Установлена последняя версия",
                             Theme.SUCCESS)
            if self.silent:
                self.after(1500, self._on_close)
            return

        asset_url = None
        asset_size = 0
        for a in info.get("assets", []) or []:
            if a.get("name") == ASSET_NAME:
                asset_url = a.get("browser_download_url")
                asset_size = a.get("size", 0)
                break

        if not asset_url:
            self._set_status(
                f"В релизе {latest} нет файла {ASSET_NAME}\n"
                "Проверьте настройки репозитория.", Theme.WARNING)
            self.retry_btn.set_enabled(True)
            return

        # Спрашиваем у пользователя
        size_mb = asset_size / 1024 / 1024 if asset_size else 0
        msg = (f"Доступна новая версия: {latest}\n"
               f"Текущая: {CURRENT_VERSION}\n")
        if size_mb:
            msg += f"Размер: {size_mb:.1f} МБ\n"
        msg += "\nСкачать и установить сейчас?"

        if self.silent:
            # в тихом режиме не спрашиваем
            ans = messagebox.askyesno("Обновление AstraConv", msg, parent=self)
        else:
            ans = messagebox.askyesno("Обновление AstraConv", msg, parent=self)

        if not ans:
            self._set_status("Обновление отложено", Theme.MUTED)
            self.retry_btn.set_enabled(True)
            return

        self._set_status("Скачивание...", Theme.WARNING)
        self._show_progress(True)
        threading.Thread(
            target=self._download_worker,
            args=(asset_url,),
            daemon=True).start()

    def _download_worker(self, url):
        tmp = os.path.join(tempfile.gettempdir(),
                            f"AstraConv_update_{int(time.time())}.exe")

        def progress(pct):
            self.after(0, lambda: self._set_progress(pct))

        ok, err = download_asset_to_file(url, tmp, progress_callback=progress)
        self.after(0, lambda: self._on_download_done(ok, err, tmp))

    def _set_progress(self, pct):
        try:
            self.progress['value'] = pct
        except Exception:
            pass

    def _on_download_done(self, ok, err, tmp):
        if self._finished:
            return
        if not ok:
            self._set_status(f"Ошибка загрузки: {err}", Theme.ERROR)
            self._show_progress(False)
            self.retry_btn.set_enabled(True)
            return

        self._set_status("Установка и перезапуск...", Theme.SUCCESS)
        self._set_progress(100)

        is_frozen = getattr(sys, "frozen", False) or \
            (sys.argv and sys.argv[0].lower().endswith(".exe"))

        try:
            perform_replacement_and_restart(tmp, ASSET_NAME, is_frozen)
        except Exception as e:
            self._set_status(f"Не удалось установить: {e}", Theme.ERROR)
            self._show_progress(False)
            self.retry_btn.set_enabled(True)


# ═══════════════════════════════════════════════════════════════════
#                  ДИАЛОГ ВЫБОРА ТРЕКОВ
# ═══════════════════════════════════════════════════════════════════

class TrackDialog(tk.Toplevel):
    def __init__(self, parent, tracks_info):
        super().__init__(parent)
        self.title("Выбор треков")
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self.geometry("440x400")
        self.result = None

        tk.Label(self, text="✦  Какие треки конвертировать",
                 font=("Segoe UI", 12, "bold"),
                 bg=Theme.BG, fg=Theme.ACCENT).pack(pady=(14, 10))

        wrap = tk.Frame(self, bg=Theme.BG)
        wrap.pack(fill="both", expand=True, padx=20)

        self.vars = []
        for tr in tracks_info:
            var = tk.BooleanVar(value=tr.get('selected', True))
            self.vars.append(var)
            row = tk.Frame(wrap, bg=Theme.BG)
            row.pack(fill="x", pady=2)
            tk.Checkbutton(
                row, text=f"  {tr['name']}  ({tr['notes']} нот)",
                variable=var, bg=Theme.BG, fg=Theme.TEXT,
                activebackground=Theme.BG, activeforeground=Theme.ACCENT,
                selectcolor=Theme.SURFACE2, font=("Segoe UI", 10),
                anchor="w", bd=0, highlightthickness=0
            ).pack(side="left", fill="x", expand=True)

        btns = tk.Frame(self, bg=Theme.BG)
        btns.pack(fill="x", padx=20, pady=16)
        ok = StyledButton(btns, "OK", self._ok)
        ok.pack(side="right", fill="x", expand=True, padx=(6, 0))
        ok.set_enabled(True)
        cancel = StyledButton(btns, "Отмена", self.destroy)
        cancel.pack(side="right", fill="x", expand=True, padx=(0, 6))
        cancel.set_enabled(True)

        self.wait_window(self)

    def _ok(self):
        self.result = [v.get() for v in self.vars]
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
#                ДИАЛОГ РЕДАКТИРОВАНИЯ АККОРДА
# ═══════════════════════════════════════════════════════════════════

class ChordEditDialog(tk.Toplevel):
    def __init__(self, parent, chord: ChordData, idx: int):
        super().__init__(parent)
        self.title(f"Аккорд #{idx + 1}")
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self.geometry("440x260")
        self.result = None

        tk.Label(self, text="Ноты аккорда (через пробел):",
                 font=("Segoe UI", 10),
                 bg=Theme.BG, fg=Theme.TEXT).pack(anchor="w", padx=20,
                                                  pady=(16, 4))

        self.entry = tk.Entry(
            self, bg=Theme.SURFACE2, fg=Theme.TEXT,
            insertbackground=Theme.ACCENT,
            font=("Consolas", 14), bd=0)
        self.entry.pack(fill="x", padx=20, ipady=8)
        self.entry.insert(0, " ".join(chord.key_tokens))

        tk.Label(self,
                 text="Пример: T Y U  или  [T Y U]  — через пробел",
                 font=("Segoe UI", 8), bg=Theme.BG, fg=Theme.MUTED
                 ).pack(anchor="w", padx=20, pady=(4, 0))

        btns = tk.Frame(self, bg=Theme.BG)
        btns.pack(fill="x", padx=20, pady=20)
        ok = StyledButton(btns, "Сохранить", self._ok)
        ok.pack(side="right", fill="x", expand=True, padx=(6, 0))
        ok.set_enabled(True)
        cancel = StyledButton(btns, "Отмена", self.destroy)
        cancel.pack(side="right", fill="x", expand=True, padx=(0, 6))
        cancel.set_enabled(True)

        self.wait_window(self)

    def _ok(self):
        text = self.entry.get().strip()
        if text:
            self.result = text.split()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
#                                GUI
# ═══════════════════════════════════════════════════════════════════

class AstraConvGUI:
    MAX_UNDO = 50

    def __init__(self, root):
        self.root = root
        self.root.title(f"AstraConv {CURRENT_VERSION} — MIDI/MP3 → QWERTY")
        self.root.geometry("900x960")
        self.root.minsize(720, 780)
        self.root.configure(bg=Theme.BG)

        self.result_text = ""
        self.code_text = ""
        self.status_base = "Перетащите .mid или .mp3 файл"
        self.current_chords: List[ChordData] = []
        self.current_file_path: Optional[str] = None
        self.current_is_audio = False

        self._midi_data: Optional[dict] = None
        self._note_to_key: Dict[int, str] = {}
        self._ctrl_notes: Set[int] = set()
        self._raw_notes: List[NoteEvent] = []
        self._tracks_info: List[dict] = []
        self._undo_stack: List[List[ChordData]] = []

        self.last_bpm = 120.0
        self.last_auto_density = 2
        self.last_auto_window_ms = 0.0

        self._ui_ready = False
        self._setting_density = False

        # настройки
        self._settings = load_local_settings()

        self.density_var = tk.IntVar(value=2)
        self.font_size_var = tk.IntVar(value=15)
        self.auto_density_var = tk.BooleanVar(value=True)
        self.velocity_var = tk.IntVar(value=20)
        self.auto_transpose_var = tk.BooleanVar(value=False)
        self.quantize_var = tk.StringVar(value="off")
        self.breaks_var = tk.StringVar(value="realistic")
        self.show_markers_var = tk.BooleanVar(value=True)
        self.auto_update_var = tk.BooleanVar(
            value=bool(self._settings.get("check_updates_on_start", True)))

        self._setup_ttk()
        self._build_ui()
        self._setup_shortcuts()
        self._setup_dnd()

        # авто-проверка обновлений через 2 секунды после старта
        if self.auto_update_var.get():
            self.root.after(2000, self._auto_check_updates)

    def _setup_ttk(self):
        try:
            style = ttk.Style()
            if "clam" in style.theme_names():
                style.theme_use("clam")
            style.configure("Vertical.TScrollbar", gripcount=0,
                            background=Theme.SURFACE2,
                            darkcolor=Theme.SURFACE2,
                            lightcolor=Theme.SURFACE2,
                            troughcolor=Theme.SURFACE,
                            bordercolor=Theme.SURFACE,
                            arrowcolor=Theme.ACCENT, relief="flat")
            style.map("Vertical.TScrollbar",
                      background=[("active", Theme.ACCENT)])
            style.configure("Gold.Horizontal.TScale",
                            background=Theme.SURFACE,
                            troughcolor=Theme.SURFACE2,
                            darkcolor=Theme.ACCENT,
                            lightcolor=Theme.ACCENT,
                            bordercolor=Theme.BORDER)
            style.configure("Gold.Horizontal.TProgressbar",
                            background=Theme.ACCENT,
                            troughcolor=Theme.SURFACE2,
                            bordercolor=Theme.BORDER,
                            lightcolor=Theme.ACCENT,
                            darkcolor=Theme.ACCENT, thickness=4)
        except Exception:
            pass

    # ------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------
    def _build_ui(self):
        # ---------- HEADER ----------
        header = tk.Frame(self.root, bg=Theme.BG)
        header.pack(fill="x", padx=26, pady=(16, 4))

        row = tk.Frame(header, bg=Theme.BG)
        row.pack(fill="x")
        tk.Label(row, text="AstraConv",
                 font=("Segoe UI", 22, "bold"),
                 bg=Theme.BG, fg=Theme.ACCENT).pack(side="left")
        tk.Label(row, text=f"  ·  v{CURRENT_VERSION}  ·  автор: SMisha2",
                 font=("Segoe UI", 10),
                 bg=Theme.BG, fg=Theme.MUTED).pack(side="left", padx=(6, 0))

        # Кнопки справа в шапке
        self.update_btn = StyledButton(
            row, "🔄  Обновления",
            self.open_update_dialog, small=True)
        self.update_btn.pack(side="right", padx=(4, 0))
        self.update_btn.set_enabled(True)

        tk.Frame(header, bg=Theme.ACCENT, height=1).pack(fill="x", pady=(6, 6))
        tk.Label(header,
                 text="MIDI/MP3 → Freepiano  ·  треки, авто-транспозиция, "
                      "квантизация, undo, JSON",
                 font=("Segoe UI", 10), bg=Theme.BG, fg=Theme.MUTED,
                 anchor="w").pack(anchor="w")

        # ---------- DROP ZONE ----------
        dz = tk.Frame(self.root, bg=Theme.SURFACE,
                      highlightbackground=Theme.BORDER,
                      highlightthickness=1, cursor="hand2")
        dz.pack(fill="x", padx=26, pady=(12, 8))
        self.drop_zone = dz
        icon = tk.Label(dz, text="♛", font=("Segoe UI Symbol", 22),
                        bg=Theme.SURFACE, fg=Theme.ACCENT)
        icon.pack(pady=(8, 2))
        self.drop_icon = icon
        title = tk.Label(dz, text="Выбрать .mid / .mp3 / .wav",
                         font=("Segoe UI", 12, "bold"),
                         bg=Theme.SURFACE, fg=Theme.TEXT)
        title.pack()
        self.drop_title = title
        hint = tk.Label(dz, text="или перетащите файл сюда",
                        font=("Segoe UI", 9),
                        bg=Theme.SURFACE, fg=Theme.MUTED)
        hint.pack(pady=(1, 8))
        self.drop_hint = hint
        for w in (dz, icon, title, hint):
            w.bind("<Button-1>", lambda e: self.select_file())
            w.bind("<Enter>", self._dz_enter)
            w.bind("<Leave>", self._dz_leave)

        # ---------- PROGRESS ----------
        self.progress = ttk.Progressbar(
            self.root, orient="horizontal", mode="indeterminate",
            style="Gold.Horizontal.TProgressbar")

        # ---------- SETTINGS ----------
        settings = tk.Frame(self.root, bg=Theme.SURFACE,
                            highlightbackground=Theme.BORDER,
                            highlightthickness=1)
        settings.pack(fill="x", padx=26, pady=(0, 8))

        tk.Label(settings, text="✦  Настройки",
                 font=("Segoe UI", 10, "bold"),
                 bg=Theme.SURFACE, fg=Theme.ACCENT, anchor="w"
                 ).pack(fill="x", padx=16, pady=(8, 0))

        # Row 1: авто-плотность + BPM
        r = tk.Frame(settings, bg=Theme.SURFACE)
        r.pack(fill="x", padx=16, pady=(6, 0))
        tk.Checkbutton(r, text="  Авто-плотность",
                       variable=self.auto_density_var,
                       command=self._on_auto_toggle,
                       bg=Theme.SURFACE, fg=Theme.TEXT,
                       activebackground=Theme.SURFACE,
                       activeforeground=Theme.ACCENT,
                       selectcolor=Theme.SURFACE2,
                       font=("Segoe UI", 10), bd=0,
                       highlightthickness=0, anchor="w").pack(side="left")
        self.bpm_lbl = tk.Label(r, text="BPM: —",
                                font=("Consolas", 10, "bold"),
                                bg=Theme.SURFACE, fg=Theme.MUTED,
                                anchor="e")
        self.bpm_lbl.pack(side="right")

        # Row 2: плотность
        r = tk.Frame(settings, bg=Theme.SURFACE)
        r.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(r, text="Плотность", font=("Segoe UI", 10),
                 bg=Theme.SURFACE, fg=Theme.TEXT, width=14,
                 anchor="w").pack(side="left")
        self.density_value_lbl = tk.Label(r, text="2",
                                          font=("Consolas", 10, "bold"),
                                          bg=Theme.SURFACE,
                                          fg=Theme.ACCENT, width=5)
        self.density_value_lbl.pack(side="right")
        self.density_scale = ttk.Scale(r, from_=0, to=12,
                                       orient="horizontal",
                                       style="Gold.Horizontal.TScale",
                                       command=self._on_density_slider)
        self.density_scale.set(2)
        self.density_scale.pack(side="left", fill="x", expand=True,
                                padx=(6, 10))

        # Row 3: шрифт
        r = tk.Frame(settings, bg=Theme.SURFACE)
        r.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(r, text="Шрифт", font=("Segoe UI", 10),
                 bg=Theme.SURFACE, fg=Theme.TEXT, width=14,
                 anchor="w").pack(side="left")
        self.font_value_lbl = tk.Label(r, text="15",
                                       font=("Consolas", 10, "bold"),
                                       bg=Theme.SURFACE,
                                       fg=Theme.ACCENT, width=5)
        self.font_value_lbl.pack(side="right")
        self.font_scale = ttk.Scale(r, from_=10, to=26,
                                    orient="horizontal",
                                    style="Gold.Horizontal.TScale",
                                    command=self._on_font_slider)
        self.font_scale.set(15)
        self.font_scale.pack(side="left", fill="x", expand=True,
                             padx=(6, 10))

        # Row 4: velocity
        r = tk.Frame(settings, bg=Theme.SURFACE)
        r.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(r, text="Порог velocity", font=("Segoe UI", 10),
                 bg=Theme.SURFACE, fg=Theme.TEXT, width=14,
                 anchor="w").pack(side="left")
        self.velocity_value_lbl = tk.Label(r, text="20",
                                           font=("Consolas", 10, "bold"),
                                           bg=Theme.SURFACE,
                                           fg=Theme.ACCENT, width=5)
        self.velocity_value_lbl.pack(side="right")
        self.velocity_scale = ttk.Scale(r, from_=0, to=127,
                                        orient="horizontal",
                                        style="Gold.Horizontal.TScale",
                                        command=self._on_velocity_slider)
        self.velocity_scale.set(20)
        self.velocity_scale.pack(side="left", fill="x", expand=True,
                                 padx=(6, 10))

        # Row 5: квантизация + разрывы
        r = tk.Frame(settings, bg=Theme.SURFACE)
        r.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(r, text="Квантизация", font=("Segoe UI", 10),
                 bg=Theme.SURFACE, fg=Theme.TEXT, width=14,
                 anchor="w").pack(side="left")
        self.quant_combo = ttk.Combobox(
            r, textvariable=self.quantize_var, state="readonly",
            values=["off", "1/4", "1/8", "1/16", "1/32"],
            width=8, font=("Consolas", 10))
        self.quant_combo.pack(side="left", padx=(0, 12))
        self.quant_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._regroup_and_render())
        tk.Label(r, text="Разрывы", font=("Segoe UI", 10),
                 bg=Theme.SURFACE, fg=Theme.TEXT, width=9,
                 anchor="w").pack(side="left")
        self.breaks_combo = ttk.Combobox(
            r, textvariable=self.breaks_var, state="readonly",
            values=["realistic", "manual"], width=10,
            font=("Consolas", 10))
        self.breaks_combo.pack(side="left")
        self.breaks_combo.bind("<<ComboboxSelected>>",
                               lambda e: self._regroup_and_render())

        # Row 6: чекбоксы
        r = tk.Frame(settings, bg=Theme.SURFACE)
        r.pack(fill="x", padx=16, pady=(4, 10))
        tk.Checkbutton(r, text="  Авто-транспозиция (по аккорду)",
                       variable=self.auto_transpose_var,
                       command=self._regroup_and_render,
                       bg=Theme.SURFACE, fg=Theme.TEXT,
                       activebackground=Theme.SURFACE,
                       activeforeground=Theme.ACCENT,
                       selectcolor=Theme.SURFACE2,
                       font=("Segoe UI", 10), bd=0,
                       highlightthickness=0, anchor="w").pack(side="left")
        tk.Checkbutton(r, text="  Маркеры транспозиции",
                       variable=self.show_markers_var,
                       command=self._regroup_and_render,
                       bg=Theme.SURFACE, fg=Theme.TEXT,
                       activebackground=Theme.SURFACE,
                       activeforeground=Theme.ACCENT,
                       selectcolor=Theme.SURFACE2,
                       font=("Segoe UI", 10), bd=0,
                       highlightthickness=0, anchor="w"
                       ).pack(side="left", padx=(12, 0))
        tk.Checkbutton(r, text="  Проверять обновления при запуске",
                       variable=self.auto_update_var,
                       command=self._on_auto_update_toggle,
                       bg=Theme.SURFACE, fg=Theme.TEXT,
                       activebackground=Theme.SURFACE,
                       activeforeground=Theme.ACCENT,
                       selectcolor=Theme.SURFACE2,
                       font=("Segoe UI", 10), bd=0,
                       highlightthickness=0, anchor="w"
                       ).pack(side="left", padx=(12, 0))

        # ---------- STATUS ----------
        self.status_label = tk.Label(self.root, text=self.status_base,
                                     font=("Segoe UI", 9),
                                     bg=Theme.BG, fg=Theme.MUTED,
                                     anchor="w", justify="left")
        self.status_label.pack(fill="x", padx=26, pady=(0, 6))

        # ---------- TEXT AREA ----------
        wrap = tk.Frame(self.root, bg=Theme.SURFACE,
                        highlightbackground=Theme.BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=26, pady=(0, 10))
        sb = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar")
        sb.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.text_area = tk.Text(
            wrap, wrap="word", font=("Consolas", 15),
            bg=Theme.SURFACE, fg=Theme.TEXT,
            insertbackground=Theme.ACCENT,
            selectbackground=Theme.SELECT, selectforeground=Theme.TEXT,
            bd=0, relief="flat", padx=20, pady=16,
            highlightthickness=0, spacing1=0, spacing2=6, spacing3=8,
            yscrollcommand=sb.set)
        self.text_area.pack(side="left", fill="both", expand=True)
        sb.config(command=self.text_area.yview)
        self.text_area.bind("<Double-Button-1>", self._on_double_click)
        self.text_area.bind("<Button-3>", self._on_right_click)

        self._configure_tags()
        self.text_area.insert("1.0", "Ноты появятся здесь", "placeholder")
        self.text_area.config(state="disabled")

        # ---------- BUTTONS ROW 1 ----------
        b1 = tk.Frame(self.root, bg=Theme.BG)
        b1.pack(fill="x", padx=26, pady=(0, 4))
        self.tracks_btn = StyledButton(b1, "🎵  Треки",
                                       self.open_track_dialog, small=True)
        self.tracks_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self.autotr_btn = StyledButton(b1, "🎼  Авто-транспозиция",
                                       self.auto_transpose_selection,
                                       small=True)
        self.autotr_btn.pack(side="left", expand=True, fill="x", padx=3)
        self.undo_btn = StyledButton(b1, "↩  Undo (Ctrl+Z)",
                                     self.undo, small=True)
        self.undo_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # ---------- BUTTONS ROW 2 ----------
        b2 = tk.Frame(self.root, bg=Theme.BG)
        b2.pack(fill="x", padx=26, pady=(0, 4))
        self.copy_btn = StyledButton(b2, "📋  Текст", self.copy_result)
        self.copy_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.code_btn = StyledButton(b2, "🧩  Код", self.copy_code)
        self.code_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.save_btn = StyledButton(b2, "💾  Сохранить", self.save_result)
        self.save_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.json_btn = StyledButton(b2, "🗂  JSON", self.export_json)
        self.json_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.log_btn = StyledButton(b2, "📜  Лог", self.open_log)
        self.log_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.log_btn.set_enabled(True)

        # ---------- FOOTER ----------
        tk.Label(self.root, text=f"AstraConv v{CURRENT_VERSION}  ·  SMisha2",
                 font=("Segoe UI", 9),
                 bg=Theme.BG, fg=Theme.MUTED).pack(pady=(2, 8))

        self._ui_ready = True
        self._update_density_slider_state()
        self._update_buttons_state(False)

    def _configure_tags(self):
        if not getattr(self, "_ui_ready", False):
            return
        size = self.font_size_var.get()
        self.text_area.tag_configure("placeholder",
                                     foreground=Theme.MUTED,
                                     justify="center",
                                     spacing1=4, spacing3=4)
        self.text_area.tag_configure("normal",
                                     foreground=Theme.TEXT,
                                     font=("Consolas", size),
                                     justify="left",
                                     spacing2=6, spacing3=8)
        self.text_area.tag_configure("chord",
                                     foreground=Theme.ACCENT,
                                     font=("Consolas", size, "bold"),
                                     justify="left",
                                     spacing2=6, spacing3=8)
        self.text_area.tag_configure("comment",
                                     foreground=Theme.MUTED,
                                     font=("Consolas", size, "italic"),
                                     justify="left",
                                     spacing1=2, spacing3=6)
        self.text_area.tag_configure("oor",
                                     foreground=Theme.ACCENT2,
                                     font=("Consolas", size, "bold italic"),
                                     justify="left")
        self.text_area.tag_configure("error",
                                     foreground=Theme.ERROR,
                                     font=("Consolas", size),
                                     justify="left")

    def _update_buttons_state(self, has_sheet):
        for b in (self.copy_btn, self.code_btn, self.save_btn,
                  self.json_btn, self.autotr_btn, self.undo_btn,
                  self.tracks_btn):
            b.set_enabled(has_sheet)

    # ------------------------------------------------------------
    #  DnD
    # ------------------------------------------------------------
    def _dz_enter(self, _):
        self.drop_zone.configure(highlightbackground=Theme.ACCENT)
        self.drop_title.configure(fg=Theme.ACCENT)

    def _dz_leave(self, _):
        self.drop_zone.configure(highlightbackground=Theme.BORDER)
        self.drop_title.configure(fg=Theme.TEXT)

    def _setup_dnd(self):
        try:
            from tkinterdnd2 import DND_FILES
        except ImportError:
            return
        for w in (self.drop_zone, self.drop_icon,
                  self.drop_title, self.drop_hint):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
            except Exception:
                pass

    def _setup_shortcuts(self):
        self.root.bind("<Control-z>", lambda e: (self.undo(), "break")[1])
        self.root.bind("<Control-Z>", lambda e: (self.undo(), "break")[1])
        self.root.bind("<Control-s>",
                       lambda e: (self._ctrl_s(), "break")[1])
        self.root.bind("<Control-S>",
                       lambda e: (self._ctrl_s(), "break")[1])
        self.root.bind("<Control-c>", self._ctrl_c)
        self.root.bind("<Control-C>", self._ctrl_c)
        self.root.bind("<Control-k>",
                       lambda e: (self.copy_code(), "break")[1])
        self.root.bind("<Control-l>",
                       lambda e: (self.open_log(), "break")[1])
        self.root.bind("<Control-t>",
                       lambda e: (self.auto_transpose_selection(),
                                  "break")[1])
        self.root.bind("<Control-u>",
                       lambda e: (self.open_update_dialog(), "break")[1])

    def _ctrl_s(self):
        if self.save_btn.enabled:
            self.save_result()

    def _ctrl_c(self, _):
        try:
            sel = self.text_area.get("sel.first", "sel.last")
            if sel.strip():
                return
        except tk.TclError:
            pass
        if self.copy_btn.enabled:
            self.copy_result()
            return "break"

    # ------------------------------------------------------------
    #  UPDATE
    # ------------------------------------------------------------
    def open_update_dialog(self):
        UpdateDialog(self.root, silent=False)

    def _auto_check_updates(self):
        # тихая проверка, без диалога при отсутствии обновления
        try:
            UpdateDialog(self.root, silent=True)
        except Exception:
            pass

    def _on_auto_update_toggle(self):
        self._settings["check_updates_on_start"] = \
            bool(self.auto_update_var.get())
        save_local_settings(self._settings)

    # ------------------------------------------------------------
    #  слайдеры
    # ------------------------------------------------------------
    def _on_auto_toggle(self):
        if not self._ui_ready:
            return
        if self.auto_density_var.get():
            self._apply_auto_density()
        self._update_density_slider_state()
        self._render()

    def _update_density_slider_state(self):
        if not self._ui_ready:
            return
        state = "disabled" if self.auto_density_var.get() else "normal"
        try:
            self.density_scale.state([state])
        except Exception:
            pass
        color = Theme.MUTED if state == "disabled" else Theme.ACCENT
        self.density_value_lbl.config(fg=color)

    def _apply_auto_density(self):
        v = self.last_auto_density
        self.density_var.set(v)
        self.density_value_lbl.config(text=str(v))
        self._setting_density = True
        try:
            self.density_scale.set(v)
        finally:
            self._setting_density = False

    def _on_density_slider(self, value):
        if not self._ui_ready or self._setting_density:
            return
        if self.auto_density_var.get():
            return
        v = int(round(float(value)))
        self.density_var.set(v)
        self.density_value_lbl.config(text=str(v))
        self._render()

    def _on_font_slider(self, value):
        if not self._ui_ready:
            return
        v = int(round(float(value)))
        self.font_size_var.set(v)
        self.font_value_lbl.config(text=str(v))
        self._configure_tags()
        self._render()

    def _on_velocity_slider(self, value):
        if not self._ui_ready:
            return
        v = int(round(float(value)))
        self.velocity_var.set(v)
        self.velocity_value_lbl.config(text=str(v))
        if self._midi_data is not None:
            self._regroup_and_render()

    def _show_progress(self, show):
        if show:
            self.progress.pack(fill="x", padx=26, pady=(0, 6),
                               before=self.status_label)
            self.progress.start(12)
        else:
            try:
                self.progress.stop()
                self.progress.pack_forget()
            except Exception:
                pass

    # ------------------------------------------------------------
    #  undo
    # ------------------------------------------------------------
    def _push_undo(self):
        if self.current_chords:
            self._undo_stack.append(
                [ChordData(notes=list(c.notes),
                           key_tokens=list(c.key_tokens),
                           index=c.index, is_break=c.is_break,
                           is_comment=c.is_comment, comment=c.comment)
                 for c in self.current_chords])
            if len(self._undo_stack) > self.MAX_UNDO:
                self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            self._flash("   ↪ нечего отменять", Theme.WARNING)
            return
        self.current_chords = self._undo_stack.pop()
        self._render()
        self._refresh_status()
        self._flash("   ↩ отменено", Theme.SUCCESS)

    # ------------------------------------------------------------
    #  файлы
    # ------------------------------------------------------------
    def select_file(self):
        path = filedialog.askopenfilename(
            title="Выберите MIDI или аудио",
            filetypes=[
                ("Все поддерживаемые",
                 "*.mid *.midi *.mp3 *.wav *.ogg *.flac *.m4a *.aac *.json"),
                ("MIDI", "*.mid *.midi"),
                ("Аудио", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac"),
                ("AstraConv sheet", "*.astra.json *.json"),
                ("Все файлы", "*.*")])
        if path:
            self.process_file(path)

    def on_drop(self, event):
        path = event.data.strip("{}")
        ext = os.path.splitext(path)[1].lower()
        if ext in MIDI_EXTS or ext in AUDIO_EXTS or ext == ".json":
            self.process_file(path)
        else:
            messagebox.showwarning("Ошибка", "Неподдерживаемый формат")

    def process_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            self.import_json(path)
            return

        is_audio = ext in AUDIO_EXTS
        self.current_is_audio = is_audio
        cleanup_midi = None

        try:
            if is_audio:
                self._set_status("⏳  Транскрипция аудио...", Theme.WARNING)
                self.root.update_idletasks()
                self._show_progress(True)
                try:
                    cleanup_midi = transcribe_audio_to_midi(path)
                finally:
                    self._show_progress(False)
                if not cleanup_midi or not os.path.exists(cleanup_midi):
                    raise RuntimeError("Транскрипция без файла")
                midi_path = cleanup_midi
            else:
                midi_path = path

            self._set_status("⏳  Разбор MIDI...", Theme.WARNING)
            self.root.update_idletasks()

            mappings = parse_freepiano_config(CONFIG_TEXT)
            note_to_key, ctrl_notes = build_maps(mappings)
            data = load_midi_events(midi_path)
            bpm, _ = compute_timing(data)

            self._midi_data = data
            self._note_to_key = note_to_key
            self._ctrl_notes = ctrl_notes
            self._tracks_info = data.get('tracks_info', [])
            self.current_file_path = path
            self.last_bpm = bpm
            self.last_auto_density = bpm_to_density(bpm)

            window_ms = self._auto_window(data, audio_mode=is_audio)
            self.last_auto_window_ms = window_ms

            self.bpm_lbl.config(text=f"BPM: {bpm:.1f}", fg=Theme.ACCENT)

            if self.auto_density_var.get():
                self._apply_auto_density()

            self._raw_notes = events_to_note_list(data)
            self._undo_stack.clear()
            self._regroup_and_render()
            self._update_buttons_state(True)

        except Exception as e:
            self._handle_error(e, path)
        finally:
            if cleanup_midi and os.path.exists(cleanup_midi):
                try:
                    os.remove(cleanup_midi)
                except Exception:
                    pass

    def _auto_window(self, data, audio_mode):
        onsets = sorted(set(t for t, k, _, _ in data['events'] if k == 1))
        if len(onsets) < 3:
            return 25.0 if audio_mode else 0.0
        bpm, ms_per_tick = compute_timing(data)
        if bpm <= 0 or ms_per_tick <= 0:
            return 25.0 if audio_mode else 0.0
        beat_ms = 60000.0 / bpm
        deltas = sorted((onsets[i + 1] - onsets[i]) * ms_per_tick
                        for i in range(len(onsets) - 1))
        deltas = [d for d in deltas if d > 0.5]
        if len(deltas) < 2:
            return 25.0 if audio_mode else 0.0
        best_i, best_r = -1, 1.0
        for i in range(1, len(deltas)):
            r = deltas[i] / deltas[i - 1]
            if r > best_r:
                best_r, best_i = r, i
        if best_i > 0 and best_r >= 2.2 and deltas[best_i] >= 15.0:
            return min(deltas[best_i - 1], beat_ms / 8.0, 40.0)
        if deltas[0] >= 20.0 and not audio_mode:
            return 0.0
        small = [d for d in deltas if d < 25.0]
        if len(small) >= 3 and len(small) / len(deltas) > 0.25:
            med = small[len(small) // 2]
            cap = 40.0 if audio_mode else 30.0
            return min(med * 2.0, beat_ms / 8.0, cap)
        return 25.0 if audio_mode else 0.0

    # ------------------------------------------------------------
    #  перегруппировка
    # ------------------------------------------------------------
    def _regroup_and_render(self):
        if self._midi_data is None or not self._raw_notes:
            return
        tpb = self._midi_data['ticks_per_beat']
        _, ms_per_tick = compute_timing(self._midi_data)

        notes = [NoteEvent(midi=n.midi, start_tick=n.start_tick,
                           end_tick=n.end_tick, velocity=n.velocity,
                           original_midi=n.original_midi)
                 for n in self._raw_notes]
        notes = quantize_events(notes, tpb, self.quantize_var.get())
        notes.sort(key=lambda e: (e.start_tick, e.end_tick))

        chords = group_into_chords(
            notes, self._note_to_key, self._ctrl_notes,
            self.last_auto_window_ms, ms_per_tick,
            self.velocity_var.get(),
            self.auto_transpose_var.get())

        if self.breaks_var.get() == "realistic":
            chords = insert_breaks_realistic(chords, self._midi_data)

        if self.show_markers_var.get() and self.auto_transpose_var.get():
            chords = inject_transpose_markers(chords)

        for i, c in enumerate(chords):
            c.index = i
        self.current_chords = chords
        self._render()
        self._refresh_status()

    def _refresh_status(self):
        if not self.current_chords or not self.current_file_path:
            return
        total_notes = sum(len(c.notes) for c in self.current_chords)
        chords_only = [c for c in self.current_chords
                       if not c.is_break and not c.is_comment]
        multi = sum(1 for c in chords_only if len(c.key_tokens) > 1)
        max_c = max((len(c.key_tokens) for c in chords_only), default=0)
        src = "MP3" if self.current_is_audio else "MIDI"

        info = (f"✦  [{src}] "
                f"{os.path.basename(self.current_file_path)}   ·   ")
        info += f"шагов: {len(chords_only)}   ·   нот: {total_notes}"
        if multi:
            info += f"   ·   аккордов: {multi}"
        if max_c > 1:
            info += f" (макс: {max_c})"
        info += f"   ·   окно: {self.last_auto_window_ms:.1f} мс"
        if self.quantize_var.get() != "off":
            info += f"   ·   квант: {self.quantize_var.get()}"
        if self.auto_transpose_var.get():
            info += "   ·   авто-транспозиция вкл"
        self._set_status(info, Theme.SUCCESS)

    # ------------------------------------------------------------
    #  рендер
    # ------------------------------------------------------------
    def _render(self):
        if not self._ui_ready:
            return
        self.text_area.config(state="normal")
        self.text_area.delete("1.0", "end")

        if not self.current_chords:
            self.text_area.insert("1.0", "Ноты появятся здесь",
                                  "placeholder")
            self.result_text = ""
            self.code_text = ""
            self.text_area.config(state="disabled")
            return

        gap = " " * self.density_var.get()
        tokens = []
        for i, ch in enumerate(self.current_chords):
            if ch.is_break:
                self.text_area.insert("end", "\n")
                tokens.append("\n")
                continue
            if ch.is_comment:
                self.text_area.insert("end", ch.comment + "\n", "comment")
                tokens.append("\n" + ch.comment)
                continue
            token = self._chord_to_token(ch.key_tokens)
            tokens.append(token)
            if any("'" in k for k in ch.key_tokens):
                tag = "oor"
            elif len(ch.key_tokens) > 1:
                tag = "chord"
            else:
                tag = "normal"
            self.text_area.insert("end", token, tag)
            if gap and i != len(self.current_chords) - 1:
                self.text_area.insert("end", gap, "sep")

        if self.density_var.get() > 0:
            self.result_text = (" " * self.density_var.get()).join(
                t for t in tokens if t != "\n")
        else:
            self.result_text = "".join(t for t in tokens if t != "\n")
        self.code_text = self._build_code(self.current_chords)
        self.text_area.config(state="disabled")

    @staticmethod
    def _chord_to_token(keys):
        if not keys:
            return ""
        if len(keys) == 1:
            return keys[0]
        return "[" + " ".join(keys) + "]"

    @staticmethod
    def _chord_to_code(keys):
        if not keys:
            return ""
        if len(keys) == 1:
            return f'"{keys[0]}"'
        return "[" + ", ".join(f'"{k}"' for k in keys) + "]"

    def _build_code(self, chords):
        lines = []
        for ch in chords:
            if ch.is_break:
                lines.append("")
                continue
            if ch.is_comment:
                lines.append(f"    # {ch.comment}")
                continue
            if ch.key_tokens:
                lines.append("    " + self._chord_to_code(ch.key_tokens) + ",")
        return "[\n" + "\n".join(lines) + "\n]"

    # ------------------------------------------------------------
    #  click handling
    # ------------------------------------------------------------
    def _on_double_click(self, event):
        if not self.current_chords:
            return
        idx = self._index_at_cursor(event)
        if idx is None:
            return
        chord = self.current_chords[idx]
        if chord.is_break or chord.is_comment:
            return
        self._push_undo()
        dlg = ChordEditDialog(self.root, chord, idx)
        if dlg.result is not None:
            chord.key_tokens = dlg.result
            self._render()
            self._refresh_status()

    def _on_right_click(self, event):
        idx = self._index_at_cursor(event)
        if idx is None:
            return
        chord = self.current_chords[idx]
        menu = tk.Menu(self.root, tearoff=0,
                       bg=Theme.SURFACE2, fg=Theme.TEXT,
                       activebackground=Theme.ACCENT,
                       activeforeground="#0a0a0a",
                       bd=0, font=("Segoe UI", 10))

        def edit():
            if chord.is_break or chord.is_comment:
                return
            self._push_undo()
            dlg = ChordEditDialog(self.root, chord, idx)
            if dlg.result is not None:
                chord.key_tokens = dlg.result
                self._render()
                self._refresh_status()

        def remove():
            self._push_undo()
            self.current_chords.pop(idx)
            self._render()
            self._refresh_status()

        def split_here():
            self._push_undo()
            self.current_chords.insert(
                idx, ChordData(notes=[], key_tokens=[], is_break=True))
            self._render()

        if not (chord.is_break or chord.is_comment):
            menu.add_command(label="✎  Изменить аккорд", command=edit)
        menu.add_command(label="✂  Разрыв строки здесь",
                         command=split_here)
        menu.add_command(label="🗑  Удалить", command=remove)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _index_at_cursor(self, event):
        try:
            pos = self.text_area.index(f"@{event.x},{event.y}")
            char_idx = self.text_area.count("1.0", pos, "chars")[0]
        except Exception:
            return None
        running = 0
        gap = self.density_var.get()
        for i, ch in enumerate(self.current_chords):
            if ch.is_break:
                running += 1
                continue
            if ch.is_comment:
                running += len(ch.comment) + 1
                continue
            tok = self._chord_to_token(ch.key_tokens)
            if char_idx <= running + len(tok):
                return i
            running += len(tok) + (gap if i != len(self.current_chords) - 1
                                    else 0)
        return None

    # ------------------------------------------------------------
    #  tracks
    # ------------------------------------------------------------
    def open_track_dialog(self):
        if not self._tracks_info:
            messagebox.showinfo("Треки", "Сначала загрузите MIDI-файл")
            return
        dlg = TrackDialog(self.root, self._tracks_info)
        if dlg.result is None:
            return
        for tr, sel in zip(self._tracks_info, dlg.result):
            tr['selected'] = sel
        self._reload_midi_with_tracks()

    def _reload_midi_with_tracks(self):
        if not self.current_file_path or not self._midi_data:
            return
        path = self._midi_data['path']
        selected_idx = {i for i, tr in enumerate(self._tracks_info)
                        if tr.get('selected', True)}
        try:
            mid = mido.MidiFile(path)
            selected_tracks = [tr for i, tr in enumerate(mid.tracks)
                               if i in selected_idx]
            if not selected_tracks:
                messagebox.showwarning("Треки", "Ни один трек не выбран")
                return
            merged = mido.merge_tracks(selected_tracks)
            tempo_changes = []
            events = []
            tick = 0
            for msg in merged:
                tick += msg.time
                if msg.type == 'set_tempo':
                    tempo_changes.append((tick, msg.tempo))
                elif msg.type == 'note_on' and msg.velocity > 0:
                    events.append((tick, 1, msg.note, msg.velocity))
                elif msg.type == 'note_off' or \
                        (msg.type == 'note_on' and msg.velocity == 0):
                    events.append((tick, 0, msg.note, 0))
            events.sort(key=lambda e: (e[0], e[1]))
            self._midi_data['events'] = events
            self._midi_data['tempo_changes'] = tempo_changes
            self._midi_data['total_ticks'] = tick
            self._raw_notes = events_to_note_list(self._midi_data)
            self._undo_stack.clear()
            self._regroup_and_render()
            self._flash("   🎵 треки обновлены", Theme.SUCCESS)
        except Exception as e:
            self._handle_error(e, path)

    # ------------------------------------------------------------
    #  auto-transpose selection
    # ------------------------------------------------------------
    def auto_transpose_selection(self):
        if not self.current_chords:
            return
        try:
            sel_start = self.text_area.index("sel.first")
            sel_end = self.text_area.index("sel.last")
            use_selection = True
        except tk.TclError:
            use_selection = False

        if not use_selection:
            idx_start, idx_end = 0, len(self.current_chords) - 1
        else:
            start_char = self.text_area.count("1.0", sel_start, "chars")[0]
            end_char = self.text_area.count("1.0", sel_end, "chars")[0]
            idx_start = idx_end = None
            running = 0
            gap = self.density_var.get()
            for i, ch in enumerate(self.current_chords):
                if ch.is_break:
                    running += 1
                    continue
                if ch.is_comment:
                    running += len(ch.comment) + 1
                    continue
                tok = self._chord_to_token(ch.key_tokens)
                lo, hi = running, running + len(tok)
                if idx_start is None and end_char >= lo:
                    idx_start = i
                if start_char <= hi:
                    idx_end = i
                running += len(tok) + (gap
                                        if i != len(self.current_chords) - 1
                                        else 0)
            if idx_start is None:
                idx_start = 0
            if idx_end is None:
                idx_end = len(self.current_chords) - 1

        if idx_start > idx_end:
            idx_start, idx_end = idx_end, idx_start

        region_notes = []
        for i in range(idx_start, idx_end + 1):
            ch = self.current_chords[i]
            if ch.is_break or ch.is_comment:
                continue
            region_notes.extend(ch.notes)
        if not region_notes:
            return

        shift = best_transposition(region_notes, self._note_to_key,
                                   self._ctrl_notes)
        if shift == 0:
            self._flash("   🎼 сдвиг не нужен", Theme.WARNING)
            return

        self._push_undo()
        for i in range(idx_start, idx_end + 1):
            ch = self.current_chords[i]
            if ch.is_break or ch.is_comment:
                continue
            tokens = []
            for n in ch.notes:
                work = n.original_midi + shift
                if work in self._ctrl_notes:
                    continue
                if work not in self._note_to_key:
                    continue
                key = self._note_to_key[work]
                if shift != 0:
                    key = key + "'"
                if key not in tokens:
                    tokens.append(key)
            ch.key_tokens = tokens
            for n in ch.notes:
                n.shift = shift

        if self.show_markers_var.get():
            filtered = [c for c in self.current_chords
                        if not c.is_comment
                        or not c.comment.startswith("Transpose by:")]
            self.current_chords = inject_transpose_markers(filtered)

        self._render()
        self._refresh_status()
        self._flash(f"   🎼 транспонировано на {shift:+d}", Theme.SUCCESS)

    # ------------------------------------------------------------
    #  JSON
    # ------------------------------------------------------------
    def export_json(self):
        if not self.current_chords:
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить как AstraConv sheet",
            defaultextension=".astra.json",
            filetypes=[("AstraConv sheet", "*.astra.json"),
                       ("JSON", "*.json")])
        if not path:
            return
        try:
            data = {
                'version': 2,
                'app_version': CURRENT_VERSION,
                'source': os.path.basename(self.current_file_path or ''),
                'bpm': self.last_bpm,
                'settings': {
                    'density': self.density_var.get(),
                    'font_size': self.font_size_var.get(),
                    'velocity': self.velocity_var.get(),
                    'auto_transpose': self.auto_transpose_var.get(),
                    'quantize': self.quantize_var.get(),
                    'breaks': self.breaks_var.get(),
                    'show_markers': self.show_markers_var.get(),
                },
                'chords': [],
            }
            for ch in self.current_chords:
                if ch.is_break:
                    data['chords'].append({'type': 'break'})
                elif ch.is_comment:
                    data['chords'].append(
                        {'type': 'comment', 'text': ch.comment})
                else:
                    data['chords'].append({
                        'type': 'chord',
                        'notes': [{'midi': n.original_midi,
                                   'shift': n.shift,
                                   'velocity': n.velocity,
                                   'start': n.start_tick,
                                   'end': n.end_tick}
                                  for n in ch.notes],
                        'tokens': list(ch.key_tokens),
                    })
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._flash("   🗂 JSON сохранён", Theme.SUCCESS)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

    def import_json(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть: {e}")
            return

        chords = []
        for raw in data.get('chords', []):
            t = raw.get('type')
            if t == 'break':
                chords.append(ChordData(notes=[], key_tokens=[],
                                        is_break=True))
            elif t == 'comment':
                chords.append(ChordData(notes=[], key_tokens=[],
                                        is_comment=True,
                                        comment=raw.get('text', '')))
            elif t == 'chord':
                notes = []
                for nn in raw.get('notes', []):
                    n = NoteEvent(midi=nn['midi'],
                                  start_tick=nn.get('start', 0),
                                  end_tick=nn.get('end', 0),
                                  velocity=nn.get('velocity', 80),
                                  original_midi=nn['midi'],
                                  shift=nn.get('shift', 0))
                    notes.append(n)
                chords.append(ChordData(notes=notes,
                                        key_tokens=list(raw.get('tokens', []))))
        for i, c in enumerate(chords):
            c.index = i

        self.current_chords = chords
        self._midi_data = None
        self._raw_notes = []
        self.current_file_path = path
        self.current_is_audio = False
        self._undo_stack.clear()

        s = data.get('settings', {})
        if 'density' in s:
            self.density_var.set(s['density'])
            self.density_value_lbl.config(text=str(s['density']))
            self._setting_density = True
            try:
                self.density_scale.set(s['density'])
            finally:
                self._setting_density = False
        if 'font_size' in s:
            self.font_size_var.set(s['font_size'])
            self.font_value_lbl.config(text=str(s['font_size']))
            self.font_scale.set(s['font_size'])
            self._configure_tags()
        if 'velocity' in s:
            self.velocity_var.set(s['velocity'])
            self.velocity_value_lbl.config(text=str(s['velocity']))
            self.velocity_scale.set(s['velocity'])
        if 'auto_transpose' in s:
            self.auto_transpose_var.set(s['auto_transpose'])
        if 'quantize' in s:
            self.quantize_var.set(s['quantize'])
        if 'breaks' in s:
            self.breaks_var.set(s['breaks'])
        if 'show_markers' in s:
            self.show_markers_var.set(s['show_markers'])

        self._render()
        self._update_buttons_state(True)
        self._set_status(
            f"✦  [JSON] {os.path.basename(path)}   ·   шагов: "
            f"{len([c for c in chords if not c.is_break and not c.is_comment])}",
            Theme.SUCCESS)
        self._flash("   🗂 JSON загружен", Theme.SUCCESS)

    # ------------------------------------------------------------
    #  error handling
    # ------------------------------------------------------------
    def _handle_error(self, e, path):
        self._midi_data = None
        self.current_chords = []
        self.current_file_path = None
        self.bpm_lbl.config(text="BPM: —", fg=Theme.MUTED)
        short = f"{type(e).__name__}: {e}"
        if len(short) > 180:
            short = short[:177] + "..."
        self._set_status(f"✖  {short}", Theme.ERROR)

        self.text_area.config(state="normal")
        self.text_area.delete("1.0", "end")
        lines = [
            "Ошибка при обработке файла",
            "",
            f"Файл: {os.path.basename(path)}",
            f"Тип:  {type(e).__name__}",
            "",
            str(e),
            "",
            "─── Traceback ───",
            traceback.format_exc(),
        ]
        if os.path.exists(TRANSCRIBE_LOG):
            lines += ["",
                      f"─── Лог: {TRANSCRIBE_LOG} ───",
                      "(кнопка 📜 Лог чтобы открыть)"]
        self.text_area.insert("1.0", "\n".join(lines), "error")
        self.text_area.config(state="disabled")
        self._update_buttons_state(False)

    def _set_status(self, text, color=None):
        self.status_base = text
        self.status_label.config(text=text, fg=color or Theme.MUTED)

    def _flash(self, suffix, color):
        self.status_label.config(text=self.status_base + suffix, fg=color)
        self.root.after(2000, lambda: self.status_label.config(
            text=self.status_base, fg=Theme.MUTED))

    # ------------------------------------------------------------
    #  copy / save / log
    # ------------------------------------------------------------
    def copy_result(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.result_text)
        self._flash("   📋 Текст скопирован", Theme.SUCCESS)

    def copy_code(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.code_text)
        self._flash("   🧩 Код скопирован", Theme.SUCCESS)

    def save_result(self):
        path = filedialog.asksaveasfilename(
            title="Сохранить результат",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.result_text)
            self._flash("   💾 Сохранено", Theme.SUCCESS)

    def open_log(self):
        if not os.path.exists(TRANSCRIBE_LOG):
            messagebox.showinfo(
                "Лог",
                f"Лог появится после первой попытки транскрипции MP3.\n\n"
                f"Путь: {TRANSCRIBE_LOG}")
            return
        try:
            os.startfile(TRANSCRIBE_LOG)
        except AttributeError:
            import platform
            if platform.system() == "Darwin":
                subprocess.Popen(["open", TRANSCRIBE_LOG])
            else:
                subprocess.Popen(["xdg-open", TRANSCRIBE_LOG])
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть: {e}")


# ═══════════════════════════════════════════════════════════════════
#                              ЗАПУСК
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
    app = AstraConvGUI(root)
    root.mainloop()
