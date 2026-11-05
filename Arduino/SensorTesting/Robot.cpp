#include "Robot.h"

void Robot_c::initialise() {
  Wire.begin();
  Wire.setClock(400000);
  pinMode(3, INPUT_PULLUP);
}

bool Robot_c::selectRegister(uint8_t reg) {
  Wire.beginTransmission(ADDRESS);
  size_t written = Wire.write(reg);
  uint8_t status = Wire.endTransmission();
  return written == 1 && status == 0;
}

bool Robot_c::getSurfaceSensors() {
  if (!selectRegister(0x01)) return false;
  SurfaceSnapshot next;
  size_t received = Wire.requestFrom(ADDRESS, sizeof(next));
  if (received != sizeof(next)) {
    while (Wire.available()) Wire.read();
    return false;
  }
  if (Wire.readBytes((uint8_t *)&next, sizeof(next)) != sizeof(next)) return false;
  surface = next;
  return true;
}

bool Robot_c::setMotorPWM(float left, float right) {
  if (left != 0 || right != 0) return false;
  if (!selectRegister(0x06)) return false;
  const int16_t stopped[2] = {0, 0};
  Wire.beginTransmission(ADDRESS);
  size_t written = Wire.write((const uint8_t *)stopped, sizeof(stopped));
  uint8_t status = Wire.endTransmission();
  return written == sizeof(stopped) && status == 0;
}
