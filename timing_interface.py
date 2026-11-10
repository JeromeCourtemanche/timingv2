from os import system, makedirs
from sys import platform
from datetime import datetime, timedelta
import ctypes
import json
import queue
import socket
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

last_passing_per_athlete = {}
overall_last_passing = None
last_lead_lap = [0.00, "Ready"]
laps_per_athlete = {}
laps_per_athlete_displayable = {}
display_order = []  # athlete names, most recent valid lap first

# Thread-safe channel from the socket thread to the tkinter UI
ui_queue = queue.Queue()
session_saved = False

#Get OS, set path to proper library according to result. Crash the program if unsupported
libname = ""
if platform == "darwin":
    libname = "./libs/libammc.dylib"
elif "win" in platform:
    libname = "./libs/ammc.dll"
elif "linux" in platform:
    libname = "./libs/libammc.so"
else:
    print(f"AMMC lib is supported on Windows, Linux and MacOS platforms only. What platform is '{platform}'?")
    exit(1)

#Setup ammconverter using their library
ammc = ctypes.CDLL(libname)
ammc.p3_to_json.restype = ctypes.c_char_p
ammc.p3_to_json.argtypes = [ ctypes.c_char_p ]

#Setup other global variables
#HOST = "127.0.0.1"  # The decoder's address
HOST = "192.168.230.2"
PORT = 5403         # The port used by the server

###Function definition section

#Function to clear the terminal contents
def clear_terminal():
    if platform == 'darwin':
        _ = system('clear')
    elif "win" in platform:
        _ = system('cls')
    elif "linux" in platform:
        _ = system('clear')

#Takes a msh from the decoder as input, decodes it using ammc p3 and makes json of it
def decode_msg(msg):
    return json.loads(ammc.p3_to_json(bytes(msg,'utf-8')))

