# AstraConv v0.0.6 - Полностью исправленная версия
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import time
import os
import json
import webbrowser
import platform
import math
import random
import sys
from datetime import datetime

# Глобальные переменные для раскладки
white_keys = '1234567890qwertyuiopasdfghjklzxcvbnm'  # 36 символов
black_keys = '!@$%^*(QWETYIOPSDGHJLZCVB'           # 24 символа
BASE_NOTE = 36  # C2 - первая белая клавиша '1'
WHITE_NOTE_POSITIONS = [0, 2, 4, 5, 7, 9, 11]  # C, D, E, F, G, A, B
BLACK_NOTE_POSITIONS = [1, 3, 6, 8, 10]        # C#, D#, F#, G#, A#

def note_to_char(note):
    """Конвертация MIDI ноты в символ клавиши с учетом раскладки"""
    octave = (note - BASE_NOTE) // 12
    note_in_octave = note % 12
    
    if note_in_octave in WHITE_NOTE_POSITIONS:
        pos_in_octave = WHITE_NOTE_POSITIONS.index(note_in_octave)
        index = octave * 7 + pos_in_octave
        if 0 <= index < len(white_keys):
            return white_keys[index]
    elif note_in_octave in BLACK_NOTE_POSITIONS:
        pos_in_octave = BLACK_NOTE_POSITIONS.index(note_in_octave)
        index = octave * 5 + pos_in_octave
        if 0 <= index < len(black_keys):
            return black_keys[index]
    return ''

