from os import system
from sys import platform
from datetime import datetime
#from dateutil import parser
import ctypes
import json
import socket

last_passing_per_athlete = {}
laps_per_athlete = {}

#Get OS, set path to proper library according to result. Crash the program if unsupported
libname = ""
if platform == "darwin":
    libname = "./libammc.dylib"
elif "win" in platform:
    libname = "./ammc.dll"
elif "linux" in platform:
    libname = "./libammc.so"
else:
    print(f"AMMC lib is supported on Windows, Linux and MacOS platforms only. What platform is '{platform}'?")
    exit(1)

#Setup ammconverter using their library
ammc = ctypes.CDLL(libname)
ammc.p3_to_json.restype = ctypes.c_char_p
ammc.p3_to_json.argtypes = [ ctypes.c_char_p ]

#Setup other global variables
HOST = "localhost"  # The decoder's address
PORT = 5403         # The port used by the server

###Function definition section

#Function to clear the terminal contents
def clear_terminal():
    # for Windows
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
    Reads a CSV file and creates a dictionary mapping column 2 -> column 6.
    """
    result = {}
    with open(file_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue  # skip empty lines
            row = line.split(',')
            if len(row) > 6:  # ensure there are enough columns
                key = row[2]
                value = row[6]
                result[key] = value
    return result

def handle_passing(passing):
    if passing[0]["msg"] != "PASSING":
        return
    name = chipmap.get(passing[0]["tran_code"])
    if name == None:
        "Unknown chip passed"
        name = "Unknown"
    #print("passing for"+name)
    date_raw = passing[0]["rtc_time"]
    date_fixed = date_raw.replace(" UTC", "+00:00")
    date = datetime.fromisoformat(date_fixed)

    last_passing = last_passing_per_athlete.get(name)

    if last_passing == None:
        last_passing_per_athlete[name] = date
        #print("last passing of ath was null")
        return
    
    lap = date - last_passing
    laptime = lap.total_seconds()
    last_passing_per_athlete[name] = date

    if laptime < 7.5 or laptime > 14:
        return
    lap_array = laps_per_athlete.get(name)
    if lap_array == None:
        laps_per_athlete[name] = [laptime]
    else:
        lap_array.insert(0, laptime)
        laps_per_athlete[name] = lap_array

#Main code goes here
chipmap = csv_file_to_map("./people.csv")
print(chipmap)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    while True:
        data = s.recv(1024)
        msg = data.hex()
        handle_passing(decode_msg(msg))
        #print(last_passing_per_athlete)
        clear_terminal()
        #print(laps_per_athlete)
        for key, value in laps_per_athlete.items():
            print(f"{key}: {value}")