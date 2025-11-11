from os import system
from sys import platform
from datetime import datetime
import ctypes
import json
import socket
import time

last_passing_per_athlete = {}
laps_per_athlete = {}
laps_per_athlete_displayable = {}

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
#HOST = "localhost"  # The decoder's address
HOST = "169.254.20.156"
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
            if len(row) > 2:  # ensure there are enough columns
                key = row[1]
                value = row[2]
                result[key] = value
    return result

#Saves the session as a text file
def save_session_to_file():
    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%Mmin")
    file_name = f"./sessions/session_{timestamp}.txt"
    try:
        with open(file_name, 'w', encoding='utf-8') as file:
            for key, value in laps_per_athlete.items():
                file.write(f"{key}: {value}\n")
    except IOError as e:
        print("Error writing to file...")

def handle_passing(passing):
    #If decoder message is not a passing, skip that message
    if passing[0]["msg"] != "PASSING":
        return
    #Get skater name from map. Unknown otherwise
    name = chipmap.get(passing[0]["tran_code"])
    if name == None:
        "Unknown chip passed"
        name = "Unknown"

    #Get and fix date from passing
    date_raw = passing[0]["rtc_time"]
    date_fixed = date_raw.replace(" UTC", "+00:00")
    date = datetime.fromisoformat(date_fixed)

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
    
    #If valid lap, update lists and ui
    lap_array = laps_per_athlete.get(name)
    if lap_array == None:
        laps_per_athlete[name] = [laptime]
        laps_per_athlete_displayable[name] = [laptime]
    else:
        lap_array.insert(0, laptime)
        laps_per_athlete[name] = lap_array
        laps_per_athlete_displayable[name] = lap_array[:10]
    clear_terminal()
    for key, value in laps_per_athlete_displayable.items():
            print(f"{key}: {value}")

#Main code goes here

#prompt for ip
user_input = input("Enter IP and enter. For default IP, enter with no input: ")
if user_input != "":
    HOST = user_input

#load chip assignment
chipmap = csv_file_to_map("./people.csv")
print(chipmap)

#create and handle connection
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    try:
        while True:
            try:
                s.connect((HOST, PORT))
                print("Socket connected!")
                while True:
                    data = s.recv(1024)
                    msg = data.hex()
                    handle_passing(decode_msg(msg))
            except Exception as e:
                print("Error connecting to decoder, retrying in 5 seconds: " + str(e))
                time.sleep(5)
    except KeyboardInterrupt:
        clear_terminal()
        print("Program exited through keyboard interrupt, saving data to file...")
        save_session_to_file()
                