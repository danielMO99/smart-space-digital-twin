"""Instance MQTT adapter. Measurement state belongs to RadarNormalizer."""
import json
import os
from .acquisition_diagnostics import AcquisitionDiagnostics, DiagnosticPolicy
import time
import paho.mqtt.client as mqtt
from .radar_normalizer import RadarNormalizer
from .frame_acquisition import FrameAcquisition
from mqtt_capture.frames import FRAME_TOPIC
BROKER='192.168.1.200'
PORT=1883
TOPIC='smartspace/esp32/sensor/#'
class MQTTConsumer:
    def __init__(self, normalizer=None, *, mode="legacy"):
        if mode not in ("legacy", "frames"):
            raise ValueError("Acquisition mode must be legacy or frames")
        self.mode = mode
        self.on_frame = None
        self.normalizer=normalizer or (FrameAcquisition() if mode == "frames" else RadarNormalizer())
        self.callback_errors=0
        self.normalizer.transport(False)
        self.diagnostics = AcquisitionDiagnostics(self.normalizer, mode=mode,
            policy=DiagnosticPolicy(**json.loads(os.getenv("SMARTSPACE_DIAGNOSTICS_CONFIG", "{}"))))
    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.normalizer.transport(reason_code==0)
        self.diagnostics.connection_changed()
        if reason_code==0: client.subscribe(FRAME_TOPIC if self.mode == "frames" else TOPIC)
    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.normalizer.transport(False)
        self.diagnostics.connection_changed()
    def on_message(self, client, userdata, msg):
        try:
            with self.normalizer.lock:
                outcome = self.normalizer.ingest(msg.topic,msg.payload,msg.retain)
                self.diagnostics.observe(outcome)
                if self.mode == "frames" and outcome == "accepted" and self.on_frame is not None:
                    self.on_frame(self.normalizer.snapshot())
                return outcome
        except Exception:
            self.callback_errors+=1
            self.normalizer.transport(False)
            return 'callback_error'
    def build_frame(self): return self.normalizer.snapshot()
def main():
    consumer=MQTTConsumer()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect,client.on_message=consumer.on_connect,consumer.on_message
    client.on_disconnect=consumer.on_disconnect
    client.connect(BROKER,PORT,60)
    client.loop_start()
    try:
        while True:
            time.sleep(1)
            print(json.dumps(consumer.build_frame()))
    except KeyboardInterrupt: pass
    finally:
        client.disconnect()
        client.loop_stop()
if __name__=='__main__': main()
