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
HOST = "127.0.0.1"  # The decoder's address
#HOST = "192.168.230.2"
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
                    handle_passing(decode_msg(msg))
        except Exception as e:
            print("Error connecting to decoder, retrying in 5 seconds: " + str(e))
            time.sleep(5)

###UI section

class TimingWindow:
    LEAD_FONT = ("Helvetica", 72, "bold")
    LIST_FONT = ("Courier", 32)
    TITLE_FONT = ("Helvetica", 52, "bold")
    SCROLLBAR_WIDTH = 30  # wide so it is easy to grab on a touch screen

    def __init__(self, root):
        self.root = root
        root.title("Lap timing")
        root.geometry("900x600")

        self.all_laps = {}      # name -> ALL laps, newest first
        self.order = []         # athlete names in the same order as the list on screen
        self.live_lines = []    # text currently shown in the main list
        self.detail_lines = []  # text currently shown in the detail list
        self.selected = None    # athlete whose laps are open, None on the main page

        #--- Main page: fixed lead lap on top, scrollable athlete list below ---
        self.main_view = tk.Frame(root)

        self.lead_label = tk.Label(self.main_view, text=self._lead_text(last_lead_lap),
                                   font=self.LEAD_FONT, anchor="w", justify="left",
                                   padx=15, pady=10)
        self.lead_label.pack(fill="x")
        tk.Frame(self.main_view, height=2, bg="gray").pack(fill="x", padx=10)

        scroll = tk.Scrollbar(self.main_view, width=self.SCROLLBAR_WIDTH)
        scroll.pack(side="right", fill="y")
        self.live_box = tk.Listbox(self.main_view, font=self.LIST_FONT,
                                   activestyle="none", exportselection=False,
                                   yscrollcommand=scroll.set)
        self.live_box.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.live_box.yview)
        self.live_box.bind("<<ListboxSelect>>", self.on_select)

        #--- Detail page: every lap of the clicked athlete ---
        self.detail_view = tk.Frame(root)
        header = tk.Frame(self.detail_view)
        header.pack(fill="x")
        tk.Button(header, text="< Back", font=("Helvetica", 36),
                  command=self.show_main).pack(side="left", padx=10, pady=10)
        self.title_label = tk.Label(header, text="", font=self.TITLE_FONT)
        self.title_label.pack(side="left", padx=10)

        detail_scroll = tk.Scrollbar(self.detail_view, width=self.SCROLLBAR_WIDTH)
        detail_scroll.pack(side="right", fill="y")
        self.laps_box = tk.Listbox(self.detail_view, font=("Courier", 40),
                                   activestyle="none", exportselection=False,
                                   selectbackground="white", selectforeground="black",
                                   yscrollcommand=detail_scroll.set)
        self.laps_box.pack(side="left", fill="both", expand=True)
        detail_scroll.config(command=self.laps_box.yview)

        self.show_main()
        self.poll_queue()

    @staticmethod
    def _lead_text(lead):
        return f"Last lead: {lead[0]} ({lead[1]})"

    #--- Page switching ---
    def show_main(self):
        self.selected = None
        self.detail_view.pack_forget()
        self.main_view.pack(fill="both", expand=True)
        self.live_box.selection_clear(0, "end")

    def show_detail(self, name):
        self.selected = name
        self.main_view.pack_forget()
        self.detail_view.pack(fill="both", expand=True)
        self.detail_lines = []  # force a rebuild
        self.refresh_detail()

    def on_select(self, event):
        sel = self.live_box.curselection()
        if sel and sel[0] < len(self.order):
            name = self.order[sel[0]]
            self.live_box.selection_clear(0, "end")  # so the same name can be tapped again later
            self.show_detail(name)

    #--- Refreshing ---
    def refresh_live(self, laps):
        #laps is a list of (name, last 10 times), most recent lap first
        width = max((len(name) for name, _ in laps), default=0)
        lines = [f"{name:<{width}}  " + ", ".join(f"{t:.2f}" for t in times)
                 for name, times in laps]
        if lines != self.live_lines:
            top = self.live_box.yview()[0]
            self.live_box.delete(0, "end")
            for line in lines:
                self.live_box.insert("end", line)
            self.live_box.yview_moveto(top)
            self.live_lines = lines
            self.order = [name for name, _ in laps]

    def refresh_detail(self):
        #laps is newest first; lap 1 is the oldest
        laps = self.all_laps.get(self.selected, [])
        total = len(laps)
        lines = [f"Lap {total - i:>3}:  {t:.2f}" for i, t in enumerate(laps)]
        self.title_label.config(text=f"{self.selected}  ({total} laps)")
        if lines != self.detail_lines:
            top = self.laps_box.yview()[0]
            self.laps_box.delete(0, "end")
            for line in lines:
                self.laps_box.insert("end", line)
            self.laps_box.yview_moveto(top)
            self.detail_lines = lines

    def poll_queue(self):
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
            self.lead_label.config(text=self._lead_text(lead))
            self.refresh_live(laps)
            if self.selected is not None:
                self.refresh_detail()

        self.root.after(100, self.poll_queue)

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