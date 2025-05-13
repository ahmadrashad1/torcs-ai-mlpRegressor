import sys
import argparse
import socket
import threading
import csv
import time
from pynput import keyboard
import driver  # Make sure your driver module is available
import os

# Global dictionary to hold control states (updated by keyboard events)
control = {
    'accelerate': 0.0,
    'brake': 0.0,
    'steer': 0.0,
    'gear': 1
}

# Global flag for reverse command via "x" key.
reverse_requested = False

# Global variable to hold header order for sensor keys
header_keys = None

# Keyboard event handlers using pynput
def on_press(key):
    global reverse_requested
    try:
        if key.char.lower() == 'w':
            control['accelerate'] = 1.0
        elif key.char.lower() == 's':
            control['brake'] = 1.0
        elif key.char.lower() == 'a':
            control['steer'] = 1.0
        elif key.char.lower() == 'd':
            control['steer'] = -1.0
        elif key.char.lower() == 'x':
            reverse_requested = True
    except AttributeError:
        pass

def on_release(key):
    global reverse_requested
    try:
        if key.char.lower() == 'w':
            control['accelerate'] = 0.0
        elif key.char.lower() == 's':
            control['brake'] = 0.0
        elif key.char.lower() in ['a', 'd']:
            control['steer'] = 0.0
        elif key.char.lower() == 'x':
            reverse_requested = False
    except AttributeError:
        pass

# Start the keyboard listener in a separate thread
listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

# Automatic gear shifting logic with reverse integration via "x" key.
def auto_gear_control(sensor_data):
    global reverse_requested
    try:
        speed = float(sensor_data.get("speedX", 0))
        rpm = float(sensor_data.get("rpm", 0))
        gear = int(sensor_data.get("gear", 1))
    except Exception as e:
        print("Error parsing sensor data:", e)
        speed, rpm, gear = 0, 0, 1

    print(f"AutoGearControl -> Speed: {speed}, RPM: {rpm}, Gear: {gear}")

    # If "x" is pressed and speed is near zero, engage reverse gear.
    if reverse_requested and speed < 1.0:
        return -1

    # If currently in reverse but "x" is no longer pressed, shift back to first gear.
    if gear == -1 and not reverse_requested:
        return 1

    # Normal forward shifting logic:
    if gear <= 0:
        gear = 1

    if gear == 1 and rpm > 6100:
        return gear + 1

    if rpm > 5800 and gear < 6 and gear > 1:
        return gear + 1  # Upshift when RPM is high
    
    elif rpm < 2400 and gear > 1 and gear < 4:
        return gear - 1  # Downshift when RPM is low
    
    elif rpm < 3000 and gear == 4:
        return gear - 1  # Downshift when RPM is low
    
    elif rpm < 3500 and gear == 5:
        return gear - 1  # Downshift when RPM is low
    
    elif rpm < 4000 and gear == 6:
        return gear - 1  # Downshift when RPM is low
 
    return gear

# A manual driver class that uses keyboard inputs for control and logs telemetry.
class ManualDriver:
    def _init_(self, stage):
        self.stage = stage

    def init(self):
        # Return an initialization string as required by the server.
        return "(init 0)"

    def drive(self, sensor_data):
        sensor_dict = self.parse_sensor_data(sensor_data)
        print("Sensor data received:", sensor_dict)
        control['gear'] = auto_gear_control(sensor_dict)
        # If reverse is requested, automatically set acceleration to 1.0.
        if reverse_requested:
            control['accelerate'] = 1.0
        # Build the command string based on the current control state.
        cmd = f"(accel {control['accelerate']}) (brake {control['brake']}) (steer {control['steer']}) (gear {control['gear']})"
        print("Command sent:", cmd)
        return cmd

    def parse_sensor_data(self, data):
        sensor_dict = {}
        # Remove any surrounding parentheses and split the string.
        # This version supports keys with multiple values.
        parts = data.strip().strip('()').split(')(')
        for part in parts:
            key_val = part.split()
            if len(key_val) >= 2:
                key = key_val[0]
                # Join all remaining parts as the value.
                value = " ".join(key_val[1:])
                sensor_dict[key] = value
        return sensor_dict

    def onShutDown(self):
        pass

    def onRestart(self):
        pass

