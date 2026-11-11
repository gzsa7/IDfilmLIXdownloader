import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import subprocess
import os
import re
import time
import webbrowser
from io import BytesIO


from PIL import Image, ImageTk
import requests
from bs4 import BeautifulSoup

from src.idlixHelper import (
    IdlixHelper, logger, check_domain_status, load_config, save_config, poster_cache_manager
)

# ============================================================
# RETRY logic (same as CLI)
# ============================================================
RETRY_LIMIT = 3


def retry(func, *args, **kwargs):
    for _ in range(RETRY_LIMIT):
        result = func(*args, **kwargs)
        if result and result.get("status"):
            return result
        time.sleep(1)
    return {"status": False, "message": "Maximum retry reached"}


# ============================================================
# DESIGN TOKENS (Dark Neutral Cinematic Palette)
# ============================================================
class Colors:
    BG_PRIMARY          = "#0B0B0C"
    BG_SURFACE          = "#141416"
    BG_ELEVATED         = "#1B1B1F"
    BG_CARD             = "#18181B"
    BG_CARD_HOVER       = "#222225"
    BG_INPUT            = "#242428"
    BORDER              = "#27272A"
    BORDER_FOCUS        = "#3F3F46"
    TEXT_PRIMARY        = "#F2F2F2"
    TEXT_SECONDARY      = "#A1A1AA"
    TEXT_MUTED          = "#71717A"
    ACCENT              = "#3B82F6"
    ACCENT_HOVER        = "#2563EB"
    BTN_SECONDARY       = "#27272A"
    BTN_SECONDARY_HOVER = "#3F3F46"
    LOG_SUCCESS         = "#4ADE80"
    LOG_WARNING         = "#FACC15"
    LOG_ERROR           = "#F87171"
    LOG_INFO            = "#A1A1AA"


class Fonts:
    TITLE       = ("Segoe UI", 16, "bold")
    SECTION     = ("Segoe UI", 11)
    CARD_TITLE  = ("Segoe UI", 10)
    CARD_META   = ("Segoe UI", 9)
    BUTTON      = ("Segoe UI", 10)
    LOG         = ("Consolas", 9)
    SEARCH      = ("Segoe UI", 11)
    STATUS      = ("Segoe UI", 9)
    STATUS_BOLD = ("Segoe UI", 9, "bold")
    MODAL_TITLE = ("Segoe UI", 14, "bold")


# ============================================================
# CANVAS ICON DRAWING HELPERS  (16 x 16)
# ============================================================
def draw_search_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_oval(3, 3, 11, 11, outline=color, width=1.5)
    canvas.create_line(10, 10, 14, 14, fill=color, width=1.5)


def draw_refresh_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_arc(2, 2, 14, 14, start=30, extent=300,
                      style="arc", outline=color, width=1.5)
    canvas.create_polygon(13, 6, 13, 2, 10, 5, fill=color, outline=color)


def draw_play_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_polygon(5, 3, 13, 8, 5, 13, fill=color, outline=color)


def draw_stop_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_rectangle(4, 4, 12, 12, fill=color, outline=color)


def draw_pause_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_rectangle(4, 3, 7, 13, fill=color, outline=color)
    canvas.create_rectangle(9, 3, 12, 13, fill=color, outline=color)


def draw_resume_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_polygon(5, 3, 13, 8, 5, 13, fill=color, outline=color)


def draw_cancel_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_line(4, 4, 12, 12, fill=color, width=2)
    canvas.create_line(12, 4, 4, 12, fill=color, width=2)



def draw_subtitle_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    # Text bubble / CC icon
    canvas.create_rectangle(2, 4, 14, 13, outline=color, width=1.5)
    canvas.create_text(8, 8.5, text="CC", fill=color, font=("Consolas", 6, "bold"))


def draw_download_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_line(8, 2, 8, 10, fill=color, width=1.5)
    canvas.create_polygon(5, 9, 8, 13, 11, 9, fill=color, outline=color)
    canvas.create_line(3, 14, 13, 14, fill=color, width=1.5)


def draw_folder_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_line(2, 5, 2, 13, fill=color, width=1.5)
    canvas.create_line(2, 13, 14, 13, fill=color, width=1.5)
    canvas.create_line(14, 13, 14, 6, fill=color, width=1.5)
    canvas.create_line(14, 6, 8, 6, fill=color, width=1.5)
    canvas.create_line(8, 6, 7, 4, fill=color, width=1.5)
    canvas.create_line(7, 4, 2, 4, fill=color, width=1.5)


def draw_settings_icon(canvas, color=Colors.TEXT_PRIMARY):
    canvas.delete("all")
    canvas.create_oval(5, 5, 11, 11, outline=color, width=1.5)
    canvas.create_line(8, 2, 8, 4, fill=color, width=1.5)
    canvas.create_line(8, 12, 8, 14, fill=color, width=1.5)
    canvas.create_line(2, 8, 4, 8, fill=color, width=1.5)
    canvas.create_line(12, 8, 14, 8, fill=color, width=1.5)
    canvas.create_line(4, 4, 5.5, 5.5, fill=color, width=1.5)
    canvas.create_line(10.5, 10.5, 12, 12, fill=color, width=1.5)
    canvas.create_line(12, 4, 10.5, 5.5, fill=color, width=1.5)
    canvas.create_line(5.5, 10.5, 4, 12, fill=color, width=1.5)


# ============================================================
# ICON BUTTON WIDGET
# ============================================================
class IconButton(tk.Frame):
    """Minimal styled button with optional Canvas icon and text label."""

    def __init__(self, parent, icon_draw_fn=None, text="", command=None,
                 bg=Colors.BTN_SECONDARY, hover_bg=Colors.BTN_SECONDARY_HOVER,
                 fg=Colors.TEXT_PRIMARY, icon_color=None):
        super().__init__(parent, bg=bg, cursor="hand2")

        self._bg = bg
        self._hover_bg = hover_bg
        self._command = command

        _icon_color = icon_color or fg
        _pad = 8

        if icon_draw_fn:
            self.icon_canvas = tk.Canvas(
                self, width=16, height=16, bg=bg,
                highlightthickness=0, cursor="hand2"
            )
            self.icon_canvas.pack(side="left", padx=(_pad, 3), pady=5)
            icon_draw_fn(self.icon_canvas, _icon_color)
            self.icon_canvas.bind("<Button-1>", self._on_click)
            self.icon_canvas.bind("<Enter>", self._on_enter)
            self.icon_canvas.bind("<Leave>", self._on_leave)
        else:
            self.icon_canvas = None

        if text:
            self.label = tk.Label(
                self, text=text, font=Fonts.BUTTON, bg=bg, fg=fg,
                cursor="hand2"
            )
            self.label.pack(
                side="left",
                padx=(0 if icon_draw_fn else _pad, _pad),
                pady=5
            )
            self.label.bind("<Button-1>", self._on_click)
            self.label.bind("<Enter>", self._on_enter)
            self.label.bind("<Leave>", self._on_leave)
        else:
            self.label = None

        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_click(self, event=None):
        if self._command:
            self._command()

    def _on_enter(self, event=None):
        self.configure(bg=self._hover_bg)
        if self.icon_canvas:
            self.icon_canvas.configure(bg=self._hover_bg)
        if self.label:
            self.label.configure(bg=self._hover_bg)

    def _on_leave(self, event=None):
        self.configure(bg=self._bg)
        if self.icon_canvas:
            self.icon_canvas.configure(bg=self._bg)
        if self.label:
            self.label.configure(bg=self._bg)

    def set_icon_and_text(self, icon_draw_fn=None, text=""):
        if self.icon_canvas and icon_draw_fn:
            icon_draw_fn(self.icon_canvas, self.label.cget("fg") if self.label else Colors.TEXT_PRIMARY)
        if self.label and text:
            self.label.configure(text=text)


