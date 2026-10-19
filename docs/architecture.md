# Smart Space Digital Twin — System Architecture

**Version:** 0.1  
**Architecture:** Edge-based modular IoT system

## 1. Architectural overview

Smart Space Digital Twin uses a modular architecture composed of five main layers:

1. Data acquisition
2. Communication
3. Edge processing
4. Data storage and automation
5. Visualization

The main processing infrastructure runs locally on a Raspberry Pi 5.

During early software development, the backend and frontend can also run on a Windows development computer.

## 2. Data acquisition layer

### HLK-LD2450 radar

The radar detects moving or stationary targets and reports spatial information through UART.

Available measurements include:

- Target-relative X coordinate.
- Target-relative Y coordinate.
- Target speed.
- Target validity or presence information.

The device supports up to three target slots.

### ESP32

The ESP32 is responsible for:

- Communicating with the LD2450 over UART.
- Reading measurements.
- Connecting to the local Wi-Fi network.
- Publishing measurements through MQTT.

Initial firmware technology: ESPHome.

### Zigbee devices

Existing Zigbee sensors provide temperature, humidity and user interaction data.

Their integration will depend on the Zigbee software already available on the Raspberry Pi.

## 3. Communication layer

### MQTT broker

Proposed technology: Eclipse Mosquitto.

Initial MQTT topics:

| Topic | Description |
|---|---|
| `smartspace/radar/targets` | Radar measurements |
| `smartspace/environment` | Environmental measurements |
| `smartspace/system/status` | Connectivity and system status |
| `smartspace/events/occupancy` | Occupancy events |

MQTT is used for communication between data producers and edge processing services.

### Initial development mode

During Phase 2, the Python simulator will communicate with the backend using a direct software interface.

MQTT transport will be added during the integration phase.

Both simulated and real data sources should use the same measurement schema.

## 4. Edge processing layer

Technology: Python and FastAPI.

The backend is responsible for:

1. Receiving measurements.
2. Validating message structure and values.
3. Converting units.
4. Transforming radar-relative coordinates into room coordinates.
5. Checking spatial boundaries.
6. Detecting occupancy in predefined zones.
7. Managing sensor state.
8. Broadcasting processed measurements through WebSockets.
9. Writing selected historical measurements to InfluxDB.

The backend must remain independent of the frontend.

## 5. Spatial coordinate system

### Room coordinates

The room is represented using a two-dimensional Cartesian coordinate system:

- Origin: lower-left corner of the floor plan.
- X axis: horizontal, 0–4 metres.
- Y axis: vertical, 0–5 metres.

### Radar coordinates

Radar measurements are expressed relative to the device.

A rotation and translation transform converts them into room coordinates.

Radar placement parameters are stored in `config/room.json`.

The coordinate signs and physical orientation will be validated with real measurements before deployment.

## 6. Data model

### Normalized radar message

```json
{
  "schema_version": 1,
  "source": "simulator",
  "radar_id": "radar_01",
  "timestamp": "2026-10-19T17:00:00Z",
  "targets": [
    {
      "slot": 1,
      "x_mm": 1200,
      "y_mm": 2400,
      "speed_cm_s": 35
    }
  ]
}
```

The `timestamp` field uses ISO 8601 UTC notation.

Coordinates in this input message use millimetres in the radar-local reference system.

An empty `targets` array represents no valid targets.

The target slot represents a radar-reported tracking slot, not a persistent person identity.

### Processed target message

```json
{
  "schema_version": 1,
  "radar_id": "radar_01",
  "timestamp": "2026-10-19T17:00:00Z",
  "targets": [
    {
      "slot": 1,
      "x_m": 3.2,
      "y_m": 3.0,
      "speed_m_s": 0.35,
      "inside_room": true
    }
  ]
}
```

The example assumes aligned radar and room axes and the provisional radar position (2.0, 0.6) m.

Real radar conventions must be verified before applying this transformation.

## 7. Backend API

Proposed endpoints:

| Endpoint | Protocol | Purpose |
|---|---|---|
| `/health` | HTTP GET | Backend health status |
| `/api/room` | HTTP GET | Room geometry and configuration |
| `/api/state` | HTTP GET | Latest processed measurements |
| `/ws` | WebSocket | Live state updates |

Initially, the API will serve simulated measurements.

## 8. Visualization layer

Technology: HTML, CSS and JavaScript.

The frontend will display:

- Room floor plan.
- Radar position.
- Detected targets.
- Live environmental measurements.
- Zone boundaries.
- Connection status.

Future versions may include trajectories, historical events and 3D visualization.

## 9. Storage layer

Technology: InfluxDB 2.7.

Historical storage will include selected radar measurements, environmental measurements and occupancy events.

High-frequency radar data retention and downsampling policies will be decided after performance measurements.

Grafana will provide historical dashboards and analytical visualizations.

## 10. Automation layer

Technology: Node-RED.

The automation layer may consume occupancy events and environmental measurements.

Future use cases include lighting activation, notifications and energy management strategies.

## 11. Deployment

### Development environment

- Windows 11
- VSCode
- Python
- Web browser
- Git and GitHub

### Edge environment

- Raspberry Pi 5
- Docker Compose
- Mosquitto
- Python/FastAPI
- InfluxDB
- Grafana
- Node-RED

Existing Raspberry Pi services should be reused rather than duplicated.

## 12. Security and reliability

The system should:

- Operate on the local network.
- Avoid committing passwords, Wi-Fi credentials or API secrets.
- Use environment variables for service credentials.
- Restrict access to MQTT and backend services.
- Detect and report missing sensor measurements.
- Provide timestamps and source identifiers.
- Avoid treating radar target slots as individual identities.

## 13. Development strategy

The system will follow an incremental development approach.

**Stage A:** Simulated data → FastAPI → WebSocket → HTML.

**Stage B:** ESP32 + radar → MQTT → FastAPI → HTML.

**Stage C:** Zigbee + InfluxDB + Grafana + Node-RED.

**Stage D:** Calibration, filtering, events, automation and performance testing.
