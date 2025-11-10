import ctypes
import json
import socket
ammc = ctypes.CDLL("./ammc.dll")
ammc.p3_to_json.restype = ctypes.c_char_p
ammc.p3_to_json.argtypes = [ ctypes.c_char_p ]
def decode_msg(msg):
    return json.loads(ammc.p3_to_json(bytes(msg,'utf-8')))
import socket
HOST = "169.254.20.156"  # The server's hostname or IP address
PORT = 5403  # The port used by the server
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    while True:
        data = s.recv(1024)
        msg = data.hex()
        msg = decode_msg(msg)
        print(msg)
        if len(msg) > 1:
            print("More tahn one message sent")