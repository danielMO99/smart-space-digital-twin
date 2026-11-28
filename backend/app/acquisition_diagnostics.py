"""Bounded acquisition diagnostics; never decides whether a measurement is accepted."""
from collections import deque
from dataclasses import asdict, dataclass
from copy import deepcopy
import math
import statistics
import time


@dataclass(frozen=True)
class DiagnosticPolicy:
    frequency_window_s: float = 10.0
    history_window_s: float = 60.0
    warmup_s: float = 10.0
    minimum_hz: float = 8.0
    integrity_threshold: int = 1
    minimum_intervals: int = 20
    capacity: int = 8192

    def __post_init__(self):
        for value in (self.frequency_window_s, self.history_window_s, self.warmup_s, self.minimum_hz):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Diagnostic thresholds must be positive and finite')
        if self.history_window_s < self.frequency_window_s:
            raise ValueError('History must cover frequency window')
        for value in (self.integrity_threshold, self.minimum_intervals, self.capacity):
            if type(value) is not int or value < 1:
                raise ValueError('Diagnostic limits must be positive integers')


class AcquisitionDiagnostics:
    def __init__(self, normalizer, *, mode='frames', source='live', clock=time.monotonic,
                 policy=None, time_basis='backend_monotonic'):
        self.normalizer = normalizer
        self.lock = normalizer.lock
        self.mode, self.source, self.clock = mode, source, clock
        self.time_basis = time_basis
        self.policy = policy or DiagnosticPolicy()
        self.started = self.observation_started = clock()
        self.events = deque(maxlen=self.policy.capacity)
        self.distributions = deque(maxlen=self.policy.capacity)
        self.history = deque(maxlen=min(self.policy.capacity, math.ceil(self.policy.history_window_s)+1))
        self.last_received = self.last_valid = None
        self.accepted = 0
        self.valid_since_connection = False
        self.previous_counters = dict(normalizer.counters)
        self.boot_id = self.last_seq = self.last_rx_us = None
        self.origin_latest = self.origin_baseline = None
        self.origin_increments = {}
        self.origin_resets = 0
        self.truncated_until = 0.0
        self.ws_configured_hz = None

    def connection_changed(self):
        with self.lock:
            # Reconnection gets a fresh observation period; lifetime counters remain.
            self.observation_started = self.clock()
            self.valid_since_connection = False

    def _prune(self, now):
        boundary = now - self.policy.history_window_s
        for buffer in (self.events, self.distributions, self.history):
            while buffer and buffer[0][0] <= boundary:
                buffer.popleft()

    def _append(self, buffer, item):
        if len(buffer) == buffer.maxlen:
            self.truncated_until = max(self.truncated_until,
                buffer[0][0] + self.policy.history_window_s)
        buffer.append(item)

    def observe(self, outcome):
        """Call once after ingest, under the same normalizer lock; no payload parsing."""
        with self.lock:
            now = self.clock()
            self._prune(now)
            self.last_received = now
            accepted = outcome == 'accepted'
            counters = self.normalizer.counters
            gaps = max(0, counters.get('missing_sequences', 0) - self.previous_counters.get('missing_sequences', 0))
            self.previous_counters = dict(counters)
            issues = int(outcome not in ('accepted', 'unexpected')) + gaps
            esp_interval = None
            if accepted:
                if not self.valid_since_connection:
                    self.observation_started = now
                self.accepted += 1
                self.valid_since_connection = True
                self.last_valid = now
                if self.mode == 'frames':
                    report = self.normalizer.report
                    diagnostics = report['diagnostics']
                    if report['boot_id'] != self.boot_id:
                        self.observation_started = now
                        self.boot_id = report['boot_id']
                        self.origin_baseline = dict(diagnostics)
                        self.origin_increments = {k: 0 for k in diagnostics if k != 'previous_callback_max_us'}
                        self.origin_resets = 0
                    else:
                        esp_interval = (report['rx_us'] - self.last_rx_us) / 1e6
                        for key in self.origin_increments:
                            delta = diagnostics[key] - self.origin_latest[key]
                            if delta < 0:
                                self.origin_resets += 1
                                issues += 1
                            else:
                                self.origin_increments[key] += delta
                                if key != 'decimated_reports':
                                    issues += delta
                    self.origin_latest = dict(diagnostics)
                    self.last_seq, self.last_rx_us = report['seq'], report['rx_us']
            self._append(self.events, (now, accepted, issues, esp_interval))

    def distributed(self):
        """One broadcast cycle, independent of subscriber count; not browser delivery."""
        with self.lock:
            now = self.clock()
            self._prune(now)
            self._append(self.distributions, (now,))

    def _rate(self, times, now):
        duration = min(self.policy.frequency_window_s, now - self.started)
        return len(times) / duration if duration > 0 else None

    def snapshot(self):
        with self.lock:
            now = self.clock()
            self._prune(now)
            if self.history and now-self.history[-1][0]>=1 and len(self.history)==self.history.maxlen:
                self.truncated_until = max(self.truncated_until, self.history[0][0]+self.policy.history_window_s)
            window = self.policy.frequency_window_s
            recent = [e for e in self.events if e[0] > now-window]
            received = [e[0] for e in recent]
            accepted = [e[0] for e in recent if e[1]]
            intervals = [b-a for a,b in zip(received, received[1:])]
            esp = [e[3] for e in recent if e[3] is not None]
            ws = [e[0] for e in self.distributions if e[0] > now-window]
            rate = self._rate(accepted, now)
            raw = self.normalizer.snapshot()
            connected = self.normalizer.connected
            age = lambda value: None if value is None else max(0.0, now-value)
            ttl = self.normalizer.ttl if self.mode == 'frames' else self.normalizer.policy.ttl
            if self.mode == 'frames':
                freshness = raw['acquisition']['telemetry_status']
            else:
                freshness = ('disconnected' if not connected else 'waiting' if not self.valid_since_connection
                             else 'stale' if age(self.last_valid) > ttl else 'fresh')
            warming = now-self.observation_started < self.policy.warmup_s
            issue_count = sum(e[2] for e in recent)
            integrity = 'issues' if issue_count >= self.policy.integrity_threshold else 'clear' if self.events else 'unknown'
            frequency = ('unavailable' if self.mode != 'frames' else 'observing' if warming
                         else 'degraded' if rate is not None and rate < self.policy.minimum_hz else 'normal')
            reasons = []
            if not connected: reasons.append('mqtt_disconnected')
            if freshness in ('waiting','stale'): reasons.append('telemetry_'+freshness)
            if integrity == 'issues': reasons.append('recent_integrity_issues')
            if now < self.truncated_until:
                reasons.append('diagnostic_window_truncated')
                frequency = 'unreliable'
            if frequency == 'degraded': reasons.append('low_acceptance_frequency')
            overall = ('disconnected' if not connected else 'stale' if freshness == 'stale'
                       else 'initializing' if freshness == 'waiting' else 'integrity_problem' if integrity == 'issues'
                       else 'diagnostic_limited' if frequency == 'unreliable'
                       else 'frequency_degraded' if frequency == 'degraded' else 'observing' if warming else 'normal')
            count = len(raw['targets']) if freshness == 'fresh' else None
            if self.mode == 'legacy' and count == 0:
                count = None  # independent legacy fields cannot confirm an empty complete report
            counters = dict(self.normalizer.counters)
            result = dict(schema_version=1, mode=self.mode, source=self.source,
                time_basis=self.time_basis, sampled_monotonic_s=now,
                policy=asdict(self.policy), overall=overall, reasons=reasons,
                mqtt=dict(connected=connected, scope='replay_consumer_to_isolated_broker'
                    if self.source == 'replay' else 'backend_consumer_to_broker', device_connectivity='not_observable'),
                source_time_reference=('recorded_esp_processing' if self.source == 'replay' else 'esp_processing')
                    if self.mode == 'frames' else None,
                freshness=dict(state=freshness, ttl_s=ttl,
                    last_received_age_s=age(self.last_received), last_valid_age_s=age(self.last_valid)),
                integrity=dict(state=integrity, recent_issue_units=issue_count, counters=counters),
                frequency=dict(state=frequency, received_hz=self._rate(received,now), accepted_hz=rate,
                    esp_processing_hz=(len(esp)/sum(esp) if esp and sum(esp)>0 else None),
                    ws_observed_hz=self._rate(ws,now), ws_configured_hz=self.ws_configured_hz,
                    interval_mean_s=statistics.mean(intervals) if intervals else None,
                    interval_stddev_s=statistics.pstdev(intervals) if len(intervals)>1 else None,
                    interval_p95_s=sorted(intervals)[math.ceil(.95*len(intervals))-1]
                        if len(intervals)>=self.policy.minimum_intervals else None,
                    interval_samples=len(intervals)),
                accepted_messages=self.accepted, current_targets=count, occupancy='unknown',
                session=dict(boot_id=self.boot_id, last_seq=self.last_seq, last_rx_us=self.last_rx_us),
                esp32=None if self.origin_latest is None else dict(accumulated=dict(self.origin_latest),
                    baseline=dict(self.origin_baseline), observed_increments=dict(self.origin_increments),
                    counter_resets=self.origin_resets),
                memory=dict(events=len(self.events), distributions=len(self.distributions),
                    capacity=self.policy.capacity, window_complete=now>=self.truncated_until))
            if not self.history or now-self.history[-1][0]>=1:
                self.history.append((now, dict(monotonic_s=now, overall=overall, freshness=freshness,
                    accepted_hz=rate, integrity=integrity, targets=count)))
            result['history'] = [deepcopy(e[1]) for e in self.history]
            return result
