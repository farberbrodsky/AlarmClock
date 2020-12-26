import threading, queue, json, copy, subprocess
from time import sleep
from datetime import datetime, timedelta
import simpleaudio as sa
from http.server import BaseHTTPRequestHandler, HTTPServer

day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

audio = sa.WaveObject.from_wave_file("alarm.wav")
# Find mice by names
mice_name = ["YICHIP Wireless Mouse", "MI Dongle MI Wireless Mouse"]
mice_filenames = []

with open("/proc/bus/input/devices", "r") as devices_file:
    lines = [x.strip() for x in devices_file.readlines()]
    for mouse_name in mice_name:
        for line_number in [i for i in range(len(lines))
        if lines[i] == "N: Name=\"" + mouse_name + "\""]:
            handlers_line = lines[line_number + 4][12:]
            if "mouse" in handlers_line:
                mouse_event_filename = "/dev/input/" + [x for x in handlers_line.split(" ") if x.startswith("mouse")][0]
                mice_filenames.append(mouse_event_filename)

snooze_mouse = mice_filenames[0]
disable_mouse = mice_filenames[1]

class MouseEvent():
    def __init__(self, filename, left, right, middle):
        self.filename = filename
        self.left = left
        self.right = right
        self.middle = middle

    def __str__(self):
        return "MouseEvent(" + self.filename + ", " + str(self.left) + \
                ", " + str(self.right) + ", " + str(self.middle) + ")"

def mouse_notifier(filename, event_queue):
    with open(filename, "rb") as mouse_file:
        while True:
            data_bytes = mouse_file.read(3)
            left = (data_bytes[0] & 0x01) != 0
            right = (data_bytes[0] & 0x02) != 0
            middle = (data_bytes[0] & 0x04) != 0
            # Other 2 bytes are x and y
            event_queue.put(MouseEvent(filename, left, right, middle))

config = {x: [] for x in day_names}
try:
    with open("alarm.json") as alarm_file:
        config = json.load(alarm_file)
except:
    pass

class ConfigEvent():
    def __init__(self, new_config):
        self.new_config = new_config

    def __str__(self):
        return "ConfigEvent(" + str(self.new_config) + ")"

def web_server_notifier(initial_config, event_queue):
    current_config = [initial_config]
    config_mutex = threading.Lock()
    class MyServer(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><meta charset=\"utf-8\"><title>Alarm</title></head><body>")
            with config_mutex:
                pretty_config = json.dumps(current_config[0], indent=2)
            self.wfile.write(f"<textarea autocomplete=\"off\" id=\"input\" style=\"width:100%;height:100%;\">{pretty_config}</textarea>".encode("utf-8"))
            self.wfile.write(b"<button onclick=\"save()\">Save</button>")
            self.wfile.write(b"<script>")
            js = """
            async function save() {
                let content = document.getElementById("input").value;
                console.log(content);
                try {
                    JSON.parse(content);
                    await fetch(location.origin, { method: "POST", body: content }).then(() => location.reload());
                } catch (err) {
                    console.error(err);
                    alert("Error");
                }
            }"""
            self.wfile.write(js.encode("utf-8"))
            self.wfile.write(b"</script>")
            self.wfile.write(b"</body></html>")
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "type/text")
            self.end_headers()
            self.wfile.write(b"ok")
            try:
                data = self.rfile.read().decode("utf-8")
                json_data = json.loads(data)
                # Add missing keys
                for day_name in day_names:
                    if not day_name in json_data:
                        json_data[day_name] = []
                with config_mutex:
                    current_config[0] = json_data
                    event_queue.put(ConfigEvent(current_config[0]))
            except Exception as e:
                pass
    web_server = HTTPServer(("0.0.0.0", 8080), MyServer)
    web_server.serve_forever()

event_queue = queue.Queue()
threading.Thread(target=mouse_notifier, args=[snooze_mouse, event_queue], daemon=True).start()
threading.Thread(target=mouse_notifier, args=[disable_mouse, event_queue], daemon=True).start()
threading.Thread(target=web_server_notifier, args=[copy.deepcopy(config), event_queue], daemon=True).start()

wake_up_time = None
wake_up_data = None
play_obj = None

def alarm_time(now, alarm_data):
    # { "hour": 8, "minutes": 0 } will return the timestamp of it today
    return datetime(now.year,
             now.month,
             now.day,
             alarm_data["hour"],
             alarm_data["minutes"] or 0
    )

def say(message):
    subprocess.Popen(["espeak", json.dumps(message)])

while True:
    while True:
        try:
            event = event_queue.get_nowait()
            if type(event) is MouseEvent:
                if event.filename == snooze_mouse and event.left:
                    # Snooze
                    now = datetime.now()
                    say(f"Wake up, it is {str(now.hour)}:{str(now.timetuple()[4]).zfill(2)}")
                    wake_up_time = datetime.now() + timedelta(seconds=30)
                    play_obj.stop()
                elif event.filename == disable_mouse and event.left:
                    # Disable
                    say("Alarm disabled, good morning!")
                    wake_up_time = None
                    play_obj.stop()
            elif type(event) is ConfigEvent:
                config = event.new_config
                with open("alarm.json", "w") as alarm_file:
                    json.dump(config, alarm_file)
                wake_up_time = None
        except:
            break
    if wake_up_time == None:
        # Try to get by schedule
        now = datetime.now()
        today_alarms = config[day_names[now.weekday()]]
        for alarm in today_alarms:
            potential_alarm_time = alarm_time(now, alarm)
            if potential_alarm_time > now and (wake_up_time == None or potential_alarm_time < wake_up_time):
                wake_up_time = potential_alarm_time
                wake_up_data = copy.deepcopy(alarm)
    if wake_up_time != None and datetime.now() > wake_up_time:
        if play_obj == None or not play_obj.is_playing():
            play_obj = audio.play()
    else:
        try:
            play_obj.stop()
        except:
            pass
    sleep(0.05)

