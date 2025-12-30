import mido
import tkinter as tk
from tkinter import filedialog, scrolledtext
import sys
import math
import random

# ===============================
# Раскладка клавиш (фиксированные диапазоны)
# ===============================
white_keys = '1234567890qwertyuiopasdfghjklzxcvbnm'  # 36 символов = 5 октав + 1 нота
black_keys = '!@$%^*&(QWETYIOPSDGHJLZCVB'           # 26 символов = 5 октав + 1 нота

WHITE_NOTE_PITCHES = [0, 2, 4, 5, 7, 9, 11]  # C D E F G A B
BLACK_NOTE_PITCHES = [1, 3, 6, 8, 10]        # C# D# F# G# A#

def note_to_char(note):
    """Конвертирует MIDI-ноту в символ клавиши с проверкой границ"""
    octave = (note - 36) // 12  # Базовая нота: C2 = MIDI 36 -> октава 0
    pitch_class = note % 12
    
    if pitch_class in WHITE_NOTE_PITCHES:
        pos_in_octave = WHITE_NOTE_PITCHES.index(pitch_class)
        idx = pos_in_octave + octave * 7  # 7 белых клавиш на октаву
        if 0 <= idx < len(white_keys):
            return white_keys[idx]
    
    elif pitch_class in BLACK_NOTE_PITCHES:
        pos_in_octave = BLACK_NOTE_PITCHES.index(pitch_class)
        idx = pos_in_octave + octave * 5  # 5 чёрных клавиш на октаву
        if 0 <= idx < len(black_keys):
            return black_keys[idx]
    
    return ''  # Игнорировать ноты вне диапазона

