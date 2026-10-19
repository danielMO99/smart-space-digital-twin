# Smart Space Digital Twin — System Requirements

**Project:** Smart Space Digital Twin  
**Version:** 0.1  
**Status:** Initial specification

## 1. Project overview

Smart Space Digital Twin is an edge-based IoT system designed to monitor physical spaces, process spatial and environmental measurements, and visualize their state through an interactive digital twin.

The system integrates an ESP32 microcontroller, an HLK-LD2450 mmWave radar, Zigbee devices and a Raspberry Pi 5 running containerized services.

The project will initially use simulated radar measurements before incorporating the physical device.

## 2. Project objectives

The main objectives are:

1. Acquire spatial information from the HLK-LD2450 radar.
2. Process radar measurements using Python on an edge server.
3. Convert radar-relative coordinates into room coordinates.
4. Visualize detected targets in a real-time 2D digital twin.
5. Integrate environmental measurements from Zigbee sensors.
6. Store historical measurements for analysis.
7. Detect occupancy events in predefined spatial zones.
8. Build a modular, reproducible and documented IoT architecture.

## 3. Physical environment

| Parameter | Initial value |
|---|---|
| Room width | 4.0 m |
| Room length | 5.0 m |
| Total area | 20 m² |
| Radar model | HLK-LD2450 |
| Radar installation | On a table |
| Radar position | X = 2.0 m, Y = 0.6 m |
| Radar height | 0.75 m (provisional) |
| Radar orientation | 0° (provisional) |

The radar position, height and orientation will be verified during hardware installation.

The room coordinate origin (0, 0) is located at the lower-left corner of the floor plan.

## 4. Hardware requirements

| Component | Function |
|---|---|
| Raspberry Pi 5 | Edge computing server |
| ESP32-WROOM-32 | Radar acquisition and Wi-Fi communication |
| HLK-LD2450 | Spatial target detection |
| Zigbee USB coordinator | Zigbee network interface |
| Zigbee temperature/humidity sensor | Environmental monitoring |
| Zigbee switch | User interaction and future automation |

The LD2450 provides measurements for up to three tracked targets. These targets are not guaranteed to correspond to uniquely identified individuals.

## 5. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Receive radar target measurements | High |
| FR-02 | Support a simulated radar data source | High |
| FR-03 | Convert coordinates to a common room reference | High |
| FR-04 | Display target positions in a 2D floor plan | High |
| FR-05 | Update the visualization in near real time | High |
| FR-06 | Support up to three radar targets | High |
| FR-07 | Integrate temperature and humidity measurements | Medium |
| FR-08 | Store time-series measurements | Medium |
| FR-09 | Define configurable spatial zones | Medium |
| FR-10 | Generate zone occupancy events | Medium |
| FR-11 | Expose system and sensor connectivity status | Medium |
| FR-12 | Integrate physical actuation | Future |

## 6. Non-functional requirements

### NFR-01 — Local operation

The system must run on the local network without depending on external cloud services.

### NFR-02 — Modularity

The firmware, messaging, backend, frontend and storage layers must be independently maintainable.

### NFR-03 — Reproducibility

The edge services should be deployable using Docker Compose and version-controlled configuration files.

### NFR-04 — Performance

The initial target is a visual update latency below one second under normal local network conditions. This is a design goal, not a validated performance guarantee.

### NFR-05 — Reliability

The system should report sensor disconnections and handle temporary communication failures.

### NFR-06 — Privacy

The system must not use cameras, facial recognition or personal identification.

### NFR-07 — Testability

The application must support simulated measurements without requiring the physical radar.

## 7. Initial validation criteria

The first software prototype will be considered successful when:

- The simulator generates valid target positions within the configured room.
- The backend receives and validates those measurements.
- The browser displays the simulated targets.
- The positions update automatically without refreshing the page.
- Invalid coordinates and disconnected data sources are handled.
- The frontend and backend work locally on a development computer.

## 8. Future improvements

Potential extensions include:

- Kalman filtering for target tracking.
- Trajectory and motion analytics.
- Advanced occupancy detection.
- Sensor fusion.
- Zigbee-based automation.
- Three.js 3D visualization.
- Energy management applications.

## 9. Current development scope

**Phase 1:** Architecture, requirements and repository configuration.

**Phase 2:** Python radar simulator, backend API and interactive 2D frontend.

**Phase 3:** Physical ESP32 and LD2450 integration.

**Phase 4:** MQTT, Zigbee, InfluxDB and Edge deployment.

**Phase 5:** Signal filtering, calibration and occupancy analysis.

**Phase 6:** Automation, testing and portfolio documentation.
