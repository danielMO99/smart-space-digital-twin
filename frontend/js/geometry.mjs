export function project(x, y, room) { return [x * 100, (room.length_m - y) * 100]; }
export function signedSpeed(value) { return `${value < 0 ? '−' : '+'}${Math.abs(value).toFixed(2)} m/s`; }
export function socketUrl(location) { const url = new URL('/ws', location.href); url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'; return url.href; }
export function validFrame(frame) {
  return frame?.schema_version === 1 && typeof frame.timestamp === 'string' && Number.isFinite(Date.parse(frame.timestamp)) &&
    Array.isArray(frame.targets) && frame.targets.length <= 3 && new Set(frame.targets.map(t => t?.slot)).size === frame.targets.length &&
    frame.targets.every(t => t && Number.isInteger(t.slot) && t.slot >= 1 && t.slot <= 3 &&
      [t.x_m, t.y_m, t.speed_m_s].every(Number.isFinite) && typeof t.inside_room === 'boolean');
}