# ===============================
# GUI приложение
# ===============================
class MidiConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MIDI to QWERTY Converter")
        self.root.geometry("800x600")
        self.root.configure(bg="#000000")
        self.root.resizable(False, False)
        
        # Создаем Canvas для анимированного фона
        self.canvas = tk.Canvas(root, bg="#000000", highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        
        # Инициализируем анимацию фона
        self.particles = []
        self.init_background()
        self.animate_background()
        
        # Основной контент поверх анимации
        content_frame = tk.Frame(root, bg="#000000")
        content_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        # Заголовок
        title = tk.Label(
            content_frame,
            text="MIDI ➜ QWERTY",
            font=("Consolas", 28, "bold"),
            fg="#FFD700",
            bg="#000000",
            pady=10
        )
        title.pack(pady=(0, 20))
        
        # Кнопки действий
        btn_frame = tk.Frame(content_frame, bg="#000000")
        btn_frame.pack(pady=10)
        
        self.select_btn = tk.Button(
            btn_frame,
            text="📂 Выбрать MIDI",
            font=("Consolas", 14),
            bg="#D4AF37",  # Золотой
            fg="#000000",
            activebackground="#B8860B",
            relief="flat",
            padx=25,
            pady=8,
            command=self.load_midi
        )
        self.select_btn.pack(side=tk.LEFT, padx=10)
        
        self.copy_btn = tk.Button(
            btn_frame,
            text="📋 Копировать",
            font=("Consolas", 14),
            bg="#D4AF37",
            fg="#000000",
            activebackground="#B8860B",
            relief="flat",
            padx=25,
            pady=8,
            command=self.copy_result,
            state="disabled"
        )
        self.copy_btn.pack(side=tk.LEFT, padx=10)
        
        # Статус BPM
        self.bpm_label = tk.Label(
            content_frame,
            text="BPM: --",
            font=("Consolas", 16),
            fg="#FFD700",
            bg="#000000",
            pady=5
        )
        self.bpm_label.pack(pady=(15, 5))
        
        # Поле результата
        self.result_frame = tk.Frame(content_frame, bg="#FFD700")
        self.result_frame.pack(padx=30, pady=20)
        
        self.result_text = scrolledtext.ScrolledText(
            self.result_frame,
            font=("Consolas", 14),
            bg="#1a1a1a",
            fg="#FFD700",
            insertbackground="#FFD700",
            wrap=tk.WORD,
            height=10,
            width=60,
            padx=15,
            pady=15,
            state="disabled",
            relief="flat"
        )
        self.result_text.pack()
        
        # Состояние кнопки копирования
        self.result_text.bind("<KeyRelease>", lambda e: self.update_copy_state())
    
    def init_background(self):
        """Инициализация частиц для анимации фона"""
        for _ in range(30):
            x = random.uniform(0, 800)
            y = random.uniform(0, 600)
            size = random.uniform(1.0, 3.0)
            speed = random.uniform(0.2, 0.8)
            angle = random.uniform(0, 2 * math.pi)
            dx = math.cos(angle) * speed
            dy = math.sin(angle) * speed
            # Едва заметные золотые частицы
            particle = self.canvas.create_oval(
                x - size, y - size, x + size, y + size,
                fill="#3D3319",  # Тёмно-золотой
                outline="#5C4D26",
                width=0.5
            )
            self.particles.append({
                'id': particle,
                'x': x,
                'y': y,
                'dx': dx,
                'dy': dy,
                'size': size
            })
    
    def animate_background(self):
        """Плавная анимация фона с частицами"""
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        
        for p in self.particles:
            # Обновляем позицию
            p['x'] += p['dx']
            p['y'] += p['dy']
            
            # Отскок от краев
            if p['x'] <= 0 or p['x'] >= width:
                p['dx'] *= -1
            if p['y'] <= 0 or p['y'] >= height:
                p['dy'] *= -1
            
            # Плавное затухание и появление
            alpha = (math.sin(p['x'] * 0.01) + 1) / 2 * 0.3 + 0.1
            fill_color = self._hex_with_alpha("#D4AF37", alpha)
            
            # Обновляем частицу
            self.canvas.coords(
                p['id'],
                p['x'] - p['size'], p['y'] - p['size'],
                p['x'] + p['size'], p['y'] + p['size']
            )
            self.canvas.itemconfig(p['id'], fill=fill_color)
        
        # Рекурсивный вызов с оптимальной частотой
        self.root.after(40, self.animate_background)
    
    def _hex_with_alpha(self, hex_color, alpha):
        """Добавляет альфа-канал к HEX цвету для имитации прозрачности"""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        return f'#{int(r*alpha):02x}{int(g*alpha):02x}{int(b*alpha):02x}'
    
    def load_midi(self):
        """Загружает и обрабатывает MIDI-файл"""
        midi_path = filedialog.askopenfilename(
            title="Выберите MIDI-файл",
            filetypes=[("MIDI files", "*.mid *.midi")]
        )
        
        if not midi_path:
            return
        
        try:
            mid = mido.MidiFile(midi_path)
        except Exception as e:
            self.show_result(f"Ошибка загрузки файла:\n{str(e)}")
            self.copy_btn.config(state="normal")
            return
        
        # Определяем BPM
        tempo = 500000  # default 120 BPM
        for track in mid.tracks:
            for msg in track:
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
                    break
            if tempo != 500000:
                break
        
        bpm = 60_000_000 / tempo
        self.bpm_label.config(text=f"BPM: {bpm:.2f}")
        
        # Собираем события note_on
        events = []
        for track in mid.tracks:
            abs_time = 0
            for msg in track:
                abs_time += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    sec_time = mido.tick2second(abs_time, mid.ticks_per_beat, tempo)
                    char = note_to_char(msg.note)
                    if char:  # Игнорируем ноты вне диапазона
                        events.append((sec_time, char))
        
        events.sort(key=lambda x: x[0])
        
        # Группируем аккорды (интервал ≤50 мс)
        output = []
        current_chord = []
        last_time = None
        
        for t, note in events:
            if last_time is None or (t - last_time) <= 0.05:
                current_chord.append(note)
            else:
                self._append_to_output(output, current_chord)
                current_chord = [note]
            last_time = t
        
        if current_chord:
            self._append_to_output(output, current_chord)
        
        result = ''.join(output)
        self.show_result(result)
        self.copy_btn.config(state="normal" if result else "disabled")
    
    def _append_to_output(self, output, chord):
        """Добавляет ноту или аккорд в результат"""
        if len(chord) > 1:
            output.append(f"[{''.join(chord)}]")
        else:
            output.append(chord[0])
    
    def show_result(self, text):
        """Отображает результат в текстовом поле"""
        self.result_text.config(state="normal")
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, text)
        self.result_text.config(state="disabled")
        self.result_text.see(tk.END)  # Автопрокрутка вниз
    
    def copy_result(self):
        """Копирует результат в буфер обмена"""
        result = self.result_text.get(1.0, tk.END).strip()
        if result:
            self.root.clipboard_clear()
            self.root.clipboard_append(result)
            self.copy_btn.config(text="✓ Скопировано!", state="disabled")
            self.root.after(1500, lambda: self.copy_btn.config(text="📋 Копировать", state="normal"))
    
    def update_copy_state(self):
        """Обновляет состояние кнопки копирования"""
        text = self.result_text.get(1.0, tk.END).strip()
        self.copy_btn.config(state="normal" if text else "disabled")

# ===============================
# Запуск приложения
# ===============================
if __name__ == "__main__":
    root = tk.Tk()
    app = MidiConverterApp(root)
    root.mainloop()
