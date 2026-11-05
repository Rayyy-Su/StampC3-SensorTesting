"""Execute the actual firmware with fake I2C: team labels must not change the base robot."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2] / 'Arduino' / 'SensorTesting'

class FirmwareBoundary(unittest.TestCase):
    def test_team_is_label_only_and_only_surface_read_and_stop_are_sent(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler not installed; board compile still required')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp/'Arduino.h').write_text(r'''
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <cstring>
#define LOW 0
#define INPUT_PULLUP 2
extern uint32_t fake_now;
inline uint32_t millis() { return fake_now; }
inline int digitalRead(int) { return 1; }
inline void pinMode(int,int) {}
struct FakeSerial {
 std::string input, output;
 int available() {return input.size();}
 int read() {char c=input[0];input.erase(0,1);return c;}
 int availableForWrite() {return 512;}
 void println(const char*s) {output+=s;output+='\n';}
 template<class... T> void printf(const char*f,T...v) {char b[512];snprintf(b,sizeof(b),f,v...);output+=b;}
 size_t write(const uint8_t*p,size_t n) {output.append((const char*)p,n);return n;}
};
extern FakeSerial Serial;
''')
            (tmp/'Wire.h').write_text(r'''
#pragma once
#include "Arduino.h"
struct FakeWire {
 std::vector<std::vector<uint8_t>> sent;
 std::vector<uint8_t> current;
 void begin() {}
 void setClock(int) {}
 void beginTransmission(int address) {if(address!=8) throw 1;current.clear();}
 size_t write(uint8_t byte) {current.push_back(byte);return 1;}
 size_t write(const uint8_t *p,size_t n) {current.insert(current.end(),p,p+n);return n;}
 int endTransmission() {sent.push_back(current);return 0;}
 size_t requestFrom(int,size_t n) {return n;}
 int available() {return 0;}
 int read() {return 0;}
 size_t readBytes(uint8_t*p,size_t n) {
   memset(p,0,n);uint32_t t=fake_now*1000;memcpy(p,&t,4);return n;
 }
};
extern FakeWire Wire;
''')
            (tmp/'main.cpp').write_text(r'''
#include "SensorExperiment.h"
#include <cassert>
uint32_t fake_now=0;FakeSerial Serial;FakeWire Wire;
int main() {
 Robot_c robot;SensorExperiment_c experiment;robot.initialise();
 auto send=[&](const char*s){Serial.input=std::string(s)+"\n";experiment.poll(robot);};
 send("TEAM GroupA");assert(Wire.sent.empty());assert(Serial.output.find("#ACK,TEAM")!=std::string::npos);
 send("MODE DEMO");assert(Wire.sent.empty());assert(Serial.output.find("#ERROR,UNKNOWN_COMMAND")!=std::string::npos);
 assert(!robot.setMotorPWM(1,0));assert(Wire.sent.empty());
 send("CONFIG test 2 0 1000");send("ARM");send("START");
 fake_now=10;experiment.update(robot);fake_now=20;experiment.update(robot);
 assert(Serial.output.find("#END,test,COMPLETE,2")!=std::string::npos);
 bool payload=false;
 for(const auto &frame:Wire.sent) {
   if(payload) {assert(frame.size()==4);for(uint8_t b:frame)assert(b==0);payload=false;}
   else {assert(frame.size()==1);assert(frame[0]==1 || frame[0]==6);if(frame[0]==6)payload=true;}
 }
 assert(!payload);
}
''')
            result = subprocess.run([compiler,'-std=c++11','-I',str(tmp),'-I',str(ROOT),
                            str(ROOT/'Robot.cpp'),str(ROOT/'SensorExperiment.cpp'),str(tmp/'main.cpp'),
                            '-o',str(tmp/'check')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(tmp/'check')],check=True,capture_output=True,text=True)
