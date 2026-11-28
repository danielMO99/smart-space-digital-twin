#pragma once
#include <array>
#include <cstdint>
#include <limits>

namespace smartspace {
struct RawSlot { float x, y, speed, resolution; };
// 0: component reports absent/unknown; 1: usable; -1: inconsistent/invalid.
constexpr int classify(const RawSlot &s) {
  const bool nx = s.x != s.x, ny = s.y != s.y;
  const bool ns = s.speed != s.speed, nr = s.resolution != s.resolution;
  if (nx && ny && ns && nr) return 0;
  if (nx || ny || ns || nr) return -1;
  if (!(s.x >= -32767 && s.x <= 32767 && s.y >= -32767 && s.y <= 32767 &&
        s.speed >= -32768 && s.speed <= 32767 && s.resolution >= 0 && s.resolution <= 32767)) return -1;
  if (s.x != static_cast<int>(s.x) || s.y != static_cast<int>(s.y) ||
      s.speed != static_cast<int>(s.speed) || s.resolution != static_cast<int>(s.resolution)) return -1;
  return (s.x == 0 && s.y == 0) ? -1 : 1;
}
constexpr bool valid(const std::array<RawSlot, 3> &slots) {
  for (const auto &s : slots) if (classify(s) < 0) return false;
  return true;
}
struct Selection {
  uint64_t seq = 0, selected = 0, invalid = 0, offline = 0, decimated = 0;
  uint64_t last_selected_us = 0;
  bool has_selected = false;
  // Caller starts a fresh boot_id before uint64 sequence overflow.
  constexpr bool exhausted() const { return seq == UINT64_MAX; }
  constexpr bool accept(uint64_t now, uint64_t interval, bool usable, bool connected) {
    ++seq;
    if (!usable) { ++invalid; return false; }
    if (!connected) { ++offline; has_selected = false; return false; }
    if (has_selected && now >= last_selected_us && now - last_selected_us < interval) {
      ++decimated; return false;
    }
    last_selected_us = now;
    has_selected = true;
    ++selected;
    return true;
  }
};
}  // namespace smartspace