if __name__ == '_main_':
    # Argument parsing as provided in your project.
    parser = argparse.ArgumentParser(description='Python client to connect to the TORCS SCRC server.')
    parser.add_argument('--host', dest='host_ip', default='localhost',
                        help='Host IP address (default: localhost)')
    parser.add_argument('--port', type=int, dest='host_port', default=3001,
                        help='Host port number (default: 3001)')
    parser.add_argument('--id', dest='id', default='SCR',
                        help='Bot ID (default: SCR)')
    parser.add_argument('--maxEpisodes', type=int, dest='max_episodes', default=1,
                        help='Maximum number of learning episodes (default: 1)')
    parser.add_argument('--maxSteps', type=int, dest='max_steps', default=0,
                        help='Maximum number of steps (default: 0)')
    parser.add_argument('--track', dest='track', default=None,
                        help='Name of the track')
    parser.add_argument('--stage', type=int, dest='stage', default=3,
                        help='Stage (0 - Warm-Up, 1 - Qualifying, 2 - Race, 3 - Unknown)')
    arguments = parser.parse_args()

    print('Connecting to server host ip:', arguments.host_ip, '@ port:', arguments.host_port)
    print('Bot ID:', arguments.id)
    print('Maximum episodes:', arguments.max_episodes)
    print('Maximum steps:', arguments.max_steps)
    print('Track:', arguments.track)
    print('Stage:', arguments.stage)
    print('*')

    # Setup the UDP socket and set timeout.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except socket.error as msg:
        print('Could not make a socket.')
        sys.exit(-1)
    sock.settimeout(1.0)

    # Open the CSV file in append mode ('a') so new data is added.
    # If the file does not exist, we will create the header later when the first sensor data is parsed.
    csv_filename = 'telemetry_log.csv'
    file_exists = os.path.isfile(csv_filename)
    header_written = False
    if file_exists:
        with open(csv_filename, 'r', newline='') as f:
            first_line = f.readline().strip()
            # We'll set header_keys later, so just check if the file is empty or missing header
            header_written = bool(first_line)
    csv_file = open(csv_filename, 'a', newline='')
    csv_writer = csv.writer(csv_file)
    # Define control command columns that will be added to the header
    control_columns = ['accelerate', 'brake', 'steer', 'gear']
    header_keys = None

    shutdownClient = False
    curEpisode = 0
    d = ManualDriver(arguments.stage)

    # Handshake with the server.
    while not shutdownClient:
        while True:
            buf = arguments.id + d.init()
            try:
                sock.sendto(buf.encode('utf-8'), (arguments.host_ip, arguments.host_port))
            except socket.error as msg:
                print("Failed to send data...Exiting...")
                sys.exit(-1)
            try:
                buf, addr = sock.recvfrom(1000)
                buf = buf.decode('utf-8')
            except socket.error as msg:
                print("Didn't get response from server...")
                continue
            if 'identified' in buf:
                break

        currentStep = 0
        while True:
            try:
                buf, addr = sock.recvfrom(1000)
                buf = buf.decode('utf-8')
            except socket.error as msg:
                print("Didn't get response from server...")
                continue

            if 'shutdown' in buf:
                d.onShutDown()
                shutdownClient = True
                print('Client Shutdown')
                break

            if 'restart' in buf:
                d.onRestart()
                print('Client Restart')
                break

            # Parse the telemetry data into a dictionary.
            sensor_dict = d.parse_sensor_data(buf)
            # If header_keys is not set (first message), determine and write header if needed.
            if header_keys is None:
                header_keys = sorted(sensor_dict.keys())
                expected_header = ["timestamp"] + header_keys + control_columns
                if not header_written:
                    csv_writer.writerow(expected_header)
                    header_written = True

            # Build a row with the timestamp, sensor values, and control commands
            timestamp = time.time()
            row = [timestamp] + [sensor_dict.get(key, "N/A") for key in header_keys] + [
                control['accelerate'],
                control['brake'],
                control['steer'],
                control['gear']
            ]
            csv_writer.writerow(row)

            currentStep += 1
            if currentStep != arguments.max_steps:
                if buf:
                    buf = d.drive(buf)
            else:
                buf = '(meta 1)'

            try:
                sock.sendto(buf.encode('utf-8'), (arguments.host_ip, arguments.host_port))
            except socket.error as msg:
                print("Failed to send data...Exiting...")
                sys.exit(-1)

        curEpisode += 1
        if curEpisode == arguments.max_episodes:
            shutdownClient = True

    sock.close()
    csv_file.close()



#    if gear == 1 and rpm > 6500:
#        return gear + 1
#
#    if rpm > 6000 and gear < 6 and gear > 1:
#        return gear + 1  # Upshift when RPM is high
#    
#    elif rpm < 2400 and gear > 1 and gear < 4:
#        return gear - 1  # Downshift when RPM is low
#    
#    elif rpm < 3000 and gear == 4:
#        return gear - 1  # Downshift when RPM is low
#    
#    elif rpm < 3500 and gear == 5:
#        return gear - 1  # Downshift when RPM is low
#    
#    elif rpm < 4000 and gear == 6:
#        return gear - 1  # Downshift when RPM is low
#