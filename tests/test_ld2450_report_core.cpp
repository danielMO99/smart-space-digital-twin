// Compile-time tests execute the exact policy used by the ESP32, without hardware.
#include "../firmware/ld2450_report_core.h"
using namespace smartspace;
constexpr float unknown = std::numeric_limits<float>::quiet_NaN();
constexpr RawSlot absent{unknown, unknown, unknown, unknown};
constexpr RawSlot one{-782, 1713, -160, 320};
constexpr RawSlot two{0, 1800, 0, 320};
constexpr RawSlot three{800, 1600, 80, 320};
static_assert(classify(absent) == 0);
static_assert(classify(one) == 1 && classify(two) == 1);
static_assert(valid({absent, absent, absent}));
static_assert(valid({one, absent, absent}));
static_assert(valid({one, absent, three}));
static_assert(valid({one, two, three}));
static_assert(!valid({RawSlot{unknown, 1, 0, 320}, absent, absent}));
static_assert(classify({0, 0, 0, 320}) == -1);
static_assert(classify({1, 1, std::numeric_limits<float>::infinity(), 320}) == -1);
static_assert(classify({1, 1, 0, -1}) == -1);
static_assert(classify({1.5, 1, 0, 320}) == -1);
constexpr bool lifecycle() {
  Selection s;
  if (s.seq != 0 || s.selected != 0) return false; // silence: no call, no frame
  if (!s.accept(100, 0, true, true) || !s.accept(100, 0, true, true)) return false; // duplicates retained
  if (s.accept(200, 0, false, true) || s.invalid != 1) return false;
  if (s.accept(300, 0, true, false) || s.offline != 1) return false;
  if (!s.accept(301, 1000, true, true)) return false; // fresh after reconnect
  if (s.accept(1300, 1000, true, true) || !s.accept(1301, 1000, true, true)) return false;
  if (s.seq != 7 || s.selected != 4 || s.decimated != 1) return false;
  s = {}; // new boot resets policy
  if (!s.accept((uint64_t{1} << 32) - 1, 100, true, true)) return false;
  if (!s.accept((uint64_t{1} << 32) + 99, 100, true, true)) return false;
  s.seq = UINT64_MAX - 1;
  if (!s.accept((uint64_t{1} << 32) + 199, 0, true, true) || !s.exhausted()) return false;
  s = {}; // Reporter rotates boot_id before the next accept, never wraps seq
  return s.seq == 0 && !s.exhausted();
}
static_assert(lifecycle());