# ============================================================
# COLLAPSIBLE LOG PANEL
# ============================================================
class CollapsibleLogPanel(tk.Frame):
    """Bottom panel with toggle header and expandable log area."""

    def __init__(self, parent):
        super().__init__(parent, bg=Colors.BG_ELEVATED)
        self.expanded = False

        # ── Header bar ──
        self.header = tk.Frame(self, bg=Colors.BG_ELEVATED, cursor="hand2")
        self.header.pack(fill="x")

        self.toggle_label = tk.Label(
            self.header, text="\u25B8 Activity & Logs",
            font=Fonts.SECTION, bg=Colors.BG_ELEVATED,
            fg=Colors.TEXT_SECONDARY, cursor="hand2"
        )
        self.toggle_label.pack(side="left", padx=16, pady=8)

        self.clear_btn = IconButton(
            self.header, text="Clear", command=None,
            bg=Colors.BG_ELEVATED, hover_bg=Colors.BTN_SECONDARY
        )
        self.clear_btn.pack(side="right", padx=12, pady=4)

        # ── Separator ──
        tk.Frame(self, bg=Colors.BORDER, height=1).pack(fill="x")

        # ── Content (log text) — NOT packed initially ──
        self.content = tk.Frame(self, bg=Colors.BG_PRIMARY)

        self.log_box = tk.Text(
            self.content, height=10, state="disabled",
            bg=Colors.BG_PRIMARY, fg=Colors.LOG_INFO,
            font=Fonts.LOG, relief="flat", borderwidth=0,
            padx=12, pady=8, wrap="word",
            insertbackground=Colors.TEXT_PRIMARY,
            selectbackground=Colors.BTN_SECONDARY
        )
        log_sb = tk.Scrollbar(self.content, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

        # Color tags
        self.log_box.tag_configure("SUCCESS", foreground=Colors.LOG_SUCCESS)
        self.log_box.tag_configure("ERROR",   foreground=Colors.LOG_ERROR)
        self.log_box.tag_configure("WARNING", foreground=Colors.LOG_WARNING)
        self.log_box.tag_configure("INFO",    foreground=Colors.LOG_INFO)

        # Bind toggle
        self.header.bind("<Button-1>", lambda e: self.toggle())
        self.toggle_label.bind("<Button-1>", lambda e: self.toggle())

    def toggle(self):
        if self.expanded:
            self.content.pack_forget()
            self.toggle_label.configure(text="\u25B8 Activity & Logs")
        else:
            self.content.pack(fill="both", expand=True)
            self.toggle_label.configure(text="\u25BE Activity & Logs")
        self.expanded = not self.expanded

    def set_clear_command(self, cmd):
        self.clear_btn._command = cmd


# ============================================================
# GUI LOGGER  (bounded lines limit MAX_LOG_LINES = 500)
# ============================================================
class GuiLogger:
    def __init__(self, textbox):
        self.textbox = textbox

    def write(self, msg):
        self.textbox.configure(state="normal")

        tag = None
        if "| SUCCESS |" in msg:
            tag = "SUCCESS"
        elif "| ERROR |" in msg:
            tag = "ERROR"
        elif "| WARNING |" in msg:
            tag = "WARNING"
        elif "| INFO |" in msg:
            tag = "INFO"

        if tag:
            self.textbox.insert(tk.END, msg, tag)
        else:
            self.textbox.insert(tk.END, msg)

        # Enforce MAX_LOG_LINES = 500 to prevent unbounded memory growth
        try:
            line_count = int(self.textbox.index('end-1c').split('.')[0])
            if line_count > 500:
                self.textbox.delete('1.0', f'{line_count - 500}.0')
        except Exception:
            pass

        self.textbox.see(tk.END)
        self.textbox.configure(state="disabled")

    def flush(self):
        pass


# ============================================================
# MAIN GUI
# ============================================================
class IdlixGUI:
    CARD_WIDTH  = 175          # approximate slot width for column calculation
    POSTER_SIZE = (150, 225)   # 2 : 3 movie poster ratio

    def __init__(self, root):
        self.root = root
        self.root.title("IDLIX Player")
        self.root.geometry("1200x750")
        self.root.minsize(700, 500)
        self.root.configure(bg=Colors.BG_PRIMARY)

        self.idlix = IdlixHelper()
        self.featured_movies = []
        self.poster_images = []
        self.card_widgets = []          # for responsive reflow
        self.ffplay_process = None
        self.ytdlp_process = None
        self._current_columns = 0
        self._resize_timer = None

        self._build_ui()

        # Logger injection
        logger.remove()
        logger.add(
            GuiLogger(self.log_panel.log_box),
            format="{time:HH:mm:ss} | {level} | {message}"
        )

        # Fast non-blocking startup: Background domain health check -> load data
        self._show_grid_status("Checking domain configuration...")
        threading.Thread(target=self._startup_health_check_task, daemon=True).start()

    def _startup_health_check_task(self):
        curr_url = self.idlix.BASE_WEB_URL
        logger.info(f"Checking domain status: {curr_url}")
        res = check_domain_status(curr_url)
        if res.get("status"):
            logger.success(f"Domain verified: {curr_url}")
            self.refresh_featured()
        else:
            err_msg = f"Domain check failed: {res.get('message')}"
            logger.warning(err_msg)
            def trigger_recovery():
                self._show_grid_status(f"Domain error: {res.get('message')}")
                self.open_domain_config_dialog(initial_error=err_msg)
            self.root.after(0, trigger_recovery)

    # ────────────────────────────────────────────
    # UI CONSTRUCTION
    # ────────────────────────────────────────────
    def _build_ui(self):
        # === TOP — header bar ===
        self._build_header()
        tk.Frame(self.root, bg=Colors.BORDER, height=1).pack(
            fill="x", side="top"
        )

        # === BOTTOM — collapsible log (always at very bottom) ===
        self.log_panel = CollapsibleLogPanel(self.root)
        self.log_panel.pack(fill="x", side="bottom")
        self.log_panel.set_clear_command(self.clear_log)

        # === BOTTOM — status bar (hidden until play / download) ===
        self._build_status_bar()          # creates widgets; does NOT pack

        # === MIDDLE — movie grid (fills remaining space) ===
        self._build_grid_area()

    # ── Header ──────────────────────────────────
    def _build_header(self):
        header = tk.Frame(self.root, bg=Colors.BG_ELEVATED, height=52)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # App title
        title_frame = tk.Frame(header, bg=Colors.BG_ELEVATED)
        title_frame.pack(side="left", padx=(20, 20), pady=10)

        tk.Label(
            title_frame, text="IDLIX Player", font=Fonts.TITLE,
            bg=Colors.BG_ELEVATED, fg=Colors.TEXT_PRIMARY
        ).pack(side="left")

        # Search bar
        search_outer = tk.Frame(header, bg=Colors.BG_INPUT)
        search_outer.pack(side="left", fill="x", expand=True,
                          padx=(0, 16), pady=10)

        s_icon = tk.Canvas(
            search_outer, width=16, height=16,
            bg=Colors.BG_INPUT, highlightthickness=0
        )
        s_icon.pack(side="left", padx=(10, 4), pady=6)
        draw_search_icon(s_icon, Colors.TEXT_MUTED)

        self.search_entry = tk.Entry(
            search_outer, font=Fonts.SEARCH,
            bg=Colors.BG_INPUT, fg=Colors.TEXT_MUTED,
            insertbackground=Colors.TEXT_PRIMARY,
            relief="flat", borderwidth=0
        )
        self.search_entry.pack(side="left", fill="x", expand=True,
                               padx=(0, 10), pady=6)
        self.search_entry.insert(0, "Search movies & series...")
        self.search_entry.bind("<FocusIn>",  self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.bind("<Return>",   lambda e: self.perform_search())

        # Action buttons (right side)
        btn_frame = tk.Frame(header, bg=Colors.BG_ELEVATED)
        btn_frame.pack(side="right", padx=(0, 16))

        for icon_fn, label, cmd in [
            (draw_settings_icon, "Domain",   self.open_domain_config_dialog),
            (draw_refresh_icon,  "Refresh",  self.refresh_featured),
            (draw_play_icon,     "Play URL", self.play_by_url),
            (draw_download_icon, "DL URL",   self.download_by_url),
            (draw_folder_icon,   "Folder",   self.open_download_folder),
        ]:
            IconButton(
                btn_frame, icon_fn, label, cmd,
                bg=Colors.BG_ELEVATED, hover_bg=Colors.BTN_SECONDARY
            ).pack(side="left", padx=2)

    # ── Grid area ───────────────────────────────
    def _build_grid_area(self):
        grid_container = tk.Frame(self.root, bg=Colors.BG_PRIMARY)
        grid_container.pack(fill="both", expand=True)

        self.poster_canvas = tk.Canvas(
            grid_container, bg=Colors.BG_PRIMARY, highlightthickness=0
        )
        self.v_scrollbar = tk.Scrollbar(
            grid_container, orient="vertical",
            command=self.poster_canvas.yview
        )
        self.poster_canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.v_scrollbar.pack(side="right", fill="y")
        self.poster_canvas.pack(side="left", fill="both", expand=True)

        self.poster_frame = tk.Frame(self.poster_canvas, bg=Colors.BG_PRIMARY)
        self._canvas_window = self.poster_canvas.create_window(
            (0, 0), window=self.poster_frame, anchor="nw"
        )

        # Centered status label (loading / empty / error)
        self.grid_status_label = tk.Label(
            self.poster_canvas, text="", font=Fonts.SECTION,
            bg=Colors.BG_PRIMARY, fg=Colors.TEXT_SECONDARY
        )

        # Responsive resize with debounced reflow (150ms)
        self.poster_canvas.bind("<Configure>", self._on_canvas_configure)

        # Mousewheel scrolling
        self.poster_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.poster_canvas.bind("<Button-4>",   self._on_mousewheel)
        self.poster_canvas.bind("<Button-5>",   self._on_mousewheel)

    # ── Status bar (Now Playing / Download) ─────
    def _build_status_bar(self):
        self._status_sep = tk.Frame(self.root, bg=Colors.BORDER, height=1)
        self._status_bar = tk.Frame(
            self.root, bg=Colors.BG_ELEVATED, height=36
        )
        self._status_bar.pack_propagate(False)

        # Accent dot
        dot = tk.Canvas(
            self._status_bar, width=8, height=8,
            bg=Colors.BG_ELEVATED, highlightthickness=0
        )
        dot.create_oval(1, 1, 7, 7, fill=Colors.ACCENT, outline=Colors.ACCENT)
        dot.pack(side="left", padx=(16, 6), pady=14)

        self._status_text = tk.Label(
            self._status_bar, text="", font=Fonts.STATUS,
            bg=Colors.BG_ELEVATED, fg=Colors.TEXT_PRIMARY
        )
        self._status_text.pack(side="left", padx=(0, 12))

        self._status_stop_btn = IconButton(
            self._status_bar, draw_stop_icon, "Stop", self.stop_player,
            bg=Colors.BG_ELEVATED, hover_bg=Colors.BTN_SECONDARY
        )
        # NOT packed — shown only during playback

        self._status_pause_btn = IconButton(
            self._status_bar, draw_pause_icon, "Pause", self.toggle_pause_download,
            bg=Colors.BG_ELEVATED, hover_bg=Colors.BTN_SECONDARY
        )
        self._status_cancel_btn = IconButton(
            self._status_bar, draw_cancel_icon, "Cancel", self.cancel_download_action,
            bg=Colors.BG_ELEVATED, hover_bg=Colors.BTN_SECONDARY
        )
        # NOT packed — shown only during download

        self._current_progress_callback = None

    # ────────────────────────────────────────────
    # SEARCH PLACEHOLDER
    # ────────────────────────────────────────────
    def _on_search_focus_in(self, event):
        if self.search_entry.get() == "Search movies...":
            self.search_entry.delete(0, tk.END)
            self.search_entry.configure(fg=Colors.TEXT_PRIMARY)

    def _on_search_focus_out(self, event):
        if not self.search_entry.get().strip():
            self.search_entry.insert(0, "Search movies...")
            self.search_entry.configure(fg=Colors.TEXT_MUTED)

    # ────────────────────────────────────────────
    # GRID STATUS (centered loading / empty / error)
    # ────────────────────────────────────────────
    def _show_grid_status(self, text):
        self.grid_status_label.configure(text=text)
        self.grid_status_label.place(relx=0.5, rely=0.35, anchor="center")

    def _hide_grid_status(self):
        self.grid_status_label.place_forget()

    def _clear_grid_and_show_status(self, text):
        """Clear poster grid and display a centered status message."""
        for w in self.poster_frame.winfo_children():
            w.destroy()
        self.poster_images.clear()
        self.card_widgets.clear()
        self._current_columns = 0
        self._show_grid_status(text)

    # ────────────────────────────────────────────
    # STATUS BAR  (Now Playing / Download progress)
    # ────────────────────────────────────────────
    def _show_status_bar(self, text, show_stop=False, show_dl_controls=False, is_paused=False):
        self._status_text.configure(text=text)
        if show_stop:
            self._status_stop_btn.pack(side="right", padx=12, pady=4)
        else:
            self._status_stop_btn.pack_forget()

        if show_dl_controls:
            if is_paused:
                self._status_pause_btn.set_icon_and_text(draw_resume_icon, "Resume")
            else:
                self._status_pause_btn.set_icon_and_text(draw_pause_icon, "Pause")
            self._status_cancel_btn.pack(side="right", padx=6, pady=4)
            self._status_pause_btn.pack(side="right", padx=6, pady=4)
        else:
            self._status_pause_btn.pack_forget()
            self._status_cancel_btn.pack_forget()

        if not self._status_bar.winfo_ismapped():
            self._status_sep.pack(fill="x", side="bottom")
            self._status_bar.pack(fill="x", side="bottom")

    def toggle_pause_download(self):
        if self.idlix.download_paused:
            logger.info("Resuming download requested from UI.")
            self.root.after(
                0, lambda: self._show_status_bar("Resuming download...", show_dl_controls=True, is_paused=False)
            )
            threading.Thread(
                target=lambda: self.idlix.resume_download(progress_callback=self._current_progress_callback),
                daemon=True
            ).start()
        else:
            logger.info("Pausing download requested from UI.")
            self.idlix.pause_download()
            self.root.after(
                0, lambda: self._show_status_bar("Paused", show_dl_controls=True, is_paused=True)
            )

    def cancel_download_action(self):
        logger.info("Cancelling download requested from UI.")
        self.root.after(
            0, lambda: self._show_status_bar("Cancelling...", show_dl_controls=False)
        )
        threading.Thread(
            target=self.idlix.cancel_download,
            daemon=True
        ).start()

    def _hide_status_bar(self):
        if self._status_bar.winfo_ismapped():
            self._status_bar.pack_forget()
            self._status_sep.pack_forget()

    # ────────────────────────────────────────────
    # MOUSE WHEEL SCROLL  (vertical)
    # ────────────────────────────────────────────
    def _on_mousewheel(self, event):
        if event.delta:
            self.poster_canvas.yview_scroll(
                int(-1 * (event.delta / 120)), "units"
            )
        elif event.num == 4:
            self.poster_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.poster_canvas.yview_scroll(1, "units")

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>",   self._on_mousewheel)
        widget.bind("<Button-5>",   self._on_mousewheel)
        for child in widget.winfo_children():
            self.bind_mousewheel(child)

    # ────────────────────────────────────────────
    # RESPONSIVE GRID
    # ────────────────────────────────────────────
    def _calculate_columns(self, canvas_width=None):
        if canvas_width is None:
            canvas_width = self.poster_canvas.winfo_width()
        if canvas_width <= 1:
            return 5                     # default before first render
        usable = canvas_width - 32       # 16 px padding each side
        return max(2, usable // self.CARD_WIDTH)

    def _on_canvas_configure(self, event):
        canvas_width = event.width
        self.poster_canvas.itemconfig(self._canvas_window, width=canvas_width)

        if self._resize_timer is not None:
            self.root.after_cancel(self._resize_timer)

        self._resize_timer = self.root.after(
            150, lambda: self._check_and_reflow_grid(canvas_width)
        )

    def _check_and_reflow_grid(self, canvas_width):
        self._resize_timer = None
        new_cols = self._calculate_columns(canvas_width)
        if new_cols != self._current_columns and self.card_widgets:
            self._current_columns = new_cols
            self._reflow_grid()
        else:
            bbox = self.poster_canvas.bbox("all")
            if bbox:
                self.poster_canvas.configure(scrollregion=bbox)

    def _reflow_grid(self):
        cols = self._current_columns
        for idx, card in enumerate(self.card_widgets):
            card.grid_forget()
            card.grid(
                row=idx // cols, column=idx % cols,
                padx=8, pady=8, sticky="n"
            )
        self.poster_frame.update_idletasks()
        bbox = self.poster_canvas.bbox("all")
        if bbox:
            self.poster_canvas.configure(scrollregion=bbox)

    # ────────────────────────────────────────────
    # DOMAIN CONFIGURATION & RECOVERY DIALOG
    # ────────────────────────────────────────────
    def open_domain_config_dialog(self, initial_error=None):
        popup = tk.Toplevel(self.root)
        popup.title("Domain Configuration & Recovery")
        popup.configure(bg=Colors.BG_SURFACE)
        popup.geometry("500x520")
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()

        popup.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 520) // 2
        popup.geometry(f"+{max(0, px)}+{max(0, py)}")

        content = tk.Frame(popup, bg=Colors.BG_SURFACE)
        content.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(
            content, text="Domain Configuration", font=Fonts.MODAL_TITLE,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY
        ).pack(pady=(0, 4))

        tk.Label(
            content, text="Kelola domain utama IDLIX atau atasi kendala koneksi server.",
            font=Fonts.CARD_META, bg=Colors.BG_SURFACE, fg=Colors.TEXT_SECONDARY
        ).pack(pady=(0, 16))

        curr_domain = self.idlix.BASE_WEB_URL
        curr_frame = tk.Frame(content, bg=Colors.BG_ELEVATED, padx=12, pady=10)
        curr_frame.pack(fill="x", pady=(0, 16))

        tk.Label(
            curr_frame, text="Active Domain:", font=Fonts.STATUS_BOLD,
            bg=Colors.BG_ELEVATED, fg=Colors.TEXT_MUTED
        ).pack(anchor="w")

        domain_lbl = tk.Label(
            curr_frame, text=curr_domain, font=Fonts.BUTTON,
            bg=Colors.BG_ELEVATED, fg=Colors.ACCENT
        )
        domain_lbl.pack(anchor="w", pady=(2, 0))

        tk.Label(
            content, text="Enter Base Domain:", font=Fonts.BUTTON,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", pady=(0, 4))

        entry_outer = tk.Frame(content, bg=Colors.BG_INPUT, padx=8, pady=4)
        entry_outer.pack(fill="x", pady=(0, 12))

        domain_entry = tk.Entry(
            entry_outer, font=Fonts.SEARCH,
            bg=Colors.BG_INPUT, fg=Colors.TEXT_PRIMARY,
            insertbackground=Colors.TEXT_PRIMARY,
            relief="flat", borderwidth=0
        )
        domain_entry.pack(fill="x", padx=4, pady=4)
        domain_entry.insert(0, curr_domain)

        status_lbl = tk.Label(
            content, text=initial_error or "Status: Ready for validation", font=Fonts.STATUS,
            bg=Colors.BG_SURFACE, fg=Colors.LOG_WARNING if initial_error else Colors.TEXT_SECONDARY,
            wraplength=440, justify="left"
        )
        status_lbl.pack(fill="x", pady=(0, 16))

        validated_url = [None]

        def set_status(msg, is_success=None):
            fg_col = Colors.LOG_SUCCESS if is_success is True else (Colors.LOG_ERROR if is_success is False else Colors.TEXT_SECONDARY)
            status_lbl.configure(text=msg, fg=fg_col)

        def test_domain(url_to_test):
            set_status("Menguji koneksi & validasi API domain...", None)
            popup.update_idletasks()

            def bg_check():
                res = check_domain_status(url_to_test)
                def on_done():
                    if res.get("status"):
                        validated_url[0] = res.get("base_url")
                        set_status(f"✓ {res.get('message')}", True)
                    else:
                        validated_url[0] = None
                        set_status(f"✗ [{res.get('code')}] {res.get('message')}", False)
                self.root.after(0, on_done)

            threading.Thread(target=bg_check, daemon=True).start()

        btn_row1 = tk.Frame(content, bg=Colors.BG_SURFACE)
        btn_row1.pack(fill="x", pady=(0, 8))

        IconButton(
            btn_row1, draw_refresh_icon, "Retry Current Domain",
            lambda: test_domain(self.idlix.BASE_WEB_URL),
            bg=Colors.BTN_SECONDARY, hover_bg=Colors.BTN_SECONDARY_HOVER
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        IconButton(
            btn_row1, draw_search_icon, "Test Connection",
            lambda: test_domain(domain_entry.get().strip()),
            bg=Colors.BTN_SECONDARY, hover_bg=Colors.BTN_SECONDARY_HOVER
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        def save_and_continue():
            target_url = validated_url[0] or domain_entry.get().strip()
            if save_config(target_url):
                self.idlix.set_active_domain(target_url)
                logger.success(f"Domain berhasil diperbarui ke: {target_url}")
                popup.destroy()
                self.refresh_featured()
            else:
                set_status("Gagal menyimpan konfigurasi ke file config.json", False)

        IconButton(
            content, text="Save & Continue", command=save_and_continue,
            bg=Colors.ACCENT, hover_bg=Colors.ACCENT_HOVER, fg="#FFFFFF"
        ).pack(fill="x", pady=(8, 0))

    # ────────────────────────────────────────────
    # POSTER GRID  (responsive columns with PosterCacheManager)
    # ────────────────────────────────────────────
    def show_poster_grid(self):
        # Clear previous cards
        for w in self.poster_frame.winfo_children():
            w.destroy()
        self.poster_images.clear()
        self.card_widgets.clear()
        self._hide_grid_status()

        cols = self._calculate_columns()
        self._current_columns = cols
        valid_idx = 0

        for movie in self.featured_movies:
            poster_url = movie.get("poster")
            pil_img = poster_cache_manager.get_image(poster_url, self.POSTER_SIZE)
            if not pil_img:
                continue

            try:
                tk_img = ImageTk.PhotoImage(pil_img)
            except Exception:
                continue

            self.poster_images.append(tk_img)

            row = valid_idx // cols
            col = valid_idx % cols

            # ── Card frame ──
            card = tk.Frame(
                self.poster_frame, bg=Colors.BG_CARD, cursor="hand2"
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="n")

            # Poster image
            tk.Label(
                card, image=tk_img, bg=Colors.BG_CARD, cursor="hand2"
            ).pack(padx=6, pady=(6, 0))

            # Title (always shown)
            tk.Label(
                card, text=movie["title"], font=Fonts.CARD_TITLE,
                bg=Colors.BG_CARD, fg=Colors.TEXT_PRIMARY,
                wraplength=150, justify="center", cursor="hand2"
            ).pack(padx=6, pady=(6, 2))

            # Year (only if available from backend)
            year = movie.get("year", "")
            if year:
                tk.Label(
                    card, text=year, font=Fonts.CARD_META,
                    bg=Colors.BG_CARD, fg=Colors.TEXT_SECONDARY,
                    cursor="hand2"
                ).pack(padx=6, pady=(0, 6))
            else:
                tk.Frame(card, bg=Colors.BG_CARD, height=6).pack()

            # Bind hover + click
            self._bind_card_events(card, movie)

            self.card_widgets.append(card)
            valid_idx += 1

        if valid_idx == 0 and self.featured_movies:
            self._show_grid_status("Failed to load poster images.")

        self.poster_frame.update_idletasks()
        bbox = self.poster_canvas.bbox("all")
        if bbox:
            self.poster_canvas.configure(scrollregion=bbox)
        self.poster_canvas.yview_moveto(0)
        self.bind_mousewheel(self.poster_frame)

    # ────────────────────────────────────────────
    def _bind_card_events(self, card, movie):
        """Bind hover highlight and click to card + children."""

        def _set_bg(bg):
            card.configure(bg=bg)
            for child in card.winfo_children():
                try:
                    child.configure(bg=bg)
                except tk.TclError:
                    pass

        def on_enter(e):
            _set_bg(Colors.BG_CARD_HOVER)

        def on_leave(e):
            # Only reset if mouse truly left the card bounds
            try:
                mx, my = card.winfo_pointerxy()
                cx, cy = card.winfo_rootx(), card.winfo_rooty()
                cw, ch = card.winfo_width(), card.winfo_height()
                if not (cx <= mx < cx + cw and cy <= my < cy + ch):
                    _set_bg(Colors.BG_CARD)
            except tk.TclError:
                pass

        def on_click(e):
            self.on_poster_click(movie)

        for widget in [card] + list(card.winfo_children()):
            widget.bind("<Enter>",    on_enter)
            widget.bind("<Leave>",    on_leave)
            widget.bind("<Button-1>", on_click)

    # ────────────────────────────────────────────
    # SEARCH FEATURE
    # ────────────────────────────────────────────
    def perform_search(self):
        query = self.search_entry.get().strip()
        if not query or query in ["Search movies...", "Search movies & series..."]:
            messagebox.showwarning(
                "Search", "Please enter a title to search."
            )
            return

        def task():
            self.root.after(
                0, lambda: self._clear_grid_and_show_status("Searching...")
            )
            logger.info(f"Searching for '{query}'...")
            res = retry(self.idlix.search_movie, query)

            if not res.get("status"):
                logger.error(f"Search failed: {res.get('message')}")
                self.root.after(
                    0, lambda: self._show_grid_status("Search failed.")
                )
                return

            movies = res.get("featured_movie", [])
            if not movies:
                logger.warning(f"No results found matching '{query}'.")
                self.root.after(
                    0,
                    lambda: self._show_grid_status(
                        f'No results for "{query}".'
                    )
                )
                return

            self.featured_movies = movies
            self.root.after(0, self.show_poster_grid)
            logger.success(f"Search completed. Found {len(movies)} results.")

        threading.Thread(target=task, daemon=True).start()

    # ────────────────────────────────────────────
    # ACTION MODAL  (on poster click)
    # ────────────────────────────────────────────
    def on_poster_click(self, movie):
        modal = tk.Toplevel(self.root)
        modal.title(movie["title"])
        modal.configure(bg=Colors.BG_SURFACE)
        modal.geometry("360x500")
        modal.resizable(False, False)
        modal.transient(self.root)

        # Center on parent
        modal.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width()  - 360) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 500) // 2
        modal.geometry(f"+{max(0, px)}+{max(0, py)}")

        modal.grab_set()

        content = tk.Frame(modal, bg=Colors.BG_SURFACE)
        content.pack(fill="both", expand=True, padx=28, pady=24)

        # Poster image from cache manager
        try:
            pil_img = poster_cache_manager.get_image(movie["poster"], self.POSTER_SIZE)
            if pil_img:
                tk_img = ImageTk.PhotoImage(pil_img)
                modal._poster_ref = tk_img
                tk.Label(
                    content, image=tk_img, bg=Colors.BG_SURFACE
                ).pack(pady=(0, 16))
        except Exception:
            pass

        # Title
        tk.Label(
            content, text=movie["title"], font=Fonts.MODAL_TITLE,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY,
            wraplength=300, justify="center"
        ).pack(pady=(0, 4))

        # Year (only if present)
        year = movie.get("year", "")
        if year:
            tk.Label(
                content, text=year, font=Fonts.CARD_META,
                bg=Colors.BG_SURFACE, fg=Colors.TEXT_SECONDARY
            ).pack(pady=(0, 16))
        else:
            tk.Frame(content, bg=Colors.BG_SURFACE, height=12).pack()

        # ── Buttons ──
        btn_row = tk.Frame(content, bg=Colors.BG_SURFACE)
        btn_row.pack(fill="x", pady=(0, 8))

        IconButton(
            btn_row, draw_play_icon, "Play",
            lambda: [
                modal.destroy(),
                self.process_movie(movie["url"], "play")
            ],
            bg=Colors.ACCENT, hover_bg=Colors.ACCENT_HOVER,
            fg="#FFFFFF", icon_color="#FFFFFF"
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        IconButton(
            btn_row, draw_download_icon, "Download",
            lambda: [
                modal.destroy(),
                self.process_movie(movie["url"], "download")
            ],
            bg=Colors.BTN_SECONDARY, hover_bg=Colors.BTN_SECONDARY_HOVER
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Close link
        close_lbl = tk.Label(
            content, text="Close", font=Fonts.BUTTON,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_MUTED, cursor="hand2"
        )
        close_lbl.pack(pady=(8, 0))
        close_lbl.bind("<Button-1>", lambda e: modal.destroy())
        close_lbl.bind(
            "<Enter>", lambda e: close_lbl.configure(fg=Colors.TEXT_PRIMARY)
        )
        close_lbl.bind(
            "<Leave>", lambda e: close_lbl.configure(fg=Colors.TEXT_MUTED)
        )

    # ────────────────────────────────────────────
    # RESOLUTION SELECTOR MODAL
    # ────────────────────────────────────────────
    def ask_variant(self, choices):
        popup = tk.Toplevel(self.root)
        popup.title("Select Resolution")
        popup.configure(bg=Colors.BG_SURFACE)
        popup.geometry("320x400")
        popup.resizable(False, False)
        popup.transient(self.root)

        popup.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width()  - 320) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
        popup.geometry(f"+{max(0, px)}+{max(0, py)}")

        content = tk.Frame(popup, bg=Colors.BG_SURFACE)
        content.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(
            content, text="Select Resolution", font=Fonts.MODAL_TITLE,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY
        ).pack(pady=(0, 16))

        listbox = tk.Listbox(
            content, width=30, height=12,
            bg=Colors.BG_INPUT, fg=Colors.TEXT_PRIMARY,
            font=Fonts.BUTTON, relief="flat", borderwidth=0,
            selectbackground=Colors.ACCENT, selectforeground="#FFFFFF",
            highlightthickness=0, activestyle="none"
        )
        for c in choices:
            listbox.insert(tk.END, c)
        listbox.pack(fill="x", pady=(0, 16))

        result = {"res": None}

        def choose():
            sel = listbox.curselection()
            if sel:
                result["res"] = listbox.get(sel[0])
            popup.destroy()

        IconButton(
            content, text="Select", command=choose,
            bg=Colors.ACCENT, hover_bg=Colors.ACCENT_HOVER, fg="#FFFFFF"
        ).pack(fill="x")

        popup.grab_set()
        self.root.wait_window(popup)
        return result["res"]

    # ────────────────────────────────────────────
    # SUBTITLE LANGUAGE SELECTOR MODAL (FOR DOWNLOAD)
    # ────────────────────────────────────────────
    def ask_subtitle_languages(self, available_subs):
        """
        Show a modal dialog for the user to select subtitle languages to download.
        Returns a list of selected language codes, or None if skipped/cancelled.
        """
        if not available_subs:
            return None

        popup = tk.Toplevel(self.root)
        popup.title("Download Subtitle")
        popup.configure(bg=Colors.BG_SURFACE)
        popup.geometry("380x480")
        popup.resizable(False, False)
        popup.transient(self.root)

        popup.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width()  - 380) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 480) // 2
        popup.geometry(f"+{max(0, px)}+{max(0, py)}")

        content = tk.Frame(popup, bg=Colors.BG_SURFACE)
        content.pack(fill="both", expand=True, padx=24, pady=20)

        # Title with subtitle icon
        title_frame = tk.Frame(content, bg=Colors.BG_SURFACE)
        title_frame.pack(pady=(0, 4))

        icon_canvas = tk.Canvas(
            title_frame, width=20, height=20,
            bg=Colors.BG_SURFACE, highlightthickness=0
        )
        icon_canvas.pack(side="left", padx=(0, 8))
        draw_subtitle_icon(icon_canvas, Colors.ACCENT)

        tk.Label(
            title_frame, text="Download Subtitle", font=Fonts.MODAL_TITLE,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY
        ).pack(side="left")

        tk.Label(
            content, text="Pilih bahasa subtitle yang ingin didownload:",
            font=Fonts.CARD_META, bg=Colors.BG_SURFACE, fg=Colors.TEXT_SECONDARY
        ).pack(pady=(0, 12))

        # Subtitle list with checkboxes
        check_frame = tk.Frame(content, bg=Colors.BG_ELEVATED)
        check_frame.pack(fill="both", expand=True, pady=(0, 12))

        # Scrollable area for checkboxes
        sub_canvas = tk.Canvas(
            check_frame, bg=Colors.BG_ELEVATED, highlightthickness=0
        )
        sub_scrollbar = tk.Scrollbar(
            check_frame, orient="vertical", command=sub_canvas.yview
        )
        sub_canvas.configure(yscrollcommand=sub_scrollbar.set)
        sub_scrollbar.pack(side="right", fill="y")
        sub_canvas.pack(side="left", fill="both", expand=True)

        inner_frame = tk.Frame(sub_canvas, bg=Colors.BG_ELEVATED)
        sub_canvas.create_window((0, 0), window=inner_frame, anchor="nw")

        checkbox_vars = {}
        for sub in available_subs:
            lang = sub['lang']
            label = sub['label']
            var = tk.BooleanVar(value=(lang in ('id', 'en')))  # Pre-select ID and EN
            checkbox_vars[lang] = var

            cb_row = tk.Frame(inner_frame, bg=Colors.BG_ELEVATED)
            cb_row.pack(fill="x", padx=12, pady=4)

            cb = tk.Checkbutton(
                cb_row, text=f"  {label}  ({lang})",
                variable=var, font=Fonts.BUTTON,
                bg=Colors.BG_ELEVATED, fg=Colors.TEXT_PRIMARY,
                selectcolor=Colors.BG_INPUT,
                activebackground=Colors.BG_ELEVATED,
                activeforeground=Colors.TEXT_PRIMARY,
                highlightthickness=0, borderwidth=0,
                cursor="hand2"
            )
            cb.pack(side="left", anchor="w")

        inner_frame.update_idletasks()
        sub_canvas.configure(scrollregion=sub_canvas.bbox("all"))

        # Select All / Deselect All buttons
        sel_row = tk.Frame(content, bg=Colors.BG_SURFACE)
        sel_row.pack(fill="x", pady=(0, 8))

        def select_all():
            for v in checkbox_vars.values():
                v.set(True)

        def deselect_all():
            for v in checkbox_vars.values():
                v.set(False)

        IconButton(
            sel_row, text="Pilih Semua", command=select_all,
            bg=Colors.BTN_SECONDARY, hover_bg=Colors.BTN_SECONDARY_HOVER
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        IconButton(
            sel_row, text="Hapus Semua", command=deselect_all,
            bg=Colors.BTN_SECONDARY, hover_bg=Colors.BTN_SECONDARY_HOVER
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        result = {"langs": None}

        def download_selected():
            selected = [lang for lang, var in checkbox_vars.items() if var.get()]
            result["langs"] = selected if selected else None
            popup.destroy()

        def skip():
            result["langs"] = []
            popup.destroy()

        # Download button
        IconButton(
            content, draw_download_icon, "Download Subtitle",
            command=download_selected,
            bg=Colors.ACCENT, hover_bg=Colors.ACCENT_HOVER,
            fg="#FFFFFF", icon_color="#FFFFFF"
        ).pack(fill="x", pady=(4, 4))

        # Skip link
        skip_lbl = tk.Label(
            content, text="Lewati (tanpa subtitle)", font=Fonts.BUTTON,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_MUTED, cursor="hand2"
        )
        skip_lbl.pack(pady=(4, 0))
        skip_lbl.bind("<Button-1>", lambda e: skip())
        skip_lbl.bind("<Enter>", lambda e: skip_lbl.configure(fg=Colors.TEXT_PRIMARY))
        skip_lbl.bind("<Leave>", lambda e: skip_lbl.configure(fg=Colors.TEXT_MUTED))

        popup.protocol("WM_DELETE_WINDOW", skip)

        popup.grab_set()
        self.root.wait_window(popup)
        return result["langs"]

    # ────────────────────────────────────────────
    # SEASON & EPISODE SELECTOR MODAL (FOR TV SERIES)
    # ────────────────────────────────────────────
    def ask_season_and_episode(self, series_title, seasons_list, series_slug):
        popup = tk.Toplevel(self.root)
        popup.title(f"Select Episode - {series_title}")
        popup.configure(bg=Colors.BG_SURFACE)
        popup.geometry("420x460")
        popup.resizable(False, False)
        popup.transient(self.root)

        popup.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 460) // 2
        popup.geometry(f"+{max(0, px)}+{max(0, py)}")

        content = tk.Frame(popup, bg=Colors.BG_SURFACE)
        content.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(
            content, text=series_title, font=Fonts.MODAL_TITLE,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY, wraplength=370
        ).pack(pady=(0, 4))

        tk.Label(
            content, text="Pilih Season & Episode yang ingin diputar/didownload:",
            font=Fonts.CARD_META, bg=Colors.BG_SURFACE, fg=Colors.TEXT_SECONDARY
        ).pack(pady=(0, 16))

        # Season selector
        tk.Label(
            content, text="Season:", font=Fonts.BUTTON,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", pady=(0, 4))

        season_var = tk.StringVar()
        season_cb = ttk.Combobox(content, textvariable=season_var, state="readonly", font=Fonts.BUTTON)

        season_map = {}
        season_options = []
        for s in seasons_list:
            sn = s.get("seasonNumber")
            s_name = s.get("name") or f"Season {sn}"
            ep_cnt = s.get("episodeCount")
            label = f"{s_name} ({ep_cnt} Episodes)" if ep_cnt else s_name
            season_options.append(label)
            season_map[label] = sn

        season_cb['values'] = season_options
        season_cb.pack(fill="x", pady=(0, 12))

        # Episode selector
        tk.Label(
            content, text="Episode:", font=Fonts.BUTTON,
            bg=Colors.BG_SURFACE, fg=Colors.TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", pady=(0, 4))

        episode_var = tk.StringVar()
        episode_cb = ttk.Combobox(content, textvariable=episode_var, state="readonly", font=Fonts.BUTTON)
        episode_cb.pack(fill="x", pady=(0, 16))

        episodes_data = []

        def load_episodes(season_num):
            nonlocal episodes_data
            episode_cb['values'] = ["Loading episodes..."]
            episode_var.set("Loading episodes...")
            popup.update_idletasks()

            res = self.idlix.get_season_episodes(series_slug, season_num)
            if res.get("status"):
                episodes_data = res.get("episodes", [])
                ep_options = []
                for ep in episodes_data:
                    num = ep.get("episodeNumber", "?")
                    name = ep.get("name") or ep.get("title") or f"Episode {num}"
                    ep_options.append(f"E{num}: {name}")
                episode_cb['values'] = ep_options
                if ep_options:
                    episode_cb.current(0)
                else:
                    episode_var.set("Tidak ada episode")
            else:
                episode_cb['values'] = ["Gagal memuat episode"]
                episode_var.set("Gagal memuat episode")

        def on_season_change(event):
            sel_season_label = season_var.get()
            sn = season_map.get(sel_season_label)
            if sn is not None:
                threading.Thread(target=lambda: load_episodes(sn), daemon=True).start()

        season_cb.bind("<<ComboboxSelected>>", on_season_change)

        if season_options:
            season_cb.current(0)
            sn_first = season_map.get(season_options[0])
            if sn_first is not None:
                threading.Thread(target=lambda: load_episodes(sn_first), daemon=True).start()

        result = {"episode": None}

        def confirm():
            sel_ep_idx = episode_cb.current()
            if episodes_data and 0 <= sel_ep_idx < len(episodes_data):
                chosen_ep = episodes_data[sel_ep_idx]
                sn_label = season_var.get()
                sn_num = season_map.get(sn_label, 1)
                ep_num = chosen_ep.get("episodeNumber", 1)
                ep_title = chosen_ep.get("name") or chosen_ep.get("title") or f"Episode {ep_num}"
                result["episode"] = {
                    "id": chosen_ep.get("id"),
                    "season_number": sn_num,
                    "episode_number": ep_num,
                    "title": ep_title,
                    "display_name": f"{series_title} - S{sn_num:02d}E{ep_num:02d} - {ep_title}"
                }
            popup.destroy()

        def on_close():
            result["episode"] = False
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", on_close)

        IconButton(
            content, text="Lanjutkan", command=confirm,
            bg=Colors.ACCENT, hover_bg=Colors.ACCENT_HOVER, fg="#FFFFFF"
        ).pack(fill="x", pady=(8, 0))

        popup.grab_set()
        self.root.wait_window(popup)
        return result["episode"]

    # ────────────────────────────────────────────
    # REFRESH FEATURED LIST
    # ────────────────────────────────────────────
    def refresh_featured(self):
        def task():
            self.root.after(
                0,
                lambda: self._clear_grid_and_show_status("Loading movies...")
            )
            logger.info("Loading featured movies...")
            home = retry(self.idlix.get_home)

            if not home.get("status"):
                logger.error(f"Failed: {home.get('message')}")
                self.root.after(
                    0,
                    lambda: self._show_grid_status("Failed to load movies.")
                )
                return

            self.featured_movies = home["featured_movie"]

            if not self.featured_movies:
                self.root.after(
                    0,
                    lambda: self._show_grid_status("No movies available.")
                )
            else:
                self.root.after(0, self.show_poster_grid)

            logger.success("Featured loaded.")

        threading.Thread(target=task, daemon=True).start()

    # ────────────────────────────────────────────
    # URL BUTTON ACTIONS
    # ────────────────────────────────────────────
    def download_by_url(self):
        url = simpledialog.askstring("Download Movie", "Enter movie URL:")
        if url:
            self.process_movie(url.strip(), "download")

    def play_by_url(self):
        url = simpledialog.askstring("Play Movie", "Enter movie URL:")
        if url:
            self.process_movie(url.strip(), "play")

    # ────────────────────────────────────────────
    # CORE PROCESS  (backend logic preserved exactly)
    # ────────────────────────────────────────────
    def process_movie(self, url: str, mode: str):

        def task():
            idlix = self.idlix

            # Reset all per-movie state so stale URLs from a previous
            # download/play session are never accidentally re-used.
            idlix.reset_download_state()

            # 1. get video data
            video_data = retry(idlix.get_video_data, url)
            if not video_data.get("status"):
                logger.error("Error getting video data")
                return

            c_type = video_data.get("content_type", "movie")

            if c_type in ["tv_series", "tv", "series"]:
                logger.info(
                    f"TV Series detected: {video_data['video_name']} | "
                    f"Seasons: {len(video_data.get('seasons', []))}"
                )

                chosen_ep = [None]
                def ask_ep():
                    chosen_ep[0] = self.ask_season_and_episode(
                        video_data['video_name'],
                        video_data.get('seasons', []),
                        video_data.get('video_slug') or url
                    )

                self.root.after(0, ask_ep)
                while chosen_ep[0] is None:
                    time.sleep(0.1)

                selected_ep = chosen_ep[0]
                if not selected_ep or not selected_ep.get("id"):
                    logger.warning("Episode selection cancelled.")
                    return

                target_id = selected_ep["id"]
                item_type = "episode"
                video_title = selected_ep["display_name"]
                idlix.video_name = video_title
                idlix.content_type = "episode"
            else:
                logger.info(
                    f"Video ID: {video_data['video_id']} | "
                    f"Name: {video_data['video_name']}"
                )
                target_id = video_data['video_id']
                item_type = "movie"
                video_title = video_data['video_name']

            # 2. embed URL
            embed = retry(idlix.get_embed_url, target_id, item_type)
            if not embed.get("status"):
                logger.error("Error getting embed URL")
                return

            logger.success(f"Embed: {embed['embed_url']}")

            # 3. m3u8
            m3u8 = retry(idlix.get_m3u8_url)
            if not m3u8.get("status"):
                logger.error("Error getting M3U8 URL")
                return

            logger.success(f"M3U8: {m3u8['m3u8_url']}")

            # 4. variant playlist
            if m3u8.get("is_variant_playlist"):
                choices = [
                    f"{v['id']} - {v['resolution']}"
                    for v in m3u8["variant_playlist"]
                ]

                selected = None

                def ask():
                    nonlocal selected
                    selected = self.ask_variant(choices)

                self.root.after(0, ask)
                while selected is None:
                    self.root.update()

                selected_id = selected.split(" - ")[0]

                for v in m3u8["variant_playlist"]:
                    if str(v["id"]) == selected_id:
                        idlix.set_m3u8_url(v["uri"])
                        logger.success(f"Variant selected: {v['resolution']}")
                        break
            else:
                logger.warning("No variant playlist.")

            # PLAY
            if mode == "play":
                subtitle = idlix.get_subtitle()

                subtitle_file = (
                    subtitle["subtitle"] if subtitle.get("status") else None
                )

                self.start_ffplay(idlix.m3u8_url, subtitle_file)

            # DOWNLOAD
            else:
                # ── Ask user which subtitles to download BEFORE video download ──
                # (We already have subtitles_list from get_embed_url)
                available_subs = idlix.get_available_subtitles()
                selected_sub_langs = [None]

                if available_subs:
                    def ask_subs():
                        selected_sub_langs[0] = self.ask_subtitle_languages(available_subs)
                    self.root.after(0, ask_subs)
                    # Wait for modal to close
                    while selected_sub_langs[0] is None:
                        time.sleep(0.1)
                else:
                    selected_sub_langs[0] = []  # No subs available, skip

                self.root.after(
                    0, lambda: self._show_status_bar("Downloading via yt-dlp...", show_dl_controls=True, is_paused=False)
                )

                def update_progress_status(log_line):
                    if idlix.download_cancelled or idlix.download_paused:
                        return
                    if "[download]" in log_line:
                        match = re.search(r'(\d+\.\d+%|\d+%)', log_line)
                        if match:
                            percent = match.group(1)
                            self.root.after(
                                0, lambda p=percent: self._show_status_bar(f"Downloading: {p}", show_dl_controls=True, is_paused=False)
                            )

                self._current_progress_callback = update_progress_status
                result = idlix.download_with_ytdlp(progress_callback=update_progress_status)

                if idlix.download_cancelled:
                    logger.warning("Download cancelled and temporary files cleaned up.")
                    self.root.after(
                        0,
                        lambda: self._show_status_bar("Download cancelled and temporary files cleaned up.", show_dl_controls=False)
                    )
                elif result.get("status"):
                    logger.success(f"Downloaded successfully: {result['path']}")

                    # ── Download subtitles after video download succeeds ──
                    chosen_langs = selected_sub_langs[0]
                    if chosen_langs:  # User selected subtitle languages
                        self.root.after(
                            0, lambda: self._show_status_bar("Downloading subtitle...", show_dl_controls=False)
                        )
                        sub_result = idlix.download_subtitles_for_video(
                            selected_langs=chosen_langs
                        )
                        if sub_result.get("status"):
                            sub_count = len(sub_result.get('downloaded', []))
                            logger.success(f"Subtitle downloaded: {sub_result['message']}")
                            self.root.after(
                                0,
                                lambda c=sub_count: self._show_status_bar(
                                    f"Download completed + {c} subtitle berhasil disimpan.",
                                    show_dl_controls=False
                                )
                            )
                        else:
                            logger.warning(f"Subtitle download failed: {sub_result.get('message')}")
                            self.root.after(
                                0,
                                lambda: self._show_status_bar(
                                    "Download video selesai, tapi subtitle gagal.",
                                    show_dl_controls=False
                                )
                            )
                    else:
                        self.root.after(
                            0,
                            lambda: self._show_status_bar("Download completed.", show_dl_controls=False)
                        )
                else:
                    logger.error(f"Download failed: {result.get('message')}")
                    self.root.after(
                        0,
                        lambda: self._show_status_bar("Download failed.", show_dl_controls=False)
                    )

                # Clean up per-movie state so the next download starts fresh
                idlix.reset_download_state()

                # Auto-hide after 5 seconds
                self.root.after(5000, self._hide_status_bar)


        threading.Thread(target=task, daemon=True).start()

    # ────────────────────────────────────────────
    # Player controls (Instant Piping Stream)
    # ────────────────────────────────────────────
    def start_ffplay(self, m3u8_url, subtitle=None):
        self.stop_player()

        result = self.idlix.play_stream_instantly(stream_url=m3u8_url, subtitle=subtitle)
        if result.get("status"):
            self.ffplay_process = result.get("player_process")
            self.ytdlp_process = result.get("ytdlp_process")

            video_name = self.idlix.video_name or "Unknown"
            self.root.after(
                0,
                lambda: self._show_status_bar(
                    f"Now Playing: {video_name}", show_stop=True
                )
            )
            self._check_ffplay_status()
        else:
            err_msg = result.get('message') or "Failed to play stream"
            logger.error(f"Failed to play stream: {err_msg}")
            self.root.after(
                0,
                lambda: messagebox.showwarning("Player Error", err_msg)
            )
            self.root.after(0, self._hide_status_bar)

    def _check_ffplay_status(self):
        """Poll player process; hide status bar when it exits."""
        if self.ffplay_process and self.ffplay_process.poll() is not None:
            if self.ytdlp_process and self.ytdlp_process.poll() is None:
                try:
                    self.ytdlp_process.terminate()
                except Exception:
                    pass
            self.ffplay_process = None
            self.ytdlp_process = None
            # Reset per-movie state so next movie starts fresh
            self.idlix.reset_download_state()
            self._hide_status_bar()
        elif self.ffplay_process:
            self.root.after(2000, self._check_ffplay_status)

    def stop_player(self):
        if self.ffplay_process and self.ffplay_process.poll() is None:
            try:
                self.ffplay_process.terminate()
                logger.info("Player terminated.")
            except Exception:
                pass
        if self.ytdlp_process and self.ytdlp_process.poll() is None:
            try:
                self.ytdlp_process.terminate()
                logger.info("yt-dlp stream process terminated.")
            except Exception:
                pass
        self.ffplay_process = None
        self.ytdlp_process = None
        # Reset per-movie state so next movie starts fresh
        self.idlix.reset_download_state()
        self._hide_status_bar()

    def open_download_folder(self):
        download_dir = os.path.abspath("Unduhan Film/Series")
        os.makedirs(download_dir, exist_ok=True)
        if os.name == 'nt':
            try:
                os.startfile(download_dir)
            except Exception:
                webbrowser.open(download_dir)
        else:
            webbrowser.open(download_dir)

    def clear_log(self):
        self.log_panel.log_box.configure(state="normal")
        self.log_panel.log_box.delete(1.0, tk.END)
        self.log_panel.log_box.configure(state="disabled")


# ============================================================
# RUN APP
# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = IdlixGUI(root)
    root.mainloop()
