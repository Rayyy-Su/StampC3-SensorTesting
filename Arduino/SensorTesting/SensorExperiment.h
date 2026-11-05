#ifndef SENSOR_EXPERIMENT_H
#define SENSOR_EXPERIMENT_H

#include "Robot.h"

// Serial protocol v1. Default mode is LAB; all surface experiments keep motors off.
// Printing raw DATA snapshots is shared by every chapter; Python owns the labels.
class SensorExperiment_c {
 public:
  void poll(Robot_c &robot);
  void update(Robot_c &robot);

 private:
  enum State { IDLE, CONFIGURED, ARMED, SETTLING, CAPTURING };
  State state = IDLE;
  bool label_set = false;
  bool button_down = false;
  bool have_timestamp = false;
  bool overflow = false;
  char command[160] = {};
  size_t command_size = 0;
  char run_id[40] = {};
  char team[32] = {};
  uint32_t target = 200, settle_ms = 2000, timeout_ms = 30000;
  uint32_t phase_started = 0, cycle_started = 0, last_timestamp = 0;
  uint32_t samples = 0, failures = 0, duplicates = 0, tx_skips = 0;
  void execute(Robot_c &robot);
  void start(Robot_c &robot);
  void finish(const char *reason);
};
#endif
