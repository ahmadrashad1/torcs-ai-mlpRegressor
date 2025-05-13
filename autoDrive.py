import sys
import argparse
import socket
import numpy as np
import joblib
from sklearn.preprocessing import StandardScaler

# ======== Globals ========
control = {'accelerate': 0.0, 'brake': 0.0, 'steer': 0.0, 'gear': 1}
mlp_model = None
input_scaler = None
header_keys = None

# ======== Auto Gear Logic ========
def auto_gear_control(sensor_data):
    try:
        speed = float(sensor_data.get("speedX", 0))
        rpm = float(sensor_data.get("rpm", 0))
        gear = int(sensor_data.get("gear", 1))
    except:
        speed, rpm, gear = 0, 0, 1

    if gear <= 0: gear = 1
    if gear == 1 and rpm > 6100: return gear + 1
    if rpm > 5800 and gear < 6 and gear > 1: return gear + 1
    if rpm < 2400 and gear > 1 and gear < 4: return gear - 1
    if rpm < 3000 and gear == 4: return gear - 1
    if rpm < 3500 and gear == 5: return gear - 1
    if rpm < 4000 and gear == 6: return gear - 1
    return gear

# ======== Driver Class ========
class AutonomousDriver:
    def __init__(self, stage, autonomous=False):

        self.stage = stage
        self.autonomous = autonomous

    def init(self):
        return "(init 0)"

    def drive(self, sensor_data):
        global mlp_model, input_scaler, header_keys
        sensor_dict = self.parse_sensor_data(sensor_data)
        control['gear'] = auto_gear_control(sensor_dict)

        if self.autonomous and mlp_model and input_scaler and header_keys:
            try:
                # === Input Preparation ===
                input_values = []
                for k in header_keys:
                    raw_value = sensor_dict.get(k, "0.0").strip()

                    try:
                        # Extract float values from possible lists
                        float_vals = [float(x) for x in raw_value.split()[:5] if x.replace('.', '', 1).replace('-', '', 1).isdigit()]
                        if float_vals:
                            input_values.append(np.mean(float_vals))  # You may use min/max/index too
                        else:
                            input_values.append(0.0)
                    except Exception as parse_err:
                        print(f"Warning: key={k}, raw_value={raw_value} -> {parse_err}")
                        input_values.append(0.0)

                input_vector = np.array([input_values])
                input_scaled = input_scaler.transform(input_vector)
                pred = mlp_model.predict(input_scaled)[0]

                control['accelerate'] = float(pred[0])
                control['brake'] = float(pred[1])
                control['steer'] = float(pred[2])
                #predicted_gear = int(round(pred[3]))
                #control['gear'] = max(1, min(6, predicted_gear))

            except Exception as e:
                print("Model prediction failed:", e)

        cmd = f"(accel {control['accelerate']}) (brake {control['brake']}) (steer {control['steer']}) (gear {control['gear']})"
        return cmd

    def parse_sensor_data(self, data):
        sensor_dict = {}
        parts = data.strip().strip('()').split(')(')
        for part in parts:
            key_val = part.split()
            if len(key_val) >= 2:
                key = key_val[0]
                value = " ".join(key_val[1:])
                sensor_dict[key] = value
        return sensor_dict

    def onShutDown(self): pass
    def onRestart(self): pass

# ======== Main Function ========
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=3001)
    parser.add_argument('--id', default='SCR')
    parser.add_argument('--maxEpisodes', type=int, default=1)
    parser.add_argument('--maxSteps', type=int, default=0)
    parser.add_argument('--track', default=None)
    parser.add_argument('--stage', type=int, default=3)
    parser.add_argument('--autonomous', action='store_true', help='Use trained MLP model to drive')
    parser.add_argument('--model', default='torcs_mlp_model.pkl', help='Path to MLP model')
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} | Bot ID: {args.id} | Autonomous: {args.autonomous}")

    if args.autonomous:
        try:
            mlp_model = joblib.load(args.model)
            input_scaler = joblib.load("input_scaler.pkl")
            print("Loaded model and scaler.")
        except Exception as e:
            print(f"Failed to load model or scaler: {e}")
            sys.exit(-1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)

    shutdownClient = False
    curEpisode = 0
    d = AutonomousDriver(args.stage, args.autonomous)

    while not shutdownClient:
        while True:
            buf = args.id + d.init()
            try:
                sock.sendto(buf.encode('utf-8'), (args.host, args.port))
                buf, addr = sock.recvfrom(1000)
                if 'identified' in buf.decode(): break
            except: continue

        currentStep = 0
        while True:
            try:
                buf, addr = sock.recvfrom(1000)
                buf = buf.decode('utf-8')
            except: continue

            if 'shutdown' in buf:
                d.onShutDown()
                shutdownClient = True
                print('Shutdown signal received.')
                break

            if 'restart' in buf:
                d.onRestart()
                print('Restarting client.')
                break

            sensor_dict = d.parse_sensor_data(buf)

            # Initialize headers (excluding very long or multi-value sensors)
            if header_keys is None:
                header_keys = ['speedX', 'speedY', 'speedZ', 'rpm', 'gear', 'trackPos', 'angle']

            buf = d.drive(buf)

            try:
                sock.sendto(buf.encode('utf-8'), (args.host, args.port))
            except socket.error:
                print("Failed to send data.")
                sys.exit(-1)

        curEpisode += 1
        if curEpisode == args.maxEpisodes:
            shutdownClient = True

    sock.close()