#include "SensorExperiment.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

namespace {
bool number(const char *s, uint32_t &value, uint32_t low, uint32_t high) {
  if (!s || !*s) return false;
  for (const char *p = s; *p; ++p) if (!isdigit((unsigned char)*p)) return false;
  char *end;
  unsigned long n = strtoul(s, &end, 10);
  if (*end || n < low || n > high) return false;
  value = (uint32_t)n;
  return true;
}
}

void SensorExperiment_c::finish(const char *reason) {
  Serial.printf("#END,%s,%s,%lu,%lu,%lu,%lu\n", run_id, reason,
    (unsigned long)samples, (unsigned long)failures,
    (unsigned long)duplicates, (unsigned long)tx_skips);
  state = IDLE;
}

void SensorExperiment_c::start(Robot_c &robot) {
  if (state != ARMED) { Serial.println("#ERROR,NOT_ARMED"); return; }
  if (!robot.setMotorPWM(0, 0)) { finish("MOTOR_STOP_FAILED"); return; }
  phase_started = robot.getMillis();
  state = SETTLING;
  Serial.printf("#SETTLING,%s\n", run_id);
}

void SensorExperiment_c::execute(Robot_c &robot) {
  if (!strcmp(command, "STATUS")) {
    Serial.printf("#READY,1,%s,%s\n", "LAB", label_set ? team : "UNSET");
    return;
  }
  if (!strcmp(command, "STOP") || !strcmp(command, "MODE LAB")) {
    bool stopped = robot.setMotorPWM(0, 0);
    if (state != IDLE) finish("ABORTED");
    state = IDLE;
    Serial.println(stopped ? "#ACK,STOP" : "#ERROR,MOTOR_STOP_FAILED");
    return;
  }
  if (!strncmp(command, "TEAM ", 5)) {
    if (state != IDLE) { Serial.println("#ERROR,BUSY"); return; }
    size_t n = strlen(command + 5);
    if (!n || n > 31 || strchr(command + 5, ',')) { Serial.println("#ERROR,TEAM_LENGTH_OR_COMMA"); return; }
    for (size_t i = 0; i < n; ++i) {
      unsigned char c = (unsigned char)command[5 + i];
      if (c < 32 || c > 126) { Serial.println("#ERROR,INVALID_TEAM_LABEL"); return; }
    }
    strcpy(team, command + 5);
    label_set = true;
    Serial.println("#ACK,TEAM");
    return;
  }
  if (!strncmp(command, "CONFIG ", 7)) {
    if (state != IDLE && state != CONFIGURED) { Serial.println("#ERROR,BUSY"); return; }
    if (!label_set) { Serial.println("#ERROR,TEAM_REQUIRED"); return; }
    char *save = nullptr;
    char *id = strtok_r(command + 7, " ", &save);
    char *count = strtok_r(nullptr, " ", &save);
    char *settle = strtok_r(nullptr, " ", &save);
    char *timeout = strtok_r(nullptr, " ", &save);
    uint32_t n, wait, limit;
    bool id_ok = id && strlen(id) < sizeof(run_id);
    if (id_ok) for (char *p = id; *p; ++p)
      if (!isalnum((unsigned char)*p) && *p != '_') id_ok = false;
    if (!id_ok || !number(count, n, 1, 1000000) || !number(settle, wait, 0, 60000)
        || !number(timeout, limit, 100, 3600000) || strtok_r(nullptr, " ", &save)) {
      Serial.println("#ERROR,BAD_CONFIG"); return;
    }
    strcpy(run_id, id); target = n; settle_ms = wait; timeout_ms = limit;
    samples = failures = duplicates = tx_skips = 0;
    have_timestamp = false;
    state = CONFIGURED;
    Serial.printf("#ACK,CONFIG,%s\n", run_id);
    return;
  }
  if (!strcmp(command, "ARM")) {
    if (state != CONFIGURED) { Serial.println("#ERROR,NOT_CONFIGURED"); return; }
    state = ARMED;
    Serial.printf("#ACK,ARM,%s\n", run_id);
    return;
  }
  if (!strcmp(command, "START")) { start(robot); return; }
  Serial.println("#ERROR,UNKNOWN_COMMAND");
}

void SensorExperiment_c::poll(Robot_c &robot) {
  // Bounded processing: an incomplete command never blocks the controller.
  for (unsigned int i = 0; i < 160 && Serial.available(); ++i) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      command[command_size] = 0;
      if (overflow) Serial.println("#ERROR,COMMAND_TOO_LONG");
      else if (command_size) execute(robot);
      command_size = 0; overflow = false;
    } else if (command_size + 1 < sizeof(command) && !overflow) command[command_size++] = c;
    else overflow = true;
  }
  bool down = digitalRead(3) == LOW;
  // A held button cannot restart another trial. Settling also absorbs contact bounce.
  if (down && !button_down && state == ARMED) start(robot);
  button_down = down;
}

void SensorExperiment_c::update(Robot_c &robot) {
  uint32_t now = robot.getMillis();
  if ((uint32_t)(now - cycle_started) < 10) return;
  cycle_started = now;
  if (!robot.setMotorPWM(0, 0)) {
    if (state != IDLE) finish("MOTOR_STOP_FAILED");
    return;
  }
  if (state == SETTLING && (uint32_t)(now - phase_started) >= settle_ms) {
    state = CAPTURING;
    phase_started = now;
    Serial.printf("#BEGIN,%s\n", run_id);
  }
  if (state != CAPTURING) return;
  if ((uint32_t)(now - phase_started) >= timeout_ms) { finish("TIMEOUT"); return; }
  if (!robot.getSurfaceSensors()) { ++failures; return; }
  uint32_t ts = robot.surface.timestamp_us;
  if (have_timestamp) {
    uint32_t dt = ts - last_timestamp;
    if (!dt) { ++duplicates; return; }
    // Forward modular deltas support rollover; a backwards clock aborts the run.
    if (dt >= 0x80000000UL) { finish("CLOCK_RESET"); return; }
  }
  char line[150];
  int n = snprintf(line, sizeof(line), "DATA,%s,%lu,%lu,%u,%u,%u,%u,%u\n", run_id,
    (unsigned long)(samples + 1), (unsigned long)ts,
    robot.surface.reading[0], robot.surface.reading[1], robot.surface.reading[2],
    robot.surface.reading[3], robot.surface.reading[4]);
  if (n <= 0 || (size_t)n >= sizeof(line) || Serial.availableForWrite() < n) { ++tx_skips; return; }
  if (Serial.write((const uint8_t *)line, (size_t)n) != (size_t)n) {
    finish("SERIAL_WRITE_FAILED"); return;
  }
  last_timestamp = ts; have_timestamp = true; ++samples;
  if (samples == target) finish("COMPLETE");
}
