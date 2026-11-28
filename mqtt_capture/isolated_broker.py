"""Owned, ephemeral loopback Mosquitto. Never attach to an existing broker."""

from contextlib import ExitStack
from pathlib import Path
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import uuid

import paho.mqtt.client as mqtt

from .record import ALL_TELEMETRY_TOPICS


class IsolatedBroker:
    host = "127.0.0.1"

    def __init__(self, executable):
        self.executable = Path(executable).resolve()
        self.port = None
        self.process = None
        self.username = "replay-" + uuid.uuid4().hex
        self.password = secrets.token_urlsafe(32)
        self.stack = ExitStack()

    def __enter__(self):
        try:
            suffix = ".exe" if os.name == "nt" else ""
            passwd_exe = self.executable.with_name("mosquitto_passwd" + suffix)
            if not self.executable.is_file() or not passwd_exe.is_file():
                raise ValueError("Se requieren mosquitto y mosquitto_passwd en la misma carpeta")
            folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="smartspace-replay-")))
            password_file = folder / "passwords"
            password_file.write_text(f"{self.username}:{self.password}\n", encoding="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            # No secrets in command line, console, capture or derived evidence.
            subprocess.run([str(passwd_exe), "-U", str(password_file)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=10, creationflags=flags)
            with socket.socket() as reservation:
                reservation.bind((self.host, 0))
                self.port = reservation.getsockname()[1]
            if self.port == 1883:
                raise RuntimeError("Puerto reservado no permitido")
            acl = folder / "acl"
            acl.write_text("user " + self.username + "\n" + "".join(
                f"topic readwrite {topic}\n" for topic in ALL_TELEMETRY_TOPICS), encoding="utf-8")
            config = folder / "mosquitto.conf"
            config.write_text(
                f"listener {self.port} 127.0.0.1\nallow_anonymous false\n"
                f"password_file {password_file.as_posix()}\nacl_file {acl.as_posix()}\n"
                "persistence false\nmax_inflight_messages 1\nlog_dest stderr\n", encoding="utf-8")
            # No default config, bridges, plugins, service registration or LAN listener.
            self.process = subprocess.Popen([str(self.executable), "-c", str(config)],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            creationflags=flags)
            self.stack.callback(self._stop)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.check()
                try:
                    with socket.create_connection((self.host, self.port), timeout=0.1):
                        pass
                    # An unrelated process winning the port race cannot authenticate
                    # our random credentials. Also verify our child remains alive.
                    self.check()
                    return self
                except OSError:
                    time.sleep(0.05)
            raise RuntimeError("Timeout del broker aislado")
        except BaseException:
            self.stack.close()
            raise

    def check(self):
        if (self.host != "127.0.0.1" or self.port is None or self.port == 1883
                or self.process is None or self.process.poll() is not None):
            raise RuntimeError("Broker aislado no disponible")

    def _stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


class MqttPublisher:
    def __init__(self, broker):
        self.broker = broker
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="smartspace-replay-" + uuid.uuid4().hex,
                                  clean_session=True, protocol=mqtt.MQTTv311,
                                  reconnect_on_failure=False)
        self.connected = threading.Event()
        self.failed = threading.Event()
        self.closing = False
        self.client.on_connect = self._connected
        self.client.on_disconnect = self._disconnected

    def _connected(self, client, userdata, flags, reason, properties):
        if reason == 0:
            self.connected.set()
        else:
            self.failed.set()

    def _disconnected(self, client, userdata, flags, reason, properties):
        self.connected.clear()
        if not self.closing:
            self.failed.set()

    def __enter__(self):
        try:
            self.broker.check()
            self.client.username_pw_set(self.broker.username, self.broker.password)
            self.client.connect_timeout = 3
            self.client.connect(self.broker.host, self.broker.port, keepalive=30)
            self.client.loop_start()
            if not self.connected.wait(5) or self.failed.is_set():
                raise RuntimeError("No se confirmó la conexión MQTT aislada")
            self.broker.check()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def check(self):
        self.broker.check()
        if self.failed.is_set() or not self.connected.is_set():
            raise RuntimeError("La conexión MQTT de reproducción se ha perdido")

    def publish(self, topic, payload, *, qos, retain=False):
        if topic not in ALL_TELEMETRY_TOPICS or retain is not False or type(qos) is not int or qos != 1:
            raise ValueError("Publicación no permitida")
        self.check()
        info = self.client.publish(topic, payload, qos=qos, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError("Publicación MQTT rechazada")
        info.wait_for_publish(timeout=5)
        if not info.is_published() or self.failed.is_set():
            raise RuntimeError("Publicación MQTT sin confirmar")

    def __exit__(self, *exc):
        self.closing = True
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
