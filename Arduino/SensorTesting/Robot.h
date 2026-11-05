#ifndef SENSOR_ROBOT_H
#define SENSOR_ROBOT_H
#include <Arduino.h>
#include <Wire.h>

#pragma pack(push, 1)
struct SurfaceSnapshot {
  uint32_t timestamp_us;
  uint16_t reading[5];
};
#pragma pack(pop)
static_assert(sizeof(SurfaceSnapshot) == 14, "Keep the robot surface packet layout");

// Surface read + motor stop only. No team, pose, encoder or geometry writes.
class Robot_c {
 public:
  SurfaceSnapshot surface = {};
  void initialise();
  uint32_t getMillis() const { return millis(); }
  bool getSurfaceSensors();
  bool setMotorPWM(float left, float right);
 private:
  static const uint8_t ADDRESS = 0x08;
  bool selectRegister(uint8_t reg);
};
#endif
