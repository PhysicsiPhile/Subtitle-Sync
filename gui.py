#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compact GUI wrapper for SRT-Sync original logic + minimal gap fill."""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    DND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

from SrtSync import SrtSync


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


class QueueWriter:
    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)
        return len(text)

    def flush(self):
        pass


class DropBox(ttk.Frame):
    """Compact rectangular click/drop target."""

    def __init__(self, master, title, hint, filetypes, save=False, height=64):
        super().__init__(master)
        self.filetypes = filetypes
        self.save = save
        self.var = tk.StringVar()
        self.default_hint = hint

        self.box = tk.Frame(
            self,
            height=height,
            bg="#f7f7f7",
            highlightthickness=1,
            highlightbackground="#b8b8b8",
            highlightcolor="#777777",
            cursor="hand2",
        )
        self.box.pack(fill="x", expand=True)
        self.box.pack_propagate(False)

        self.title_label = tk.Label(
            self.box,
            text=title,
            bg="#f7f7f7",
            fg="#222222",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.title_label.pack(fill="x", padx=10, pady=(7, 0))

        self.path_label = tk.Label(
            self.box,
            text=hint,
            bg="#f7f7f7",
            fg="#666666",
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        )
        self.path_label.pack(fill="x", padx=10, pady=(2, 0))

        for w in (self, self.box, self.title_label, self.path_label):
            w.bind("<Button-1>", self.browse)
            w.bind("<Enter>", self.on_enter)
            w.bind("<Leave>", self.on_leave)

        if DND_AVAILABLE:
            for widget in (self.box, self.title_label, self.path_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self.on_drop)

    def on_enter(self, _event=None):
        self.box.configure(bg="#eeeeee", highlightbackground="#777777")
        self.title_label.configure(bg="#eeeeee")
        self.path_label.configure(bg="#eeeeee")

    def on_leave(self, _event=None):
        self.box.configure(bg="#f7f7f7", highlightbackground="#b8b8b8")
        self.title_label.configure(bg="#f7f7f7")
        self.path_label.configure(bg="#f7f7f7")

    def _shorten(self, path):
        if not path:
            return self.default_hint
        p = Path(path)
        parent = str(p.parent)
        name = p.name
        if len(path) <= 66:
            return path
        return "..." + os.sep + name if len(name) < 60 else "..." + name[-60:]

    def set(self, value):
        value = value.strip()
        self.var.set(value)
        self.path_label.configure(text=self._shorten(value), fg="#333333" if value else "#666666")

    def get(self):
        return self.var.get().strip()

    def browse(self, _event=None):
        if self.save:
            path = filedialog.asksaveasfilename(
                title="Choose output subtitle path",
                defaultextension=".srt",
                filetypes=self.filetypes,
            )
        else:
            path = filedialog.askopenfilename(
                title="Choose file",
                filetypes=self.filetypes,
            )
        if path:
            self.set(path)

    def on_drop(self, event):
        raw = event.data.strip()
        # tkinterdnd2 wraps paths with spaces in braces.
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        # If several files were dropped, keep the first one.
        if "} {" in raw:
            raw = raw.split("} {", 1)[0].lstrip("{")
        self.set(raw)


BaseTk = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk


class App(BaseTk):
    def __init__(self):
        super().__init__()

        self.title("SRT-Sync")
        self.geometry("660x420")
        self.minsize(620, 380)

        try:
            self.iconbitmap(resource_path("srtsync_logo.ico"))
        except Exception:
            pass
        try:
            self._icon_img = tk.PhotoImage(file=resource_path("srtsync_logo.png"))
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass

        self.log_queue = queue.Queue()
        self.last_output = None
        self.running = False
        self._last_progress_ui_update = 0.0

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(
            header,
            text="SRT-Sync",
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")

        drag_note = "Drag files into boxes" if DND_AVAILABLE else "Click boxes to browse"
        ttk.Label(header, text=drag_note, foreground="#666666").pack(side="right")

        self.timing_box = DropBox(
            outer,
            "1. Correct timing SRT",
            "Drop/click: subtitle with correct timestamps",
            [("SubRip subtitles", "*.srt"), ("All files", "*.*")],
        )
        self.timing_box.pack(fill="x", pady=(10, 6))

        self.text_box = DropBox(
            outer,
            "2. Better text SRT/TXT",
            "Drop/click: subtitle or transcript with better words",
            [("Text/subtitles", "*.srt *.txt"), ("All files", "*.*")],
        )
        self.text_box.pack(fill="x", pady=6)

        self.output_box = DropBox(
            outer,
            "3. Output synced SRT",
            "Auto-filled; click to change output path",
            [("SubRip subtitles", "*.srt"), ("All files", "*.*")],
            save=True,
        )
        self.output_box.pack(fill="x", pady=6)

        opts = ttk.Frame(outer)
        opts.pack(fill="x", pady=(4, 5))

        self.progress_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="status", variable=self.progress_var).pack(side="left")

        self.trace_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="trace", variable=self.trace_var).pack(side="left", padx=(10, 0))

        ttk.Label(opts, text="gap ms").pack(side="left", padx=(14, 3))
        self.min_gap_var = tk.StringVar(value="700")
        ttk.Entry(opts, textvariable=self.min_gap_var, width=6).pack(side="left")

        ttk.Label(opts, text="fallback ms/word").pack(side="left", padx=(10, 3))
        self.ms_per_token_var = tk.StringVar(value="280")
        ttk.Entry(opts, textvariable=self.ms_per_token_var, width=5).pack(side="left")

        ttk.Label(opts, text="min words").pack(side="left", padx=(10, 3))
        self.min_words_var = tk.StringVar(value="3")
        ttk.Entry(opts, textvariable=self.min_words_var, width=4).pack(side="left")

        ttk.Label(opts, text="wrap").pack(side="left", padx=(10, 3))
        self.wrap_chars_var = tk.StringVar(value="42")
        ttk.Entry(opts, textvariable=self.wrap_chars_var, width=4).pack(side="left")

        self.format_var = tk.StringVar(value="auto")
        ttk.Label(opts, text="input 2").pack(side="left", padx=(14, 3))
        ttk.Combobox(opts, textvariable=self.format_var, values=["auto", "srt", "txt"], width=6, state="readonly").pack(side="left")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(2, 5))

        self.start_button = ttk.Button(actions, text="Sync", command=self.start_sync)
        self.start_button.pack(side="left")

        ttk.Button(actions, text="Open folder", command=self.open_output_folder).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Clear", command=self.clear_log).pack(side="left", padx=(6, 0))

        self.status = tk.StringVar(value="Ready")
        ttk.Label(actions, textvariable=self.status, foreground="#555555").pack(side="right")

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(0, 5))
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.percent_var = tk.StringVar(value="0.00% | processed 0 | left ?")
        ttk.Label(progress_row, textvariable=self.percent_var, width=38, anchor="e").pack(side="left", padx=(6, 0))

        self.log = tk.Text(outer, height=5, wrap="word", state="disabled", font=("Consolas", 8))
        self.log.pack(fill="both", expand=True)

        self.after(100, self.drain_log_queue)

    def default_output_path(self):
        text = self.text_box.get()
        if not text:
            return ""
        p = Path(text)
        return str(p.with_suffix(".synced.srt"))

    def start_sync(self):
        timing = self.timing_box.get()
        text = self.text_box.get()
        output = self.output_box.get() or self.default_output_path()
        self.output_box.set(output)

        if not timing or not text:
            messagebox.showerror("Missing files", "Choose both input files.")
            return

        try:
            min_gap = int(self.min_gap_var.get().strip())
            ms_per_token = int(self.ms_per_token_var.get().strip())
            min_words = int(self.min_words_var.get().strip())
            wrap_chars = int(self.wrap_chars_var.get().strip())
        except ValueError:
            messagebox.showerror("Bad value", "Gap ms, fallback ms/word, and min words must be integers.")
            return

        self.clear_log()
        self.status.set("Running...")
        self.running = True
        self.start_button.configure(state="disabled")
        self.progress["value"] = 0
        self.percent_var.set("0.00% | processed 0 | left ?")
        self._last_progress_ui_update = 0.0

        def run():
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = QueueWriter(self.log_queue)
            sys.stderr = QueueWriter(self.log_queue)
            try:
                print("Starting SRT sync using original DP + local-rate gap fit...\n")
                print(f"Timing: {timing}")
                print(f"Text:   {text}")
                print(f"Output: {output}\n")

                def gui_progress(percent, message="", done=None, total=None):
                    self.log_queue.put(("PROGRESS", percent, message, done, total))

                out = SrtSync().sync(
                    timing,
                    text,
                    show_progress=self.progress_var.get(),
                    trace=self.trace_var.get(),
                    target_format=self.format_var.get(),
                    output_path=output,
                    print_output=False,
                    gap_fill=True,
                    min_gap_ms=min_gap,
                    ms_per_token=ms_per_token,
                    min_target_missing_words=min_words,
                    local_rate_window=6,
                    wrap_chars=wrap_chars,
                    progress_callback=gui_progress,
                )
                self.last_output = out
                print("\nDone.")
                self.log_queue.put("__STATUS_DONE__")
            except Exception:
                print("\nERROR:")
                print(traceback.format_exc())
                self.log_queue.put("__STATUS_ERROR__")
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        threading.Thread(target=run, daemon=True).start()

    def drain_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if isinstance(msg, tuple) and msg and msg[0] == "PROGRESS":
                    if len(msg) >= 5:
                        _, percent, message, done, total = msg
                    else:
                        _, percent, message = msg
                        done, total = None, None

                    now = time.time()
                    percent = max(0.0, min(100.0, float(percent)))

                    # Do not update the tkinter widgets thousands of times.
                    # Update at about 10 FPS, or always on major stage changes.
                    force = percent in (0.0, 1.0, 2.0, 8.0, 97.0, 98.0, 99.0, 100.0)
                    if not force and now - self._last_progress_ui_update < 0.10:
                        continue
                    self._last_progress_ui_update = now

                    self.progress["value"] = percent
                    if done is not None and total is not None:
                        done = int(done)
                        total = int(total)
                        left = max(0, total - done)
                        self.percent_var.set(f"{percent:6.2f}% | processed {done:,} | left {left:,}")
                    else:
                        self.percent_var.set(f"{percent:6.2f}% | processed - | left -")
                    if message:
                        self.status.set(message)
                    continue
                if msg == "__STATUS_DONE__":
                    self.finish_run("Done")
                    continue
                if msg == "__STATUS_ERROR__":
                    self.finish_run("Error")
                    continue
                self.log.configure(state="normal")
                self.log.insert("end", msg)
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self.drain_log_queue)

    def finish_run(self, status):
        if status == "Done":
            self.progress["value"] = 100
            current = self.percent_var.get()
            if "processed" in current and "left" in current:
                # Preserve the final processed/left counts, only force exact percent.
                parts = current.split("|", 1)
                self.percent_var.set("100.00% |" + parts[1] if len(parts) > 1 else "100.00%")
            else:
                self.percent_var.set("100.00%")
        self.running = False
        self.status.set(status)
        self.start_button.configure(state="normal")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def open_output_folder(self):
        path = self.output_box.get() or self.last_output or self.default_output_path()
        if not path:
            messagebox.showinfo("No output", "No output path yet.")
            return
        folder = Path(path).expanduser().resolve().parent
        if not folder.exists():
            messagebox.showerror("Folder not found", str(folder))
            return
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(folder)])


if __name__ == "__main__":
    App().mainloop()
