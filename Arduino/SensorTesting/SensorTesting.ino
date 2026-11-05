#include "Robot.h"
#include "SensorExperiment.h"

Robot_c robot;
SensorExperiment_c experiment;

void setup() {
  Serial.begin(115200);
  robot.initialise();
  robot.setMotorPWM(0, 0);
  Serial.println("#READY,1,LAB,UNSET");
}

void loop() {
  experiment.poll(robot);
  experiment.update(robot);
}