#loads chip assignments from csv and adds them to a map
def csv_file_to_map(file_path):
    """
    Reads a CSV file and creates a dictionary mapping column 2 -> column 3.
    """
    result = {}
    with open(file_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue  # skip empty lines
            row = line.split(',')
            if len(row) > 2:  # ensure there are enough columns
                key = row[1]
                value = row[2]
                result[key] = value
    return result

#Saves the session as a text file
def save_session_to_file():
    global session_saved
    if session_saved:
        return
    session_saved = True
    makedirs("./sessions", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%Mmin")
    file_name = f"./sessions/session_{timestamp}.txt"
    try:
        with open(file_name, 'w', encoding='utf-8') as file:
            for key, value in laps_per_athlete.items():
                file.write(f"{key}: {value}\n")
    except IOError as e:
        print("Error writing to file...")

def handle_passing(passing):
    global overall_last_passing, last_lead_lap

    #If decoder message is not a passing, skip that message
    if passing[0]["msg"] != "PASSING":
        return
    #Get skater name from map. Unknown otherwise
    name = chipmap.get(passing[0]["tran_code"])
    if name == None:
        name = "Unknown"

    #Get and fix date from passing
    date_raw = passing[0]["rtc_time"]
    date_fixed = date_raw.replace(" UTC", "+00:00")
    date = datetime.fromisoformat(date_fixed)

    #Check if passing was lead (more than 3 seconds since the previous passing of anyone)
    lead = False
    if overall_last_passing == None or date - overall_last_passing > timedelta(seconds=3):
        lead = True
    overall_last_passing = date

    #Get last passing of athlete. If none, means no lap, just change last passing
    last_passing = last_passing_per_athlete.get(name)
    if last_passing == None:
        last_passing_per_athlete[name] = date
        return

    #Calculate lap
    lap = date - last_passing
    raw_laptime = lap.total_seconds()
    laptime = round(raw_laptime, 2)
    last_passing_per_athlete[name] = date

    #If invalid time, return
    if laptime < 7.5 or laptime > 14:
        return

    #If valid lap, check if lead and update lead.
    if lead:
        last_lead_lap = [laptime, name]

    #If valid lap, update lists and ui
    lap_array = laps_per_athlete.get(name)
    if lap_array == None:
        laps_per_athlete[name] = [laptime]
        laps_per_athlete_displayable[name] = [laptime]
    else:
        lap_array.insert(0, laptime)
        laps_per_athlete[name] = lap_array
        laps_per_athlete_displayable[name] = lap_array[:10]

    #Move the athlete who just recorded a lap to the top of the display list
    if name in display_order:
        display_order.remove(name)
    display_order.insert(0, name)

    update_ui()

def update_ui():
    #Terminal output
    clear_terminal()
    print(f"Last lead: {last_lead_lap[0]} ({last_lead_lap[1]})")
    for name in display_order:
        print(f"{name}: {laps_per_athlete_displayable[name]}")

    #Send a snapshot to the tkinter window (it must only be touched from the main thread)
    #Snapshot is (lead lap, list of (name, last 10 times) pairs most recent lap first,
    #dict of name -> ALL laps, newest first)
    ui_queue.put((
        list(last_lead_lap),
        [(name, list(laps_per_athlete_displayable[name])) for name in display_order],
        {name: list(laps) for name, laps in laps_per_athlete.items()},
    ))

def decoder_loop():
    """Runs in a background thread: connects to the decoder and handles passings."""
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                print("Socket connected!")
                while True:
                    data = s.recv(1024)
                    if not data:
                        raise ConnectionError("Decoder closed the connection")
                    msg = data.hex()
                    try:
                        handle_passing(decode_msg(msg))
                    except Exception:
                        #A bad or unexpected message is ignored, the connection stays up
                        pass
        except Exception as e:
            print("Error connecting to decoder, retrying in 5 seconds: " + str(e))
            time.sleep(5)

###UI section

#--- Dark theme ---
BG = "#0d1117"          # window background
CARD = "#161b22"        # cards and rows
CARD_HOVER = "#1f2630"  # row under the pointer
BORDER = "#262d36"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#9ad7e8"      # newest lap in each row (soft, near-white cyan)
FLASH = "#1e4b5c"       # row colour when a new lap arrives, fades back to CARD
LEAD = "#4ade80"        # lead lap time (green, used nowhere else)
LEAD_EDGE = "#22c55e"   # stripe on the left of the lead card
LEAD_BG = "#14201a"     # lead card background
LEAD_BORDER = "#1f4d34"
LEAD_FLASH = "#166534"  # lead card colour when a new lead lap arrives, fades back to LEAD_BG
THUMB = "#30363d"       # scrollbar
PAD = 24

def mix(c1, c2, t):
    """Blend hex colour c1 into c2. t=0 gives c1, t=1 gives c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))

def pick_font(candidates, fallback):
    """First font from the list that is installed on this machine."""
    available = set(tkfont.families())
    for name in candidates:
        if name in available:
            return name
    return fallback

class ScrollList(tk.Frame):
    """Scrollable list of custom-drawn rows with hover, click, drag-scroll and row flash."""
    FLASH_MS = 1400
    DRAG_THRESHOLD = 6

    def __init__(self, parent, row_height, draw_row, on_click=None):
        super().__init__(parent, bg=BG)
        self.row_h = row_height
        self.draw_row = draw_row      # draw_row(canvas, x0, y0, x1, y1, row)
        self.on_click = on_click      # on_click(row), or None for a non-clickable list
        self.rows = []
        self.keys = []                # one unique key per row (used for flashing/anchoring)
        self.rendered_keys = []       # keys of what is actually drawn right now
        self.bg_items = []            # canvas id of each drawn row background
        self.hover = None
        self.flashes = {}             # key -> time the flash started
        self.anim = None
        self.press = None             # (y, key) while the mouse button is down
        self.dragging = False
        self.pending = False          # a redraw was postponed because of a drag

        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0,
                                yscrollincrement=max(1, row_height // 2))
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       style="Dark.Vertical.TScrollbar",
                                       command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y", padx=(10, 0))
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda e: self.set_hover(None))

    #--- Data ---
    def set_rows(self, rows, keys):
        if rows == self.rows and keys == self.keys:
            return
        self.rows, self.keys = rows, keys
        self.render()

    def reset(self):
        self.rows, self.keys, self.rendered_keys = [], [], []
        self.flashes = {}
        self.hover = None
        self.canvas.yview_moveto(0)

    def flash(self, key):
        self.flashes[key] = time.monotonic()
        if self.anim is None:
            self.animate()

    def scroll(self, units):
        self.canvas.yview_scroll(units, "units")

    #--- Drawing ---
    def color(self, i, key):
        base = CARD_HOVER if i == self.hover else CARD
        start = self.flashes.get(key)
        if start is not None:
            t = (time.monotonic() - start) * 1000 / self.FLASH_MS
            if t < 1:
                return mix(FLASH, base, t * t)
        return base

    def render(self):
        if self.dragging:
            self.pending = True  # redraw when the finger/mouse is released
            return
        w = self.canvas.winfo_width()
        if w <= 1:
            return  # not laid out yet, <Configure> will call us again
        h = self.canvas.winfo_height()
        row_h = self.row_h

        #Remember which row is at the top of the view so it stays put when rows move around
        top_px = self.canvas.canvasy(0)
        anchor = None
        if top_px > 0:
            i = int(top_px // row_h)
            if i < len(self.rendered_keys):
                anchor = (self.rendered_keys[i], top_px - i * row_h)

        self.canvas.delete("all")
        self.bg_items = []
        for i, row in enumerate(self.rows):
            y0 = i * row_h + 3
            y1 = (i + 1) * row_h - 3
            self.bg_items.append(self.canvas.create_rectangle(
                1, y0, w - 2, y1, fill=self.color(i, self.keys[i]), outline=BORDER))
            self.draw_row(self.canvas, 1, y0, w - 2, y1, row)

        region_h = max(len(self.rows) * row_h, h)
        self.canvas.configure(scrollregion=(0, 0, w, region_h))
        new_top = top_px
        if anchor is not None and anchor[0] in self.keys:
            new_top = self.keys.index(anchor[0]) * row_h + anchor[1]
        self.canvas.yview_moveto(new_top / region_h)
        self.rendered_keys = list(self.keys)

    def animate(self):
        now = time.monotonic()
        for i, key in enumerate(self.rendered_keys):
            if key in self.flashes and i < len(self.bg_items):
                self.canvas.itemconfig(self.bg_items[i], fill=self.color(i, key))
        self.flashes = {k: s for k, s in self.flashes.items()
                        if (now - s) * 1000 < self.FLASH_MS}
        self.anim = self.after(30, self.animate) if self.flashes else None

    #--- Mouse / touch ---
    def row_at(self, event_y):
        i = int(self.canvas.canvasy(event_y) // self.row_h)
        return i if 0 <= i < len(self.rendered_keys) else None

    def set_hover(self, idx):
        if idx == self.hover:
            return
        old, self.hover = self.hover, idx
        for i in (old, idx):
            if i is not None and i < len(self.bg_items):
                self.canvas.itemconfig(self.bg_items[i],
                                       fill=self.color(i, self.rendered_keys[i]))

    def on_motion(self, e):
        if self.on_click is not None and not self.dragging:
            self.set_hover(self.row_at(e.y))

    def on_press(self, e):
        i = self.row_at(e.y)
        self.press = (e.y, self.rendered_keys[i] if i is not None else None)
        self.dragging = False
        self.canvas.scan_mark(0, e.y)

    def on_drag(self, e):
        if self.press is None:
            return
        if not self.dragging and abs(e.y - self.press[0]) > self.DRAG_THRESHOLD:
            self.dragging = True
        if self.dragging:
            self.canvas.scan_dragto(0, e.y, gain=1)

    def on_release(self, e):
        press, was_click = self.press, not self.dragging
        self.press = None
        self.dragging = False
        if self.pending:
            self.pending = False
            self.render()
        if was_click and press and press[1] is not None and self.on_click:
            if press[1] in self.keys:
                self.on_click(self.rows[self.keys.index(press[1])])

class TimingWindow:
    def __init__(self, root):
        self.root = root
        root.title("Lap timing")
        root.configure(bg=BG)

        #Start large: the fonts are big
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = int(sw * 0.9), int(sh * 0.85)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        root.minsize(700, 450)

        self.setup_fonts()
        self.setup_style()

        self.all_laps = {}      # name -> ALL laps, newest first
        self.lap_counts = {}    # name -> number of laps seen so far (to detect new laps)
        self.name_w = 0         # width of the widest athlete name
        self.selected = None    # athlete whose laps are open, None on the main page
        self.detail_count = 0

        #--- Main page: fixed lead card on top, scrollable athlete list below ---
        self.main_view = tk.Frame(root, bg=BG)

        card = tk.Frame(self.main_view, bg=LEAD_BG, highlightbackground=LEAD_BORDER,
                        highlightthickness=1)
        card.pack(fill="x", padx=PAD, pady=(PAD, 12))
        tk.Frame(card, bg=LEAD_EDGE, width=8).pack(side="left", fill="y")
        inner = tk.Frame(card, bg=LEAD_BG)
        inner.pack(side="left", fill="x", expand=True, padx=28, pady=(16, 10))
        caption = tk.Label(inner, text="LAST LEAD", font=self.f_caption, bg=LEAD_BG, fg=MUTED)
        caption.pack(anchor="w")
        lead_row = tk.Frame(inner, bg=LEAD_BG)
        lead_row.pack(fill="x", anchor="w")
        self.lead_time = tk.Label(lead_row, text=f"{last_lead_lap[0]:.2f}",
                                  font=self.f_lead_time, bg=LEAD_BG, fg=LEAD)
        self.lead_time.pack(side="left")
        self.lead_name = tk.Label(lead_row, text=last_lead_lap[1],
                                  font=self.f_lead_name, bg=LEAD_BG, fg=TEXT)
        self.lead_name.pack(side="left", anchor="s", padx=(28, 0), pady=(0, 18))

        #Everything on the card that has the card's background colour (used by the flash)
        self.lead_widgets = [card, inner, caption, lead_row, self.lead_time, self.lead_name]
        self.last_lead = (last_lead_lap[0], last_lead_lap[1])
        self.lead_flash_start = None

        main_row_h = max(self.f_name.metrics("linespace"),
                         self.f_time_b.metrics("linespace")) + 36
        self.live_list = ScrollList(self.main_view, main_row_h, self.draw_main_row,
                                    on_click=self.on_row_click)
        self.live_list.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

        #--- Detail page: every lap of the clicked athlete ---
        self.detail_view = tk.Frame(root, bg=BG)
        header = tk.Frame(self.detail_view, bg=BG)
        header.pack(fill="x", padx=PAD, pady=(PAD, 12))

        back = tk.Label(header, text="\u2039  Back", font=self.f_back, bg=CARD, fg=TEXT,
                        padx=22, pady=10, cursor="hand2", highlightbackground=BORDER,
                        highlightthickness=1)
        back.pack(side="left")
        back.bind("<Button-1>", lambda e: self.show_main())
        back.bind("<Enter>", lambda e: back.config(bg=CARD_HOVER))
        back.bind("<Leave>", lambda e: back.config(bg=CARD))

        self.title_name = tk.Label(header, text="", font=self.f_title, bg=BG, fg=TEXT)
        self.title_name.pack(side="left", padx=(28, 0))
        self.title_count = tk.Label(header, text="", font=self.f_count, bg=BG, fg=MUTED)
        self.title_count.pack(side="left", anchor="s", padx=(20, 0), pady=(0, 10))

        detail_row_h = max(self.f_laptime.metrics("linespace"),
                           self.f_lapnum.metrics("linespace")) + 28
        self.detail_list = ScrollList(self.detail_view, detail_row_h, self.draw_detail_row)
        self.detail_list.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

        #Mouse wheel scrolls whichever list is on screen
        self.current_list = self.live_list
        root.bind_all("<MouseWheel>", self.on_wheel)
        root.bind_all("<Button-4>", self.on_wheel)
        root.bind_all("<Button-5>", self.on_wheel)

        self.main_view.pack(fill="both", expand=True)
        self.poll_queue()

    #--- Setup ---
    def setup_fonts(self):
        sans = pick_font(["Segoe UI", "SF Pro Display", "Helvetica Neue", "Inter",
                          "Roboto", "Ubuntu", "DejaVu Sans", "Helvetica", "Arial"], "Helvetica")
        mono = pick_font(["Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono",
                          "Liberation Mono", "Courier New"], "Courier")
        F = tkfont.Font
        self.f_caption = F(family=sans, size=14, weight="bold")
        self.f_lead_time = F(family=mono, size=90, weight="bold")
        self.f_lead_name = F(family=sans, size=32)
        self.f_name = F(family=sans, size=32, weight="bold")
        self.f_time = F(family=mono, size=32)
        self.f_time_b = F(family=mono, size=32, weight="bold")
        self.f_title = F(family=sans, size=52, weight="bold")
        self.f_count = F(family=sans, size=24)
        self.f_back = F(family=sans, size=24, weight="bold")
        self.f_lapnum = F(family=sans, size=24)
        self.f_laptime = F(family=mono, size=40, weight="bold")

        self.time_w = max(self.f_time.measure("00.00"), self.f_time_b.measure("00.00"))
        self.lapnum_w = self.f_lapnum.measure("Lap 0000")

    def setup_style(self):
        #The "clam" theme is the one ttk theme that lets the scrollbar be coloured everywhere
        style = ttk.Style(self.root)
        style.theme_use("clam")
        name = "Dark.Vertical.TScrollbar"
        style.layout(name, [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure(name, background=THUMB, troughcolor=BG, bordercolor=BG,
                        lightcolor=THUMB, darkcolor=THUMB, arrowsize=22, gripcount=0)
        for opt in ("background", "lightcolor", "darkcolor"):
            style.map(name, **{opt: [("pressed", "#6e7681"), ("active", "#484f58")]})

    #--- Lead card flash ---
    def flash_lead(self):
        running = self.lead_flash_start is not None
        self.lead_flash_start = time.monotonic()
        if not running:
            self.animate_lead()

    def animate_lead(self):
        t = (time.monotonic() - self.lead_flash_start) * 1000 / ScrollList.FLASH_MS
        if t >= 1:
            color = LEAD_BG
            self.lead_flash_start = None
        else:
            color = mix(LEAD_FLASH, LEAD_BG, t * t)
        for widget in self.lead_widgets:
            widget.config(bg=color)
        if self.lead_flash_start is not None:
            self.root.after(30, self.animate_lead)

    #--- Page switching ---
    def show_main(self):
        self.selected = None
        self.detail_view.pack_forget()
        self.main_view.pack(fill="both", expand=True)
        self.current_list = self.live_list
        self.root.update_idletasks()
        self.live_list.render()

    def show_detail(self, name):
        self.selected = name
        self.main_view.pack_forget()
        self.detail_view.pack(fill="both", expand=True)
        self.current_list = self.detail_list
        self.detail_list.reset()
        self.detail_count = len(self.all_laps.get(name, []))
        self.root.update_idletasks()
        self.refresh_detail()

    def on_row_click(self, row):
        self.show_detail(row[0])

    def on_wheel(self, e):
        if e.num == 4:
            units = -2
        elif e.num == 5:
            units = 2
        elif platform == "darwin":
            units = -e.delta
        else:
            units = -2 if e.delta > 0 else 2
        self.current_list.scroll(units)

    #--- Drawing rows ---
    def draw_main_row(self, canvas, x0, y0, x1, y1, row):
        name, times = row
        cy = (y0 + y1) / 2
        pad = 28
        canvas.create_text(x0 + pad, cy, text=name, anchor="w", fill=TEXT, font=self.f_name)
        canvas.create_text(x1 - pad, cy, text="\u203a", anchor="e", fill=MUTED, font=self.f_name)

        #As many of the 10 most recent times as fit in the window width, newest first
        start = x0 + pad + self.name_w + 48
        limit = x1 - pad - self.f_name.measure("\u203a") - 24
        col_w = self.time_w + 30
        count = max(0, min(len(times), int((limit - start + 30) // col_w)))
        for j in range(count):
            x = start + j * col_w + self.time_w
            if j == 0:
                canvas.create_text(x, cy, text=f"{times[j]:.2f}", anchor="e",
                                   fill=ACCENT, font=self.f_time_b)
            else:
                canvas.create_text(x, cy, text=f"{times[j]:.2f}", anchor="e",
                                   fill=MUTED, font=self.f_time)

    def draw_detail_row(self, canvas, x0, y0, x1, y1, row):
        number, laptime, newest = row
        cy = (y0 + y1) / 2
        canvas.create_text(x0 + 28, cy, text=f"Lap {number}", anchor="w",
                           fill=MUTED, font=self.f_lapnum)
        canvas.create_text(x0 + 28 + self.lapnum_w + 60, cy, text=f"{laptime:.2f}",
                           anchor="w", fill=ACCENT if newest else TEXT, font=self.f_laptime)

    #--- Refreshing ---
    def refresh_detail(self):
        #laps is newest first; lap 1 is the oldest
        laps = self.all_laps.get(self.selected, [])
        total = len(laps)
        rows = [(total - i, t, i == 0) for i, t in enumerate(laps)]
        self.title_name.config(text=self.selected)
        self.title_count.config(text=f"{total} lap" if total == 1 else f"{total} laps")
        self.detail_list.set_rows(rows, [r[0] for r in rows])
        if total > self.detail_count:
            self.detail_list.flash(total)
        self.detail_count = total

    def poll_queue(self):
        try:
            self.update_from_queue()
        finally:
            #Always schedule the next check, so one error can't freeze the display
            self.root.after(100, self.poll_queue)

    def update_from_queue(self):
        #Only the newest snapshot matters
        latest = None
        try:
            while True:
                latest = ui_queue.get_nowait()
        except queue.Empty:
            pass

        if latest is not None:
            lead, laps, all_laps = latest
            self.all_laps = all_laps
            self.lead_time.config(text=f"{lead[0]:.2f}")
            self.lead_name.config(text=lead[1])
            if (lead[0], lead[1]) != self.last_lead:
                self.last_lead = (lead[0], lead[1])
                self.flash_lead()

            names = [name for name, _ in laps]
            self.name_w = max((self.f_name.measure(n) for n in names), default=0)
            self.live_list.set_rows(laps, names)

            #Flash the rows of everyone who completed a new lap
            for name, athlete_laps in all_laps.items():
                if len(athlete_laps) > self.lap_counts.get(name, 0):
                    self.live_list.flash(name)
                self.lap_counts[name] = len(athlete_laps)

            if self.selected is not None:
                self.refresh_detail()


###Main code goes here

#prompt for ip
user_input = input("Enter IP and enter. For default IP, enter with no input: ")
if user_input != "":
    HOST = user_input

#load chip assignment
chipmap = csv_file_to_map("./people.csv")
print(chipmap)

#start the decoder connection in the background, run the UI in the main thread
threading.Thread(target=decoder_loop, daemon=True).start()

root = tk.Tk()
window = TimingWindow(root)

def on_close():
    print("Window closed, saving data to file...")
    save_session_to_file()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

try:
    root.mainloop()
except KeyboardInterrupt:
    clear_terminal()
    print("Program exited through keyboard interrupt, saving data to file...")
    save_session_to_file()