class MidiProcessor:
    """Отдельный класс для обработки MIDI файлов с поддержкой игровых форматов"""
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.game_formats = {
            "minecraft": self._process_for_minecraft,
            "roblox": self._process_for_roblox,
            "terraria": self._process_for_terraria
        }
    
    def process_midi(self, midi_path, game_format=None):
        """Универсальная обработка с поддержкой игровых форматов"""
        try:
            import mido
            from mido import MidiFile, tick2second
            
            mid = MidiFile(midi_path)
            
            # Собираем события
            events = []
            total_notes = 0
            max_notes = self.settings.get('max_notes', 100000)
            
            for track in mid.tracks:
                abs_time = 0
                for msg in track:
                    abs_time += msg.time
                    sec_time = tick2second(abs_time, mid.ticks_per_beat, 500000)
                    if hasattr(msg, 'type') and msg.type == 'note_on' and hasattr(msg, 'velocity') and msg.velocity > 0:
                        total_notes += 1
                        if total_notes > max_notes:
                            return f"Файл слишком большой! Максимальное количество нот: {max_notes}. Ваш файл содержит {total_notes} нот."
                        
                        if game_format:
                            events.append((sec_time, msg.note, msg.velocity))
                        else:
                            char = note_to_char(msg.note)
                            if char:
                                events.append((sec_time, char))
            
            # Для игровых форматов используем специальную обработку
            if game_format and game_format in self.game_formats:
                return self.game_formats[game_format](mid, events)
            else:
                return self._process_standard(events)
                
        except Exception as e:
            return f"Ошибка обработки: {str(e)}"
    
    def _process_standard(self, events):
        """Стандартная обработка MIDI файла с группировкой в аккорды"""
        if not events:
            return "Нет обнаруженных нот для обработки."
        
        # Сортируем события по времени
        events.sort(key=lambda x: x[0])
        
        # Группируем ноты в аккорды
        output = []
        current_time = events[0][0]
        current_chord = []
        chord_threshold = self.settings.get('chord_threshold', 0.025)
        detail_level = self.settings.get('detail_level', 'medium')
        space_between_chords = self.settings.get('space_between_chords', True)
        
        # Добавляем первую ноту
        current_chord.append(events[0][1])
        
        for i in range(1, len(events)):
            time_diff = events[i][0] - current_time
            
            if time_diff <= chord_threshold:
                current_chord.append(events[i][1])
            else:
                # Обработка текущего аккорда/ноты
                self._process_chord(current_chord, output, detail_level)
                
                # Добавляем пробел между аккордами если нужно
                if space_between_chords and output:
                    output.append(' ')
                
                current_chord = [events[i][1]]
                current_time = events[i][0]
        
        # Обработка последнего аккорда/ноты
        if current_chord:
            self._process_chord(current_chord, output, detail_level)
        
        return ''.join(output)
    
    def _process_chord(self, chord, output, detail_level):
        """Обработка одного аккорда в зависимости от уровня детализации"""
        if detail_level == 'high':
            # Максимальная детализация - каждая нота отдельно
            for note in chord:
                output.append(note)
        elif detail_level == 'low':
            # Минимальная детализация - объединяем близкие ноты
            if len(chord) > 3:
                main_notes = sorted(set(chord))[:3]
                output.append(f"[{''.join(main_notes)}]")
            else:
                if len(chord) > 1:
                    output.append(f"[{''.join(sorted(set(chord)))}]")
                else:
                    output.append(chord[0])
        else:
            # Стандартная детализация - обычные аккорды
            if len(chord) > 1:
                output.append(f"[{''.join(sorted(set(chord)))}]")
            else:
                output.append(chord[0])
    
    def _process_for_minecraft(self, midi_file, events):
        """Обработка для Minecraft 1.21.9 нотных блоков"""
        notes = []
        current_time = 0
        
        for msg in midi_file:
            current_time += msg.time
            if hasattr(msg, 'type') and msg.type == 'note_on' and hasattr(msg, 'velocity') and msg.velocity > 0:
                # Фильтрация только нот в диапазоне нотных блоков (C2-A3 = 36-57)
                if 36 <= msg.note <= 57:
                    notes.append((current_time, msg.note, msg.velocity))
        
        commands = []
        x, y, z = 0, 0, 0
        
        for i, (time, note, vel) in enumerate(notes[:50]):  # Ограничение для демо
            # Конвертация MIDI ноты в индекс нотного блока (0-24)
            block_note = max(0, min(24, note - 36))
            
            # Команда для установки нотного блока с правильной нотой
            command = (
                f"/setblock ~{x+i} ~{y} ~{z} minecraft:note_block{{"
                f"note:{block_note},powered:1b,"
                f"instrument:{self._get_mc_instrument(vel)}}}"
            )
            commands.append(command)
        
        return "\n".join(commands)
    
    def _process_for_roblox(self, midi_file, events):
        """Обработка для Roblox Piano"""
        notes = []
        current_time = 0
        
        for msg in midi_file:
            current_time += msg.time
            if hasattr(msg, 'type') and msg.type == 'note_on' and hasattr(msg, 'velocity') and msg.velocity > 0:
                # Все ноты для Roblox, но с нормализацией громкости
                normalized_vel = max(1, min(127, msg.velocity))
                notes.append((current_time, msg.note, normalized_vel))
        
        # Генерация Lua скрипта
        lua_script = """-- Roblox Piano Script generated by AstraConv v0.0.6
local piano = workspace.Piano -- Измените путь к вашему пианино
local notes = {\n"""
        
        for time, note, vel in notes[:30]:  # Ограничение для демо
            note_name = self._midi_to_note(note).replace('#', 's')
            key_name = f"Key_{note_name}"
            lua_script += f"    {{time = {time:.2f}, key = '{key_name}', velocity = {vel}}},\n"
        
        lua_script += """}

local function playNote(noteData)
    local key = piano:FindFirstChild(noteData.key)
    if key then
        key.Transparency = 0.5
        game:GetService("Debris"):AddItem(key, 0.2)
        
        -- Здесь должна быть логика нажатия клавиши
        print("Playing note:", noteData.key, "at velocity", noteData.velocity)
    end
end

local startTime = os.clock()
for _, noteData in ipairs(notes) do
    local waitTime = noteData.time - (os.clock() - startTime)
    if waitTime > 0 then wait(waitTime) end
    playNote(noteData)
end
"""
        return lua_script
    
    def _process_for_terraria(self, midi_file, events):
        """Обработка для Terraria музыкальной шкатулки"""
        notes = []
        current_time = 0
        
        try:
            import mido
        except ImportError:
            return "Ошибка: не установлен модуль mido. Пожалуйста, установите его командой: pip install mido"
        
        # Получаем ticks_per_beat из файла MIDI
        ticks_per_beat = midi_file.ticks_per_beat if hasattr(midi_file, 'ticks_per_beat') else 480
        tempo = 500000  # microseconds per beat (default)
        
        for msg in midi_file:
            if hasattr(msg, 'type') and msg.type == 'set_tempo':
                tempo = msg.tempo
            
            current_time += mido.tick2second(msg.time, ticks_per_beat, tempo) if hasattr(mido, 'tick2second') else msg.time / 1000.0
            
            if hasattr(msg, 'type') and msg.type == 'note_on' and hasattr(msg, 'velocity') and msg.velocity > 0:
                # Terraria поддерживает только основные ноты без аккордов
                if 48 <= msg.note <= 72:  # C3-C5
                    beat = int(current_time * 4)  # 4 beats per second
                    notes.append((beat, msg.note))
        
        # Формат Terraria Music Box: номер_бита:нота
        terraria_format = ""
        last_beat = -1
        
        for beat, note in notes[:20]:  # Ограничение для демо
            if beat != last_beat:
                terraria_format += f"\n{beat}: "
                last_beat = beat
            terraria_format += f"{self._midi_to_note(note)} "
        
        return f"# Terraria Music Box Data (AstraConv v0.0.6)\n{terraria_format}"
    
    def _midi_to_note(self, midi_num):
        """Конвертация MIDI номера в название ноты"""
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = (midi_num // 12) - 1
        note = notes[midi_num % 12]
        return f"{note}{octave}"
    
    def _get_mc_instrument(self, velocity):
        """Определение инструмента для Minecraft на основе громкости"""
        if velocity < 40:
            return "harp"  # Арфа
        elif velocity < 80:
            return "basedrum"  # Бас-барабан
        else:
            return "pling"  # Пианино (pling)

class AstrConvApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🚀 AstraConv v0.0.6")
        self.root.geometry("1300x800")
        self.root.minsize(1100, 700)
        
        # Установка темной темы
        self.setup_styles()
        
        # Создание атрибутов
        self.midi_path = ""
        self.processing = False
        self.visualization_active = False
        self.visualization_thread = None
        self.copying_in_progress = False
        self.current_tab = "main"
        
        # Настройки по умолчанию
        self.settings = {
            'detail_level': 'medium',  # 'high', 'medium', 'low'
            'animations': True,
            'wrap_text': False,
            'chord_threshold': 0.025,
            'max_notes': 100000,
            'show_unmapped': True,
            'space_between_chords': True,
            'background_enabled': True
        }
        
        # Загрузка сохраненных настроек
        self.load_settings()
        
        # Инициализация аудио-зависимостей
        self.pygame_available = self.check_pygame()
        self.fluidsynth_available = self.check_fluidsynth()
        self.soundfont_path = self.get_soundfont_path()
        self.soundfont_available = self.soundfont_path and os.path.exists(self.soundfont_path)
        self.audio_available = self.pygame_available and self.fluidsynth_available and self.soundfont_available
        
        # Создание виджетов
        self.create_widgets()
        
        # Горячие клавиши
        self.root.bind('<Control-m>', lambda e: self.generate_mc_commands())
        self.root.bind('<Control-r>', lambda e: self.export_roblox_script())
        self.root.bind('<Control-t>', lambda e: self.export_terraria_music_box())
        self.root.bind('<Control-o>', lambda e: self.load_midi_file())
        self.root.bind('<Control-s>', lambda e: self.save_result())
        self.root.bind('<Control-c>', lambda e: self.copy_result())
        
        # Статус-бар
        self.status_var = tk.StringVar(value="Готов к работе | AstraConv v0.0.6")
        status_bar = tk.Label(root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, 
                            anchor=tk.W, bg="#2d2d30", fg="#d4d4d4", font=("Segoe UI", 9))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Инициализация звездного фона
        if self.settings.get('background_enabled', True) and self.settings.get('animations', True):
            self.init_stars()
    
    def setup_styles(self):
        """Настройка современных стилей для интерфейса"""
        style = ttk.Style()
        
        # Используем 'clam' тему как основу для кастомизации
        style.theme_use('clam')
        
        # Темно-серая тема с акцентами
        bg_color = "#1e1e1e"
        fg_color = "#d4d4d4"
        accent_color = "#61afef"
        secondary_accent = "#c678dd"
        success_color = "#98c379"
        warning_color = "#e5c07b"
        error_color = "#e06c75"
        
        # Настройка стилей для ttk виджетов
        style.configure('TFrame', background=bg_color)
        style.configure('TLabelframe', background=bg_color, bordercolor="#444", relief=tk.SOLID)
        style.configure('TLabelframe.Label', background=bg_color, foreground=fg_color, font=("Segoe UI", 10, "bold"))
        style.configure('TNotebook', background=bg_color, borderwidth=0)
        style.configure('TNotebook.Tab', 
                       background="#2d2d30", 
                       foreground="#a9a9a9",
                       font=("Segoe UI", 10),
                       padding=[12, 6])
        style.map('TNotebook.Tab', 
                 background=[('selected', bg_color), ('active', '#3a3a3a')],
                 foreground=[('selected', accent_color), ('active', fg_color)])
        
        # Стили для кнопок
        style.configure('TButton', 
                       font=("Segoe UI", 10),
                       background="#2d2d30",
                       foreground=fg_color,
                       borderwidth=1,
                       focusthickness=3,
                       focuscolor='none')
        style.map('TButton',
                 background=[('active', '#3a3a3a'), ('pressed', '#454545')],
                 foreground=[('active', fg_color), ('pressed', fg_color)])
        
        # Стили для кнопок с акцентами
        style.configure('Accent.TButton',
                       font=("Segoe UI", 10, "bold"),
                       background=accent_color,
                       foreground="#1e1e1e")
        style.map('Accent.TButton',
                 background=[('active', '#4da6ff'), ('pressed', '#3d94f5')])
        
        # Стили для переключателей
        style.configure('TCheckbutton',
                       background=bg_color,
                       foreground=fg_color,
                       font=("Segoe UI", 10))
        style.configure('TRadiobutton',
                       background=bg_color,
                       foreground=fg_color,
                       font=("Segoe UI", 10))
        
        # Стили для выпадающих списков
        style.configure('TMenubutton',
                       background="#2d2d30",
                       foreground=fg_color,
                       font=("Segoe UI", 10))
        
        # Корневой фон
        self.root.configure(bg=bg_color)
        
        # Стили для ползунков
        style.configure('Horizontal.TScale',
                       background=bg_color,
                       troughcolor="#3a3a3a",
                       sliderrelief=tk.FLAT)
        
        # Создаем стиль для заголовков
        self.title_font = ("Segoe UI", 14, "bold")
        self.subtitle_font = ("Segoe UI", 11)
        self.normal_font = ("Segoe UI", 10)
        
        # Стиль для вкладок
        style.configure('Custom.TNotebook', background=bg_color, borderwidth=0)
        style.configure('Custom.TNotebook.Tab', 
                       background="#2d2d30", 
                       foreground="#a9a9a9",
                       font=("Segoe UI", 10),
                       padding=[12, 6])
        style.map('Custom.TNotebook.Tab', 
                 background=[('selected', bg_color), ('active', '#3a3a3a')],
                 foreground=[('selected', accent_color), ('active', fg_color)])
    
    def check_pygame(self):
        """Проверка доступности pygame"""
        try:
            import pygame
            pygame.mixer.init()
            return True
        except ImportError:
            return False
        except Exception:
            return False
    
    def check_fluidsynth(self):
        """Проверка доступности fluidsynth"""
        try:
            from midi2audio import FluidSynth
            return True
        except ImportError:
            return False
    
    def get_soundfont_path(self):
        """Определение пути к SoundFont для Windows"""
        # Проверяем стандартные места
        possible_paths = [
            os.path.join(os.environ.get('USERPROFILE', ''), 'Documents', 'SoundFonts', 'FluidR3_GM.sf2'),
            os.path.join(os.environ.get('USERPROFILE', ''), 'SoundFonts', 'FluidR3_GM.sf2'),
            'C:\\SoundFonts\\FluidR3_GM.sf2',
            os.path.join(os.path.dirname(__file__), 'FluidR3_GM.sf2'),
            os.path.join(os.path.dirname(__file__), 'soundfonts', 'FluidR3_GM.sf2')
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def create_widgets(self):
        """Создание современного интерфейса"""
        # Основной контейнер с панелью навигации
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Левая панель - навигация
        nav_frame = ttk.Frame(main_pane, width=200)
        nav_frame.pack_propagate(False)
        
        # Логотип и заголовок
        logo_frame = ttk.Frame(nav_frame)
        logo_frame.pack(fill=tk.X, padx=10, pady=15)
        
        logo_label = tk.Label(logo_frame, text="🎮 AstraConv", 
                            font=("Segoe UI", 16, "bold"), 
                            fg="#61afef", bg="#1e1e1e")
        logo_label.pack(anchor=tk.W)
        
        subtitle_label = tk.Label(logo_frame, 
                                text="MIDI → Игровые форматы",
                                font=("Segoe UI", 9), fg="#a9a9a9", bg="#1e1e1e")
        subtitle_label.pack(anchor=tk.W, pady=(0, 5))
        
        # Кнопки навигации
        nav_buttons = [
            ("🏠 Основное", "main"),
            ("⚙️ Настройки", "settings"),
            ("🎮 Minecraft", "minecraft"),
            ("🎵 Roblox", "roblox"),
            ("⛏️ Terraria", "terraria"),
            ("📊 Визуализация", "visualization")
        ]
        
        self.nav_buttons = {}
        for text, tag in nav_buttons:
            if tag == "main":
                btn = ttk.Button(nav_frame, text=text, style="Accent.TButton")
            else:
                btn = ttk.Button(nav_frame, text=text, style="TButton")
            btn.pack(fill=tk.X, padx=10, pady=5)
            btn.bind("<Button-1>", lambda e, t=tag: self.switch_tab(t))
            self.nav_buttons[tag] = btn
        
        # Правая панель - контент
        self.content_frame = ttk.Frame(main_pane)
        
        # Добавление панелей в разделитель
        main_pane.add(nav_frame)
        main_pane.add(self.content_frame, weight=1)
        
        # Создание вкладок контента
        self.tab_content = {}
        
        # Создаем все вкладки
        self.create_main_tab()
        self.create_settings_tab()
        self.create_minecraft_tab()
        self.create_roblox_tab()
        self.create_terraria_tab()
        self.create_visualization_tab()
        
        # Показываем основную вкладку
        self.switch_tab("main")
    
    def create_main_tab(self):
        """Создание основной вкладки"""
        main_tab = ttk.Frame(self.content_frame)
        self.tab_content["main"] = main_tab
        
        # Загрузка файла
        load_frame = ttk.LabelFrame(main_tab, text="📁 Загрузка MIDI файла")
        load_frame.pack(fill=tk.X, padx=15, pady=10)
        
        file_frame = ttk.Frame(load_frame)
        file_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.file_label = ttk.Label(file_frame, text="Файл не выбран", font=self.subtitle_font)
        self.file_label.pack(side=tk.LEFT, padx=5)
        
        btn_frame = ttk.Frame(load_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="📂 Выбрать MIDI файл", command=self.load_midi_file).pack(side=tk.LEFT, padx=5)
        if self.audio_available:
            ttk.Button(btn_frame, text="▶️ Воспроизвести MIDI", command=self.play_midi).pack(side=tk.LEFT, padx=5)
        
        # Настройки обработки
        settings_frame = ttk.LabelFrame(main_tab, text="⚙️ Настройки обработки")
        settings_frame.pack(fill=tk.X, padx=15, pady=10)
        
        # Уровень детализации
        detail_frame = ttk.Frame(settings_frame)
        detail_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(detail_frame, text="Уровень детализации:", font=self.normal_font).pack(side=tk.LEFT)
        
        self.detail_var = tk.StringVar(value=self.settings['detail_level'])
        detail_menu = ttk.OptionMenu(detail_frame, self.detail_var, self.settings['detail_level'],
                                   "low", "medium", "high", "ultra")
        detail_menu.pack(side=tk.LEFT, padx=10)
        
        # Порог аккордов
        chord_frame = ttk.Frame(settings_frame)
        chord_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(chord_frame, text="Порог аккордов:", font=self.normal_font).pack(side=tk.LEFT)
        
        self.chord_threshold = tk.DoubleVar(value=self.settings['chord_threshold'])
        chord_scale = ttk.Scale(chord_frame, from_=0.01, to=0.2, 
                              variable=self.chord_threshold, length=200)
        chord_scale.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(chord_frame, textvariable=self.chord_threshold, font=self.normal_font).pack(side=tk.LEFT, padx=5)
        
        # Дополнительные настройки
        options_frame = ttk.Frame(settings_frame)
        options_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.space_var = tk.BooleanVar(value=self.settings['space_between_chords'])
        ttk.Checkbutton(options_frame, text="Пробелы между аккордами", variable=self.space_var).pack(side=tk.LEFT, padx=10)
        
        self.wrap_var = tk.BooleanVar(value=self.settings['wrap_text'])
        ttk.Checkbutton(options_frame, text="Перенос строк", variable=self.wrap_var).pack(side=tk.LEFT, padx=10)
        
        # Результат обработки
        result_frame = ttk.LabelFrame(main_tab, text="📤 Результат обработки")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        btn_container = ttk.Frame(result_frame)
        btn_container.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_container, text="🚀 Начать обработку", style="Accent.TButton", 
                 command=self.start_processing).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_container, text="💾 Сохранить результат", command=self.save_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_container, text="📋 Копировать", command=self.copy_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_container, text="🗑️ Очистить", command=self.clear_result).pack(side=tk.LEFT, padx=5)
        
        # Поле результата
        self.result_text = scrolledtext.ScrolledText(
            result_frame, 
            wrap=tk.WORD if self.settings['wrap_text'] else tk.NONE,
            font=("Consolas", 11),
            bg="#2d2d30",
            fg="#d4d4d4",
            insertbackground="#61afef",
            highlightthickness=1,
            highlightbackground="#444"
        )
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.result_text.insert(tk.END, "Результат будет показан здесь после обработки...")
        
        # Информационная панель
        info_frame = ttk.Frame(main_tab)
        info_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.bpm_label = ttk.Label(info_frame, text="BPM: --", font=self.normal_font)
        self.bpm_label.pack(side=tk.LEFT, padx=10)
        
        self.note_count_label = ttk.Label(info_frame, text="Нот: 0", font=self.normal_font)
        self.note_count_label.pack(side=tk.LEFT, padx=10)
        
        self.chord_count_label = ttk.Label(info_frame, text="Аккордов: 0", font=self.normal_font)
        self.chord_count_label.pack(side=tk.LEFT, padx=10)
        
        self.warning_label = ttk.Label(info_frame, text="", font=self.normal_font, foreground="#e06c75")
        self.warning_label.pack(side=tk.RIGHT, padx=10)
    
    def create_settings_tab(self):
        """Создание вкладки настроек"""
        settings_tab = ttk.Frame(self.content_frame)
        self.tab_content["settings"] = settings_tab
        
        # Заголовок
        title_label = tk.Label(
            settings_tab,
            text="⚙️ Настройки AstraConv",
            font=("Segoe UI", 18, "bold"),
            fg="#61afef",
            bg="#1e1e1e"
        )
        title_label.pack(fill=tk.X, padx=15, pady=15)
        
        # Уровень детализации
        detail_frame = ttk.LabelFrame(settings_tab, text="Уровень детализации")
        detail_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.detail_var_settings = tk.StringVar(value=self.settings['detail_level'])
        
        ttk.Radiobutton(detail_frame, text="Максимальная (каждая нота отдельно, аккорды сохраняются)",
                      variable=self.detail_var_settings, value="high").pack(anchor="w", pady=2, padx=10)
        ttk.Radiobutton(detail_frame, text="Стандартная (оптимальный баланс между деталями и читаемостью)",
                      variable=self.detail_var_settings, value="medium").pack(anchor="w", pady=2, padx=10)
        ttk.Radiobutton(detail_frame, text="Минимальная (группировка близких нот для упрощенного отображения)",
                      variable=self.detail_var_settings, value="low").pack(anchor="w", pady=2, padx=10)
        
        # Анимации и фон
        anim_frame = ttk.LabelFrame(settings_tab, text="Фон и анимации")
        anim_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.anim_var = tk.BooleanVar(value=self.settings['animations'])
        ttk.Checkbutton(anim_frame, text="Включить анимацию звезд",
                      variable=self.anim_var).pack(anchor="w", pady=5, padx=10)
        
        self.bg_var = tk.BooleanVar(value=self.settings.get('background_enabled', True))
        ttk.Checkbutton(anim_frame, text="Показывать фон со звездами",
                      variable=self.bg_var).pack(anchor="w", pady=5, padx=10)
        
        # Форматирование текста
        text_frame = ttk.LabelFrame(settings_tab, text="Форматирование текста")
        text_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.wrap_var_settings = tk.BooleanVar(value=self.settings['wrap_text'])
        ttk.Checkbutton(text_frame, text="Переносить текст на новую строку",
                      variable=self.wrap_var_settings).pack(anchor="w", pady=5, padx=10)
        
        self.space_var_settings = tk.BooleanVar(value=self.settings['space_between_chords'])
        ttk.Checkbutton(text_frame, text="Добавлять пробелы между аккордами",
                      variable=self.space_var_settings).pack(anchor="w", pady=5, padx=10)
        
        # Порог аккордов
        chord_frame = ttk.LabelFrame(settings_tab, text="Порог объединения нот в аккорды")
        chord_frame.pack(fill=tk.X, padx=15, pady=10)
        
        explanation = (
            "Этот параметр определяет, насколько близко по времени должны следовать ноты,\n"
            "чтобы считаться частью одного аккорда. Меньшее значение делает аккорды более точными,\n"
            "но может разбить действительно одновременные ноты. Значение в секундах."
        )
        tk.Label(chord_frame, text=explanation,
                font=("Segoe UI", 9), bg="#1e1e1e", fg="#d4d4d4", justify="left", wraplength=500).pack(anchor="w", pady=5, padx=10)
        
        self.chord_threshold_var = tk.DoubleVar(value=self.settings['chord_threshold'])
        chord_scale = tk.Scale(chord_frame, from_=0.01, to=0.1, resolution=0.005,
                             orient="horizontal", variable=self.chord_threshold_var,
                             font=("Segoe UI", 9), bg="#1e1e1e", fg="#d4d4d4",
                             highlightthickness=0, troughcolor="#2d2d30")
        chord_scale.pack(fill="x", pady=5, padx=10)
        
        # Добавляем примеры значений
        example_frame = tk.Frame(chord_frame, bg="#1e1e1e")
        example_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(example_frame, text="0.01с = Очень точные аккорды", font=("Segoe UI", 8), bg="#1e1e1e", fg="#c678dd").pack(side="left")
        tk.Label(example_frame, text="0.05с = Стандарт (рекомендуется)", font=("Segoe UI", 8), bg="#1e1e1e", fg="#98c379").pack(side="left", padx=10)
        tk.Label(example_frame, text="0.10с = Максимальная группировка", font=("Segoe UI", 8), bg="#1e1e1e", fg="#61afef").pack(side="left")
        
        # Кнопки применения
        btn_frame = ttk.Frame(settings_tab)
        btn_frame.pack(fill=tk.X, padx=15, pady=15)
        
        ttk.Button(btn_frame, text="Применить настройки", style="Accent.TButton",
                 command=self.apply_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Сбросить к стандартным", 
                 command=self.reset_settings).pack(side=tk.RIGHT, padx=5)
    
    def create_minecraft_tab(self):
        """Создание вкладки для Minecraft"""
        mc_tab = ttk.Frame(self.content_frame)
        self.tab_content["minecraft"] = mc_tab
        
        # Заголовок
        title_label = tk.Label(
            mc_tab,
            text="🎮 Экспорт для Minecraft 1.21.9",
            font=("Segoe UI", 18, "bold"),
            fg="#61afef",
            bg="#1e1e1e"
        )
        title_label.pack(fill=tk.X, padx=15, pady=15)
        
        # Описание
        desc_frame = ttk.LabelFrame(mc_tab, text="Информация")
        desc_frame.pack(fill=tk.X, padx=15, pady=10)
        
        desc_text = (
            "Генерирует команды /setblock для создания нотных блоков в Minecraft 1.21.9\n"
            "Поддерживаемые инструменты:\n"
            "- harp (арфа) - для тихих нот\n"
            "- basedrum (бас-барабан) - для средних по громкости нот\n"
            "- pling (пианино) - для громких нот\n"
            "Диапазон нот: C2-A3 (36-57 MIDI)"
        )
        tk.Label(desc_frame, text=desc_text,
                font=("Segoe UI", 10), bg="#1e1e1e", fg="#d4d4d4", justify="left", wraplength=600).pack(pady=10, padx=10)
        
        # Кнопка генерации
        btn_frame = ttk.Frame(mc_tab)
        btn_frame.pack(fill=tk.X, padx=15, pady=10)
        
        ttk.Button(btn_frame, text="🚀 Сгенерировать команды Minecraft", style="Accent.TButton",
                 command=self.generate_mc_commands).pack(side=tk.LEFT, padx=5)
        
        # Результат
        result_frame = ttk.LabelFrame(mc_tab, text="Команды для Minecraft")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        self.mc_result = scrolledtext.ScrolledText(
            result_frame, 
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg="#2d2d30",
            fg="#61afef",
            insertbackground="#61afef",
            highlightthickness=1,
            highlightbackground="#444"
        )
        self.mc_result.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.mc_result.insert(tk.END, "// Команды Minecraft появятся здесь после генерации")
    
    def create_roblox_tab(self):
        """Создание вкладки для Roblox"""
        rb_tab = ttk.Frame(self.content_frame)
        self.tab_content["roblox"] = rb_tab
        
        # Заголовок
        title_label = tk.Label(
            rb_tab,
            text="🎵 Экспорт для Roblox Piano",
            font=("Segoe UI", 18, "bold"),
            fg="#98c379",
            bg="#1e1e1e"
        )
        title_label.pack(fill=tk.X, padx=15, pady=15)
        
        # Описание
        desc_frame = ttk.LabelFrame(rb_tab, text="Информация")
        desc_frame.pack(fill=tk.X, padx=15, pady=10)
        
        desc_text = (
            "Генерирует Lua скрипт для автоматического воспроизведения на Roblox пианино\n"
            "Требуется настройка скрипта под вашу модель пианино\n"
            "Поддерживает громкость для эффектов нажатия клавиш\n"
            "Диапазон нот: C1-C7 (все доступные ноты)"
        )
        tk.Label(desc_frame, text=desc_text,
                font=("Segoe UI", 10), bg="#1e1e1e", fg="#d4d4d4", justify="left", wraplength=600).pack(pady=10, padx=10)
        
        # Кнопка генерации
        btn_frame = ttk.Frame(rb_tab)
        btn_frame.pack(fill=tk.X, padx=15, pady=10)
        
        ttk.Button(btn_frame, text="🚀 Экспортировать Lua скрипт для Roblox", style="Accent.TButton",
                 command=self.export_roblox_script).pack(side=tk.LEFT, padx=5)
        
        # Результат
        result_frame = ttk.LabelFrame(rb_tab, text="Lua скрипт для Roblox")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        self.rb_result = scrolledtext.ScrolledText(
            result_frame, 
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg="#2d2d30",
            fg="#98c379",
            insertbackground="#98c379",
            highlightthickness=1,
            highlightbackground="#444"
        )
        self.rb_result.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.rb_result.insert(tk.END, "-- Lua скрипт для Roblox появится здесь после экспорта")
    
    def create_terraria_tab(self):
        """Создание вкладки для Terraria"""
        terraria_tab = ttk.Frame(self.content_frame)
        self.tab_content["terraria"] = terraria_tab
        
        # Заголовок
        title_label = tk.Label(
            terraria_tab,
            text="⛏️ Экспорт для Terraria Music Box",
            font=("Segoe UI", 18, "bold"),
            fg="#c678dd",
            bg="#1e1e1e"
        )
        title_label.pack(fill=tk.X, padx=15, pady=15)
        
        # Описание
        desc_frame = ttk.LabelFrame(terraria_tab, text="Информация")
        desc_frame.pack(fill=tk.X, padx=15, pady=10)
        
        desc_text = (
            "Генерирует данные в формате для музыкальной шкатулки Terraria\n"
            "Поддерживает ноты только в диапазоне C3-C5 (48-72 MIDI)\n"
            "Формат: номер_удара: нота1 нота2...\n"
            "Для импорта скопируйте результат в файл .txt и используйте в Terraria"
        )
        tk.Label(desc_frame, text=desc_text,
                font=("Segoe UI", 10), bg="#1e1e1e", fg="#d4d4d4", justify="left", wraplength=600).pack(pady=10, padx=10)
        
        # Кнопка генерации
        btn_frame = ttk.Frame(terraria_tab)
        btn_frame.pack(fill=tk.X, padx=15, pady=10)
        
        ttk.Button(btn_frame, text="🚀 Экспортировать для Terraria", style="Accent.TButton",
                 command=self.export_terraria_music_box).pack(side=tk.LEFT, padx=5)
        
        # Результат
        result_frame = ttk.LabelFrame(terraria_tab, text="Данные для Terraria Music Box")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        self.terraria_result = scrolledtext.ScrolledText(
            result_frame, 
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg="#2d2d30",
            fg="#c678dd",
            insertbackground="#c678dd",
            highlightthickness=1,
            highlightbackground="#444"
        )
        self.terraria_result.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.terraria_result.insert(tk.END, "# Данные для Terraria появятся здесь после экспорта")
    
    def create_visualization_tab(self):
        """Создание вкладки визуализации"""
        viz_tab = ttk.Frame(self.content_frame)
        self.tab_content["visualization"] = viz_tab
        
        # Заголовок
        title_label = tk.Label(
            viz_tab,
            text="📊 Визуализация MIDI файла",
            font=("Segoe UI", 18, "bold"),
            fg="#e5c07b",
            bg="#1e1e1e"
        )
        title_label.pack(fill=tk.X, padx=15, pady=15)
        
        # Описание
        desc_frame = ttk.LabelFrame(viz_tab, text="Информация")
        desc_frame.pack(fill=tk.X, padx=15, pady=10)
        
        desc_text = (
            "Визуализация нот MIDI файла в реальном времени\n"
            "Показывает, какие ноты играются и когда\n"
            "Подсветка клавиш при воспроизведении\n"
            "Требуется загруженный MIDI файл"
        )
        tk.Label(desc_frame, text=desc_text,
                font=("Segoe UI", 10), bg="#1e1e1e", fg="#d4d4d4", justify="left", wraplength=600).pack(pady=10, padx=10)
        
        # Кнопки управления
        btn_frame = ttk.Frame(viz_tab)
        btn_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.play_btn = ttk.Button(btn_frame, text="▶️ Начать визуализацию", 
                                 command=self.play_visualization)
        self.play_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(btn_frame, text="⏹️ Стоп", 
                                 command=self.stop_visualization, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # Canvas для визуализации
        viz_frame = ttk.LabelFrame(viz_tab, text="Визуализация нот")
        viz_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        self.viz_canvas = tk.Canvas(viz_frame, height=150, bg="#2d2d30", highlightthickness=1, 
                                  highlightbackground="#444")
        self.viz_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Отрисовка клавиатуры
        self.draw_keyboard()
    
    def draw_keyboard(self):
        """Отрисовка клавиатуры для визуализации"""
        if not hasattr(self, 'viz_canvas'):
            return
            
        self.viz_canvas.delete("all")
        width = self.viz_canvas.winfo_width() or 1000
        height = 150
        
        # Белые клавиши
        white_keys = 15
        white_width = width // white_keys
        
        for i in range(white_keys):
            x1 = i * white_width
            x2 = x1 + white_width
            self.viz_canvas.create_rectangle(x1, 10, x2, height-10, 
                                            fill="#FFFFFF", outline="#444")
        
        # Чёрные клавиши (упрощённо)
        black_keys = [1, 3, 6, 8, 10]  # Позиции чёрных клавиш
        black_width = white_width * 0.6
        
        for i in black_keys:
            if i < white_keys:
                x1 = i * white_width - black_width//2
                x2 = x1 + black_width
                self.viz_canvas.create_rectangle(x1, 10, x2, height//2, 
                                                fill="#333", outline="#444")
    
    def switch_tab(self, tab_name):
        """Переключение между вкладками"""
        # Сброс стилей кнопок
        for btn in self.nav_buttons.values():
            btn.configure(style="TButton")
        
        # Установка стиля для активной кнопки
        self.nav_buttons[tab_name].configure(style="Accent.TButton")
        
        # Скрытие всех вкладок
        for tab in self.tab_content.values():
            tab.pack_forget()
        
        # Отображение выбранной вкладки
        self.tab_content[tab_name].pack(fill=tk.BOTH, expand=True)
        self.current_tab = tab_name
        
        # Обновление отображения при переключении на вкладку визуализации
        if tab_name == "visualization":
            self.draw_keyboard()
    
    def apply_settings(self):
        """Применение настроек"""
        self.settings['detail_level'] = self.detail_var_settings.get()
        self.settings['animations'] = self.anim_var.get()
        self.settings['background_enabled'] = self.bg_var.get()
        self.settings['wrap_text'] = self.wrap_var_settings.get()
        self.settings['chord_threshold'] = self.chord_threshold_var.get()
        self.settings['space_between_chords'] = self.space_var_settings.get()
        
        # Обновление интерфейса
        self.result_text.config(wrap=tk.WORD if self.settings['wrap_text'] else tk.NONE)
        
        # Перезапуск фона при необходимости
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.delete("all")
            if self.settings['background_enabled'] and self.settings['animations']:
                self.init_stars()
        
        # Сохранение настроек
        self.save_settings()
        
        self.status_var.set(f"Настройки применены | Уровень детализации: {self.settings['detail_level']}")
    
    def reset_settings(self):
        """Сброс настроек к значениям по умолчанию"""
        self.settings = {
            'detail_level': 'medium',
            'animations': True,
            'wrap_text': False,
            'chord_threshold': 0.025,
            'max_notes': 100000,
            'show_unmapped': True,
            'space_between_chords': True,
            'background_enabled': True
        }
        
        # Обновление интерфейса
        self.detail_var_settings.set(self.settings['detail_level'])
        self.anim_var.set(self.settings['animations'])
        self.bg_var.set(self.settings['background_enabled'])
        self.wrap_var_settings.set(self.settings['wrap_text'])
        self.chord_threshold_var.set(self.settings['chord_threshold'])
        self.space_var_settings.set(self.settings['space_between_chords'])
        
        self.result_text.config(wrap=tk.WORD if self.settings['wrap_text'] else tk.NONE)
        
        # Перезапуск фона
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.delete("all")
            if self.settings['background_enabled'] and self.settings['animations']:
                self.init_stars()
        
        # Сохранение настроек
        self.save_settings()
        
        self.status_var.set("Настройки сброшены к значениям по умолчанию")
    
    def load_settings(self):
        """Загрузка настроек из файла"""
        try:
            settings_path = "astrconv_settings.json"
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
    
    def save_settings(self):
        """Сохранение настроек в файл"""
        try:
            settings_path = "astrconv_settings.json"
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")
    
    def load_midi_file(self):
        """Загрузка MIDI файла"""
        self.midi_path = filedialog.askopenfilename(
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")]
        )
        
        if self.midi_path:
            filename = os.path.basename(self.midi_path)
            self.file_label.config(text=f"Выбран файл: {filename}")
            self.status_var.set(f"Загружен файл: {filename}")
            
            # Очистка предыдущих результатов
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "Файл загружен. Нажмите 'Начать обработку' для конвертации.")
    
    def process_midi_background(self, game_format=None):
        """Фоновая обработка MIDI"""
        try:
            # Создание обработчика
            processor = MidiProcessor({
                'detail_level': self.detail_var.get(),
                'chord_threshold': self.chord_threshold.get(),
                'space_between_chords': self.space_var.get(),
                'max_notes': self.settings['max_notes'],
                'wrap_text': self.wrap_var.get()
            })
            
            # Обработка
            result = processor.process_midi(self.midi_path, game_format)
            
            # Обновление интерфейса
            self.root.after(0, lambda: self.update_result(result))
            
        except Exception as e:
            error_msg = f"Ошибка обработки:\n{str(e)}"
            self.root.after(0, lambda: self.result_text.insert(tk.END, error_msg))
        finally:
            self.processing = False
            self.root.after(0, lambda: self.status_var.set("Обработка завершена | Готов к работе"))
    
    def update_result(self, result):
        """Обновление результатов обработки"""
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, result)
        
        # Обновление информационной панели
        if "Ошибка" in result or "Файл слишком большой" in result:
            self.warning_label.config(text="⚠️ Ошибка обработки")
        else:
            # Простой подсчет нот и аккордов для демонстрации
            note_count = sum(1 for c in result if c in white_keys + black_keys)
            chord_count = result.count('[') + result.count(']')
            self.note_count_label.config(text=f"Нот: {note_count}")
            self.chord_count_label.config(text=f"Аккордов: {chord_count}")
            self.warning_label.config(text="")
    
    def start_processing(self):
        """Начало обработки MIDI файла"""
        if not self.midi_path:
            messagebox.showwarning("Предупреждение", "Сначала загрузите MIDI файл!")
            return
        
        if self.processing:
            messagebox.showinfo("Информация", "Обработка уже запущена!")
            return
        
        # Отображение статуса
        self.status_var.set("Обработка начинается...")
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, "Обработка начинается...\n")
        self.root.update()
        
        # Запуск в отдельном потоке
        self.processing = True
        threading.Thread(target=self.process_midi_background, daemon=True).start()
    
    def save_result(self):
        """Сохранение результата в файл"""
        content = self.result_text.get(1.0, tk.END).strip()
        
        if not content or content == "Результат будет показан здесь после обработки...":
            messagebox.showinfo("Информация", "Нет данных для сохранения!")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[
                ("Текстовые файлы", "*.txt"),
                ("JSON файлы", "*.json"),
                ("Lua скрипты", "*.lua"),
                ("Все файлы", "*.*")
            ]
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.status_var.set(f"✅ Результат сохранён: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{str(e)}")
    
    def copy_result(self):
        """Копирование результата"""
        if self.copying_in_progress:
            return
        
        content = self.result_text.get(1.0, tk.END).strip()
        
        if not content or content == "Результат будет показан здесь после обработки...":
            messagebox.showinfo("Информация", "Нет данных для копирования!")
            return
        
        try:
            self.copying_in_progress = True
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status_var.set("✅ Результат скопирован в буфер обмена!")
            
            # Эффектная анимация подсветки
            original_bg = self.result_text.cget("bg")
            self.result_text.config(bg="#3a3a00")
            
            def fade_back(step=0):
                if step < 8:
                    intensity = 1.0 - step * 0.12
                    color = f'#{int(58*intensity):02x}{int(58*intensity):02x}{int(0):02x}'
                    self.result_text.config(bg=color)
                    self.root.after(50, lambda: fade_back(step + 1))
                else:
                    self.result_text.config(bg=original_bg)
            
            fade_back()
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать в буфер обмена:\n{str(e)}")
        finally:
            self.copying_in_progress = False
            self.root.after(2000, lambda: self.status_var.set("Готов к работе | AstraConv v0.0.6"))
    
    def clear_result(self):
        """Очистка результатов"""
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, "Результат будет показан здесь после обработки...")
        self.note_count_label.config(text="Нот: 0")
        self.chord_count_label.config(text="Аккордов: 0")
        self.warning_label.config(text="")
        self.status_var.set("Результаты очищены")
    
    def generate_mc_commands(self):
        """Генерация команд для Minecraft"""
        if not self.midi_path:
            messagebox.showwarning("Предупреждение", "Сначала загрузите MIDI файл!")
            return
        
        self.status_var.set("Генерация команд Minecraft...")
        self.root.update()
        
        processor = MidiProcessor()
        commands = processor.process_midi(self.midi_path, "minecraft")
        
        self.mc_result.delete(1.0, tk.END)
        self.mc_result.insert(tk.END, commands)
        
        # Копирование в буфер
        self.root.clipboard_clear()
        self.root.clipboard_append(commands)
        
        self.status_var.set("✅ Команды Minecraft скопированы в буфер обмена!")
        self.root.after(3000, lambda: self.status_var.set("Готов к работе | AstraConv v0.0.6"))
    
    def export_roblox_script(self):
        """Экспорт Lua скрипта для Roblox"""
        if not self.midi_path:
            messagebox.showwarning("Предупреждение", "Сначала загрузите MIDI файл!")
            return
        
        self.status_var.set("Генерация Lua скрипта для Roblox...")
        self.root.update()
        
        processor = MidiProcessor()
        script = processor.process_midi(self.midi_path, "roblox")
        
        self.rb_result.delete(1.0, tk.END)
        self.rb_result.insert(tk.END, script)
        
        self.status_var.set("✅ Lua скрипт для Roblox сгенерирован!")
        self.root.after(3000, lambda: self.status_var.set("Готов к работе | AstraConv v0.0.6"))
    
    def export_terraria_music_box(self):
        """Экспорт данных для Terraria"""
        if not self.midi_path:
            messagebox.showwarning("Предупреждение", "Сначала загрузите MIDI файл!")
            return
        
        self.status_var.set("Генерация данных для Terraria...")
        self.root.update()
        
        processor = MidiProcessor()
        data = processor.process_midi(self.midi_path, "terraria")
        
        self.terraria_result.delete(1.0, tk.END)
        self.terraria_result.insert(tk.END, data)
        
        self.status_var.set("✅ Данные для Terraria сгенерированы!")
        self.root.after(3000, lambda: self.status_var.set("Готов к работе | AstraConv v0.0.6"))
    
    def play_midi(self):
        """Воспроизведение MIDI файла"""
        if not self.midi_path:
            messagebox.showwarning("Предупреждение", "Сначала загрузите MIDI файл!")
            return
        
        if not self.audio_available:
            messagebox.showwarning("Предупреждение", "Аудио недоступно. Проверьте установку SoundFont.")
            return
        
        try:
            from midi2audio import FluidSynth
            import pygame
            
            # Конвертация MIDI в WAV для воспроизведения
            wav_path = "temp_audio.wav"
            fs = FluidSynth(self.soundfont_path)
            fs.midi_to_audio(self.midi_path, wav_path)
            
            # Воспроизведение
            pygame.mixer.music.load(wav_path)
            pygame.mixer.music.play()
            
            self.status_var.set("▶️ Воспроизведение MIDI...")
            while pygame.mixer.music.get_busy():
                self.root.update()
                time.sleep(0.1)
            
            # Удаляем временный файл
            if os.path.exists(wav_path):
                pygame.mixer.music.unload()
                os.remove(wav_path)
            
            self.status_var.set("Готов к работе | AstraConv v0.0.6")
        except Exception as e:
            error_msg = f"Ошибка воспроизведения:\n{str(e)}"
            messagebox.showerror("Ошибка", error_msg)
            self.status_var.set("Ошибка воспроизведения | Проверьте SoundFont")
    
    def play_visualization(self):
        """Запуск визуализации воспроизведения"""
        if not self.midi_path:
            messagebox.showwarning("Предупреждение", "Сначала загрузите MIDI файл!")
            return
        
        self.visualization_active = True
        self.play_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("▶️ Визуализация запущена...")
        
        # Запуск в отдельном потоке
        self.visualization_thread = threading.Thread(target=self._visualization_worker, daemon=True)
        self.visualization_thread.start()
    
    def stop_visualization(self):
        """Остановка визуализации"""
        self.visualization_active = False
        self.play_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Готов к работе | AstraConv v0.0.6")
        
        # Очистка подсветки клавиш
        if hasattr(self, 'viz_canvas'):
            self.viz_canvas.delete("highlight")
    
    def _visualization_worker(self):
        """Рабочий поток для визуализации"""
        try:
            import mido
            midi_file = mido.MidiFile(self.midi_path)
            
            # Воспроизведение с визуализацией
            start_time = time.time()
            current_time = 0
            
            for msg in midi_file:
                if not self.visualization_active:
                    break
                
                if hasattr(msg, 'time'):
                    current_time += msg.time
                
                # Ожидание до следующего события
                elapsed = time.time() - start_time
                wait_time = current_time - elapsed
                if wait_time > 0:
                    time.sleep(wait_time)
                
                # Визуализация ноты
                if hasattr(msg, 'type') and msg.type == 'note_on' and hasattr(msg, 'velocity') and msg.velocity > 0:
                    self._highlight_key(msg.note)
        
        except Exception as e:
            print(f"Ошибка визуализации: {e}")
        finally:
            self.root.after(0, self.stop_visualization)
    
    def _highlight_key(self, midi_note):
        """Подсветка клавиши на визуализации"""
        if not hasattr(self, 'viz_canvas') or not self.visualization_active:
            return
        
        # Простая реализация - определение позиции клавиши
        key_position = (midi_note - 36) % 15  # 15 белых клавиш на октаву
        width = self.viz_canvas.winfo_width() or 1000
        white_width = width // 15
        
        x1 = key_position * white_width
        x2 = x1 + white_width
        
        # Создание подсветки
        self.viz_canvas.delete("highlight")
        highlight = self.viz_canvas.create_rectangle(x1, 10, x2, 160, 
                                                   fill="#00FF00", 
                                                   stipple="gray50",
                                                   tags="highlight")
        
        # Автоматическое удаление через 200мс
        self.root.after(200, lambda: self.viz_canvas.delete(highlight))
    
    def init_stars(self):
        """Инициализация мерцающих звезд для фона"""
        if not self.settings.get('background_enabled', True) or not self.settings.get('animations', True):
            return
        
        # Создаем canvas для фона
        self.canvas = tk.Canvas(self.root, bg="#1e1e1e", highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.lower("all")
        
        # Создаем звезды
        self.stars = []
        for _ in range(70):
            x = random.randint(50, self.root.winfo_width() - 50)
            y = random.randint(50, self.root.winfo_height() - 50)
            size = random.uniform(0.5, 1.5)
            brightness = random.uniform(0.4, 1.0)
            star = self.canvas.create_oval(
                x - size, y - size, x + size, y + size,
                fill=self._get_star_color(brightness),
                outline=""
            )
            self.stars.append({
                'id': star,
                'x': x,
                'y': y,
                'size': size,
                'brightness': brightness,
                'phase': random.uniform(0, 2 * math.pi),
                'speed': random.uniform(0.02, 0.05)
            })
        
        # Запускаем анимацию
        self.animate_stars()
    
    def _get_star_color(self, brightness):
        """Получает цвет звезды в зависимости от яркости"""
        if brightness > 0.8:
            return "#FFFFFF"  # Белый для самых ярких
        elif brightness > 0.6:
            return "#FFD700"  # Золотой для средних
        else:
            return "#DAA520"  # Темно-золотой для тусклых
    
    def animate_stars(self):
        """Анимация мерцающих звезд"""
        if not self.settings.get('animations', True) or not hasattr(self, 'canvas'):
            return
        
        for star in self.stars:
            star['phase'] += star['speed']
            # Плавное изменение яркости
            brightness = 0.4 + 0.6 * abs(math.sin(star['phase']))
            star['brightness'] = brightness
            
            # Обновляем цвет звезды
            try:
                self.canvas.itemconfig(
                    star['id'],
                    fill=self._get_star_color(brightness)
                )
            except tk.TclError:
                # Игнорируем ошибку если элемент уже удален
                pass
        
        # Планируем следующий кадр
        if hasattr(self, 'root') and self.root:
            self.root.after(40, self.animate_stars)

def check_dependencies():
    """Проверка необходимых зависимостей"""
    required = ['mido', 'pygame']
    missing = []
    
    for module in required:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    
    return missing

def show_dependency_error():
    """Показать ошибку о зависимостях"""
    root = tk.Tk()
    root.withdraw()
    error_msg = "⚠️ Отсутствуют необходимые зависимости для работы AstraConv:\n\n"
    error_msg += "Установите их командами:\n"
    error_msg += "pip install mido pygame\n\n"
    error_msg += "Для работы с SoundFont (воспроизведение MIDI):\n"
    error_msg += "pip install midi2audio\n\n"
    error_msg += "Для полноценной работы скачайте SoundFont файл FluidR3_GM.sf2\n"
    error_msg += "и поместите его в папку C:\\SoundFonts\\\n\n"
    error_msg += "Программа продолжит работу в ограниченном режиме."
    messagebox.showwarning("Зависимости не установлены", error_msg)
    root.destroy()

def main():
    """Основная функция запуска приложения"""
    # Проверка базовых зависимостей
    missing_deps = check_dependencies()
    
    if missing_deps:
        show_dependency_error()
    
    # Создание основного окна
    root = tk.Tk()
    
    # Запрещаем изменение размера окна
    root.resizable(True, True)
    
    # Запуск приложения
    app = AstrConvApp(root)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

if __name__ == "__main__":
    main()
