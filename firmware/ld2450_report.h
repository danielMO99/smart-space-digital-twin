#pragma once
#include "ld2450_report_core.h"
#include "esphome/components/json/json_util.h"
#include "esphome/components/mqtt/mqtt_client.h"
#include "esp_random.h"
#include "esp_timer.h"
#include <cstdio>

namespace smartspace {
class Reporter {
 public:
  void on_data(const std::array<RawSlot, 3> &slots, esphome::mqtt::MQTTClientComponent *mqtt,
               uint64_t min_interval_us) {
    const uint64_t now = static_cast<uint64_t>(esp_timer_get_time());
    if (boot_id_[0] == 0 || selection_.exhausted() || now < last_rx_us_) new_session();
    last_rx_us_ = now;
    // slots were copied synchronously in on_data, before serialization or enqueue.
    if (!selection_.accept(now, min_interval_us, valid(slots), mqtt->is_connected())) return;
    const auto payload = esphome::json::build_json([&](JsonObject root) {
      root["schema"] = "smartspace.ld2450.frame";
      root["version"] = 1;
      root["device"] = "smartspace-esp32";
      root["boot_id"] = boot_id_;
      root["seq"] = selection_.seq;
      root["rx_us"] = now;
      root["time_reference"] = "esp_processing_monotonic";
      root["selected_seq"] = selection_.selected;
      root["min_interval_us"] = min_interval_us;
      auto targets = root["targets"].to<JsonArray>();
      auto array = root["slots"].to<JsonArray>();
      for (size_t i = 0; i < slots.size(); ++i) {
        auto out = array.add<JsonObject>();
        out["slot"] = i + 1;
        if (classify(slots[i]) == 1) {
          targets.add(i + 1);
          out["x_mm"] = static_cast<int>(slots[i].x);
          out["y_mm"] = static_cast<int>(slots[i].y);
          out["speed_mm_s"] = static_cast<int>(slots[i].speed);
          out["resolution_mm"] = static_cast<int>(slots[i].resolution);
        } else {
          out["x_mm"] = nullptr; out["y_mm"] = nullptr;
          out["speed_mm_s"] = nullptr; out["resolution_mm"] = nullptr;
        }
      }
      auto stats = root["diagnostics"].to<JsonObject>();
      stats["invalid_reports"] = selection_.invalid;
      stats["offline_reports"] = selection_.offline;
      stats["decimated_reports"] = selection_.decimated;
      stats["enqueue_failures"] = enqueue_failures_;
      stats["previous_callback_max_us"] = callback_max_us_;
    });
    // IDF asynchronous mode copies into its bounded queue; true != delivery ACK.
    if (!mqtt->publish("smartspace/esp32/radar/frame/v1", payload.c_str(), payload.size(), 0, false))
      ++enqueue_failures_;
    const uint64_t elapsed = static_cast<uint64_t>(esp_timer_get_time()) - now;
    if (elapsed > callback_max_us_) callback_max_us_ = elapsed;
  }
 private:
  void new_session() {
    uint8_t bytes[16];
    esp_fill_random(bytes, sizeof(bytes));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    char *p = boot_id_;
    for (unsigned i = 0; i < 16; ++i) {
      if (i == 4 || i == 6 || i == 8 || i == 10) *p++ = '-';
      std::snprintf(p, 3, "%02x", bytes[i]); p += 2;
    }
    selection_ = {}; enqueue_failures_ = 0; callback_max_us_ = 0;
  }
  Selection selection_;
  char boot_id_[37] = {};
  uint64_t last_rx_us_ = 0, enqueue_failures_ = 0, callback_max_us_ = 0;
};
}  // namespace smartspace
