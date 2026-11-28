"""Temporal associations of independent MQTT fields, never synchronized frames."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import threading
import time
from mqtt_capture.record import TELEMETRY_TOPICS

@dataclass(frozen=True)
class Policy:
    ttl: float = 2.0
    xy_skew: float = 0.25
    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in (self.ttl,self.xy_skew)) or self.xy_skew > self.ttl:
            raise ValueError('Invalid freshness policy')

class RadarNormalizer:
    def __init__(self, policy=None, *, clock=time.monotonic, utc_now=lambda: datetime.now(timezone.utc)):
        self.policy=policy or Policy()
        self.clock,self.utc_now=clock,utc_now
        self.lock=threading.RLock()
        self.fields={s:{} for s in (1,2,3)}
        self.count=None
        self.connected=True
        self.counters=dict(received=0,invalid=0,retained=0,unexpected=0)
    def transport(self, connected):
        with self.lock:
            self.connected=connected
            if not connected:
                self.fields={s:{} for s in (1,2,3)}
                self.count=None
    def ingest(self, topic, payload, retain=False):
        with self.lock:
            self.counters['received']+=1
            if topic not in TELEMETRY_TOPICS:
                self.counters['unexpected']+=1
                return 'unexpected'
            if retain:
                self.counters['retained']+=1
                return 'retained'
            name=topic.split('/')[-2]
            is_count=name=='n__mero_de_objetivos'
            if not is_count:
                _,slot,field=name.split('_')
                fields=self.fields[int(slot)]
            try:
                text=payload.decode('utf-8').strip()
                value=int(text) if is_count else float(text)
                if not math.isfinite(value) or (is_count and not 0<=value<=3): raise ValueError()
            except (UnicodeError, ValueError, TypeError, AttributeError, OverflowError):
                self.counters['invalid']+=1
                if is_count: self.count=None
                else: fields.pop(field,None)
                return 'invalid'
            measurement=(value,self.clock())
            if is_count: self.count=measurement
            else: fields[field]=measurement
            return 'accepted'
    def snapshot(self):
        with self.lock:
            now=self.clock()
            def fresh(v): return v is not None and 0<=now-v[1]<=self.policy.ttl
            targets,rejected=[],{}
            for slot,fields in self.fields.items():
                x,y=fields.get('x'),fields.get('y')
                if not self.connected: reason='disconnected'
                elif x is None or y is None: reason='partial_or_invalid'
                elif not fresh(x) or not fresh(y): reason='expired'
                elif abs(x[1]-y[1])>self.policy.xy_skew: reason='temporal_mismatch'
                else:
                    speed=fields.get('velocidad')
                    targets.append(dict(slot=slot,x_mm=x[0],y_mm=y[0],speed_mm_s=speed[0] if fresh(speed) else None))
                    continue
                rejected[str(slot)]=reason
            count=self.count[0] if self.connected and fresh(self.count) else None
            return dict(source='ld2450',radar_id='radar_01',timestamp=self.utc_now().isoformat(),targets=targets,
                observation=dict(reported_count=count,observed_slots=len(targets),count_inconsistent=count is not None and count!=len(targets),
                    occupancy='unknown',association='temporal_not_synchronized',connected=self.connected,
                    ttl_seconds=self.policy.ttl,xy_skew_seconds=self.policy.xy_skew,rejected_slots=rejected,counters=dict(self.counters)))
