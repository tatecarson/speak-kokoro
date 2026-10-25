"""A desktop reader for Windows and Linux. Speech runs outside the UI thread."""
from pathlib import Path
import queue
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

import kokoro_runtime as runtime
from kokoro_controller import ReaderController

PAPER = "#f4f3ed"
INK = "#243c32"
MUTED = "#617168"
GREEN = "#245c45"
LINE = "#d6ddd3"

VOICE_GROUPS = {
    "American English": "af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa",
    "British English": "bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis",
    "Spanish": "ef_dora em_alex em_santa",
    "French": "ff_siwis",
    "Hindi": "hf_alpha hf_beta hm_omega hm_psi",
    "Italian": "if_sara im_nicola",
    "Portuguese": "pf_dora pm_alex pm_santa",
}
VOICES = {f"{voice[3:].title()} / {language}": voice
          for language, voices in VOICE_GROUPS.items() for voice in voices.split()}


class ReaderWindow:
    def __init__(self, root, controller=None):
        self.root = root
        self.controller = controller if controller is not None else ReaderController()
        self.active = False
        self.loading = False
        self.paused = False
        self.failed = False
        self.session_id = None
        self.ignore_through = 0
        self.playback_text = ""
        self.spans = []
        self.closed = False
        root.title("Speak Kokoro")
        root.geometry("960x720")
        root.minsize(760, 540)
        root.configure(background=PAPER)
        icon = (runtime.BUNDLE / 'desktop/speak-kokoro.png' if runtime.BUNDLE else
                Path(__file__).resolve().parents[1] / 'packaging/speak-kokoro.png')
        if icon.is_file():
            self.icon = tk.PhotoImage(file=str(icon))
            root.iconphoto(True, self.icon)
        root.protocol("WM_DELETE_WINDOW", self.close)
        families = set(font.families(root))
        ui_font = "Segoe UI" if "Segoe UI" in families else "DejaVu Sans"
        reading_font = next((name for name in ("Georgia", "DejaVu Serif", "Liberation Serif")
                             if name in families), "TkTextFont")
        self.ui_font = ui_font
        root.option_add("*Font", (ui_font, 10))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=PAPER)
        style.configure("TLabel", background=PAPER, foreground=INK)
        style.configure("TButton", padding=(13, 9), background="#ffffff", foreground=INK,
                        bordercolor=LINE, focuscolor=GREEN)
        style.map("TButton", background=[("active", "#e6ece2")],
                  foreground=[("disabled", "#8b958e")])
        style.configure("Read.TButton", background=GREEN, foreground="white", bordercolor=GREEN,
                        font=(ui_font, 11, "bold"), padding=(23, 11))
        style.map("Read.TButton", background=[("active", "#184432"), ("disabled", "#a4b9ac")],
                  foreground=[("disabled", "#ffffff")])
        style.configure("TCombobox", padding=8, fieldbackground="white", foreground=INK)
        style.map("TCombobox", fieldbackground=[("readonly", "white")],
                  selectbackground=[("readonly", "white")], selectforeground=[("readonly", INK)])
        style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor="#e1e6dc",
                        borderwidth=0, thickness=4)

        outer = ttk.Frame(root, padding=(28, 24, 28, 20))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 24))
        mark = tk.Canvas(header, width=43, height=43, bg=GREEN, highlightthickness=0)
        mark.pack(side="left", padx=(0, 14))
        for x, height in ((10, 10), (17, 22), (24, 30), (31, 16)):
            mark.create_line(x, 22-height/2, x, 22+height/2, fill="#e7efd9", width=3,
                             capstyle="round")
        title = ttk.Frame(header)
        title.pack(side="left")
        ttk.Label(title, text="Speak Kokoro", font=(ui_font, 22, "bold")).pack(anchor="w")
        ttk.Label(title, text="Text to speech, on your computer.", foreground=MUTED).pack(anchor="w", pady=(3, 0))
        tk.Label(header, text="WORKS OFFLINE" if runtime.BUNDLE else "LOCAL SPEECH", bg="#e3eadb",
                 fg=GREEN, padx=12, pady=8, font=(ui_font, 9, "bold")).pack(side="right")

        tools = ttk.Frame(outer)
        tools.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.paste_button = ttk.Button(tools, text="Paste text", command=self.paste)
        self.paste_button.pack(side="left")
        ttk.Button(tools, text="Open text file…", command=self.open_file).pack(side="left", padx=8)
        ttk.Button(tools, text="Clear", command=self.clear).pack(side="left")
        self.count = tk.StringVar(value="0 words")
        ttk.Label(tools, textvariable=self.count, foreground=MUTED).pack(side="right")

        page = tk.Frame(outer, bg="white", highlightthickness=1, highlightbackground=LINE)
        page.grid(row=2, column=0, sticky="nsew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        self.text = tk.Text(page, wrap="word", undo=True, font=(reading_font, 17),
                            background="white", foreground=INK, insertbackground=GREEN,
                            selectbackground="#dce9cc", selectforeground=INK, borderwidth=0,
                            padx=24, pady=22, spacing1=2, spacing3=7, height=8,
                            highlightthickness=0)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(page, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)
        self.placeholder = tk.Label(self.text, text="Paste or type text here.", foreground="#8a948c",
                                    background="white", font=(reading_font, 17))
        self.placeholder.place(x=21, y=20)
        self.placeholder.bind("<Button-1>", lambda _: self.text.focus_set())
        self.text.tag_configure("sentence", background="#edf2e6")
        self.text.tag_configure("word", background="#d4e6ae", foreground=INK)
        self.text.tag_raise("word")
        self.text.bind("<<Modified>>", self._edited)
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=1)
        self.progress.grid(row=3, column=0, sticky="ew", pady=(0, 20))

        settings = ttk.Frame(outer)
        settings.grid(row=4, column=0, sticky="ew", pady=(0, 22))
        settings.columnconfigure(0, weight=1)
        ttk.Label(settings, text="VOICE", foreground=MUTED, font=(ui_font, 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(settings, text="SPEED", foreground=MUTED, font=(ui_font, 9, "bold")).grid(row=0, column=1, sticky="w", padx=(18, 0), pady=(0, 6))
        cfg = runtime.read_config()
        self.voice = tk.StringVar(value=next((label for label, value in VOICES.items()
                                              if value == cfg["VOICE"]), "Heart / American English"))
        try:
            speed = float(cfg["SPEED"])
            if not 0.5 <= speed <= 2:
                raise ValueError()
        except ValueError:
            speed = 1.0
        self.speed = tk.StringVar(value=f"{speed:g}×")
        self.voice_box = ttk.Combobox(settings, textvariable=self.voice, values=list(VOICES), state="readonly")
        self.voice_box.grid(row=1, column=0, sticky="ew")
        self.speed_box = ttk.Combobox(settings, textvariable=self.speed, width=9, state="readonly",
                                      values=[f"{value:g}×" for value in sorted({i/10 for i in range(5, 21)} | {speed})])
        self.speed_box.grid(row=1, column=1, sticky="e", padx=(18, 0))
        for box in (self.voice_box, self.speed_box):
            box.bind("<<ComboboxSelected>>", self.save_preferences)

        controls = ttk.Frame(outer)
        controls.grid(row=5, column=0, sticky="ew")
        self.read_button = ttk.Button(controls, text="Read aloud", style="Read.TButton", command=self.read)
        self.read_button.pack(side="left", padx=(0, 10))
        self.pause_button = ttk.Button(controls, text="Pause", command=lambda: self.control("TOGGLE"))
        self.pause_button.pack(side="left", padx=(0, 6))
        self.previous_button = ttk.Button(controls, text="Previous", command=lambda: self.control("PREV"))
        self.previous_button.pack(side="left", padx=(0, 6))
        self.next_button = ttk.Button(controls, text="Next", command=lambda: self.control("NEXT"))
        self.next_button.pack(side="left", padx=(0, 6))
        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop)
        self.stop_button.pack(side="left")
        footer = ttk.Frame(outer)
        footer.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Ready when you are.")
        self.status_label = ttk.Label(footer, textvariable=self.status, foreground=MUTED, wraplength=650)
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(footer, text="Ctrl+Enter to read · Esc to stop", foreground=MUTED,
                  font=(ui_font, 9)).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.help_button = ttk.Button(footer, text="Help", command=self.help)
        self.help_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))
        footer.bind("<Configure>", lambda event: self.status_label.configure(
            wraplength=max(200, event.width - self.help_button.winfo_reqwidth() - 16)))
        root.bind("<Control-Return>", lambda _: self.read())
        root.bind("<Escape>", lambda _: self.stop())
        root.bind("<Control-o>", lambda _: self.open_file())
        self._buttons()
        self.poll_id = root.after(80, self.poll)
        self.text.focus_set()

    def content(self):
        return self.text.get("1.0", "end-1c")

    def _edited(self, _=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        content = self.content()
        self.count.set(f"{len(content.split()):,} words")
        if content:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=21, y=20)
        if content != self.playback_text:
            self.text.tag_remove("word", "1.0", "end")
            self.text.tag_remove("sentence", "1.0", "end")
        self._buttons()

    def _buttons(self):
        self.read_button.configure(state="normal" if self.content().strip() and not self.loading else "disabled")
        for button in (self.pause_button, self.previous_button, self.next_button):
            button.configure(state="normal" if self.active else "disabled")
        self.stop_button.configure(state="normal" if self.active or self.loading else "disabled")
        for box in (self.voice_box, self.speed_box):
            box.configure(state="disabled" if self.loading else "readonly")
        self.pause_button.configure(text="Resume" if self.paused else "Pause")

    def paste(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.status.set("Copy some text first, then choose Paste text.")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.focus_set()

    def open_file(self):
        filename = filedialog.askopenfilename(parent=self.root, title="Open text to read",
                                               filetypes=[("Text files", "*.txt *.md"), ("All files", "*")])
        if not filename:
            return
        try:
            with Path(filename).open("rb") as file:
                data = file.read(runtime.MAX_REQUEST)
            if len(data) >= runtime.MAX_REQUEST:
                raise ValueError("This file is too large. Open a section smaller than 4 MB.")
            text = data.decode("utf-8-sig")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", text)
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("Couldn't open this file", f"Open a plain UTF-8 text file.\n\n{exc}", parent=self.root)

    def clear(self):
        self.stop()
        self.text.delete("1.0", "end")
        self.status.set("Ready when you are.")

    def preferences(self):
        return VOICES[self.voice.get()], float(self.speed.get().rstrip("×"))

    def save_preferences(self, _=None):
        try:
            voice, speed = self.preferences()
            runtime.save_settings(voice, speed)
            if self.active:
                self.controller.configure(voice, speed)
        except (OSError, ValueError) as exc:
            self.error(f"Couldn't save voice settings: {exc}")

    def read(self):
        if self.loading:
            return
        try:
            voice, speed = self.preferences()
            runtime.save_settings(voice, speed)
            self.controller.read(self.content(), voice, speed)
        except (OSError, ValueError) as exc:
            self.error(str(exc))
            return
        self.failed = False
        self.loading = True
        self.ignore_through = self.session_id or self.ignore_through
        self.session_id = None
        self.active = False
        self.paused = False
        self.progress.configure(mode="indeterminate")
        self.progress.start(18)
        self.status_label.configure(foreground=MUTED)
        self.status.set("Getting the voice ready… This may take a moment.")
        self._buttons()

    def control(self, command):
        if self.active:
            self.controller.control(command)

    def stop(self):
        self.controller.control("STOP")
        self.loading = self.active = self.paused = False
        self.ignore_through = self.session_id or self.ignore_through
        self.session_id = None
        self.failed = False
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.status.set("Stopped. You can edit the text or read again.")
        self.text.tag_remove("word", "1.0", "end")
        self.text.tag_remove("sentence", "1.0", "end")
        self._buttons()

    def error(self, message):
        self.failed = True
        self.loading = self.active = False
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.status_label.configure(foreground="#9a382e")
        self.status.set(f"Couldn't read aloud. {message[:220]}\nCheck your audio output. Help includes the diagnostic log.")
        self._buttons()

    def _index(self, offset):
        # Tcl 8.6 counts non-BMP characters differently from Python. Ask Tcl
        # for the column length so highlighting also works after emoji.
        prefix = self.playback_text[:offset]
        return f"{prefix.count(chr(10)) + 1}.{self.root.tk.call('string', 'length', prefix.rsplit(chr(10), 1)[-1])}"

    def highlight(self, tag, start, end):
        if self.content() == self.playback_text and 0 <= start <= end <= len(self.playback_text):
            self.text.tag_remove(tag, "1.0", "end")
            self.text.tag_add(tag, self._index(start), self._index(end))
            self.text.see(self._index(start))

    def handle_event(self, event):
        kind = event.get("ev")
        if kind == "client_error":
            self.error(event.get("message", "Please try again."))
        elif kind == "disconnected":
            self.session_id = None
            self.ignore_through = 0
            if self.active:
                self.error("The reader disconnected. Press Read aloud to restart it.")
        elif kind == "start":
            if event["id"] <= self.ignore_through or event["id"] < (self.session_id or 0):
                return
            self.session_id = event["id"]
            self.playback_text = event["text"]
            self.spans = event.get("spans", [])
            self.active = True
            self.loading = self.paused = self.failed = False
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.status_label.configure(foreground=MUTED)
            self.status.set("Preparing the first sentence…")
        elif event.get("id") == self.session_id and self.session_id is not None:
            if kind == "sentence":
                index = event.get("i", 0)
                if 0 <= index < len(self.spans):
                    self.highlight("sentence", *self.spans[index])
                    self.progress.configure(value=index/max(1, len(self.spans)))
                    self.status.set(f"Reading sentence {index + 1} of {len(self.spans)}")
            elif kind == "word":
                self.highlight("word", event["s"], event["e"])
            elif kind == "state":
                self.paused = event.get("paused", False)
                self.status.set("Paused. Resume when you're ready." if self.paused else "Reading aloud…")
            elif kind == "error":
                self.error(event.get("message", "Please try again."))
            elif kind == "end":
                was_active = self.active
                self.loading = self.active = self.paused = False
                self.progress.stop()
                self.progress.configure(mode="determinate", value=1 if was_active and not self.failed else 0)
                self.text.tag_remove("word", "1.0", "end")
                self.text.tag_remove("sentence", "1.0", "end")
                if not self.failed and was_active:
                    self.status.set("Finished reading. Listen again whenever you like.")
        self._buttons()

    def poll(self):
        # Bound each pass so large event bursts never starve typing or Stop.
        for _ in range(100):
            try:
                self.handle_event(self.controller.events.get_nowait())
            except queue.Empty:
                break
        if not self.closed:
            self.poll_id = self.root.after(80, self.poll)

    def help(self):
        window = tk.Toplevel(self.root)
        window.title("Speak Kokoro help")
        window.geometry("700x430")
        text = tk.Text(window, wrap="word", padx=20, pady=20, font=(self.ui_font, 11))
        text.pack(fill="both", expand=True)
        try:
            with runtime.LOG.open("rb") as log:
                log.seek(0, 2)
                log.seek(max(0, log.tell()-16000))
                diagnostic = log.read().decode("utf-8", errors="replace")
        except OSError:
            diagnostic = "No diagnostic log yet."
        text.insert("1.0", "Paste or open plain text, choose a voice, then select Read aloud.\n\n"
                    "Ctrl+Enter reads the text. Esc stops it. Ctrl+O opens a text file.\n"
                    "Voice and speed changes apply to the current sentence.\n"
                    "Closing the window stops playback and unloads the speech model.\n\n"
                    "No sound? Check your speakers, volume, and default output device.\n"
                    "If you change audio devices, close and reopen Speak Kokoro.\n\n"
                    f"Settings: {runtime.CONF}\nDiagnostic log: {runtime.LOG}\n\n{diagnostic}")
        text.configure(state="disabled")

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.controller.close()
        self.root.destroy()


def self_test():
    """Exercise real Tk controls without audio hardware or changing user settings."""
    class FakeReader:
        def __init__(self):
            self.events = queue.Queue()
            self.calls = []
        def read(self, *args): self.calls.append(("read", *args))
        def control(self, command): self.calls.append((command,))
        def configure(self, *args): self.calls.append(("configure", *args))
        def close(self): self.calls.append(("close",))
    previous = runtime.CONF
    with tempfile.TemporaryDirectory(prefix="kokoro-ui-") as temporary:
        runtime.CONF = Path(temporary) / "settings.conf"
        root = tk.Tk()
        reader = FakeReader()
        window = ReaderWindow(root, reader)
        try:
            root.update()
            root.geometry("760x540")
            root.update()
            for button in (window.read_button, window.pause_button, window.previous_button,
                           window.next_button, window.stop_button, window.help_button):
                assert button.winfo_ismapped(), "A control disappeared at the minimum window size"
                right = button.winfo_rootx() + button.winfo_width()
                assert right <= root.winfo_rootx() + root.winfo_width()
            assert window.read_button.instate(["disabled"])
            root.clipboard_get = lambda: "Hello 😀. Read this sentence."
            window.paste_button.invoke()
            root.update()
            window.read_button.invoke()
            assert reader.calls[-1] == ("read", "Hello 😀. Read this sentence.", "af_heart", 1.0)
            assert runtime.CONF.is_file()
            window.handle_event({"ev": "start", "id": 7, "text": window.content(), "spans": [[0, 8], [9, 28]]})
            window.handle_event({"ev": "word", "id": 7, "s": 9, "e": 13})
            assert window.text.get(*window.text.tag_ranges("word")) == "Read"
            window.pause_button.invoke()
            assert reader.calls[-1] == ("TOGGLE",)
            window.handle_event({"ev": "state", "id": 7, "paused": True})
            assert window.pause_button.cget("text") == "Resume"
            window.next_button.invoke()
            window.previous_button.invoke()
            assert reader.calls[-2:] == [("NEXT",), ("PREV",)]
            window.speed.set("1.2×")
            window.save_preferences()
            assert reader.calls[-1] == ("configure", "af_heart", 1.2)
            window.handle_event({"ev": "error", "id": 7, "message": "No audio output"})
            window.handle_event({"ev": "end", "id": 7})
            assert "No audio output" in window.status.get()
            window.read_button.invoke()
            window.handle_event({"ev": "end", "id": 7})
            assert window.loading, "An old playback event cancelled a new reading"
            window.stop_button.invoke()
            assert reader.calls[-1] == ("STOP",)
            assert not window.loading
            window.handle_event({"ev": "start", "id": 7, "text": window.content(), "spans": []})
            assert not window.active, "A stale event restarted a stopped reading"
            root.update()
        finally:
            window.close()
            runtime.CONF = previous
    print("Desktop controls, Unicode highlighting, settings, error state, and close passed.")
    return 0


def main():
    root = tk.Tk()
    ReaderWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
