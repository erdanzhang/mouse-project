// mouse-scratch-rig — camera sync trigger (M3)
//
// Emits a shared shutter pulse on pin D9 to every camera's opto-isolated
// Line0 input, so all cameras expose the same instant (hardware sync).
//
// Wiring (Hikrobot MV-CS016, 6-pin HR10A IO cable):
//   Arduino D9  -> each camera Line0+ (yellow, opto input)   [optional 1k in series]
//   Arduino GND -> each camera Line0- (green,  opto ground)
// In MVS/SDK set: Trigger Mode = On, Trigger Source = Line0.

const int TRIG_PIN   = 9;
const int FPS        = 60;     // frames per second
const int PULSE_US   = 2000;   // 2 ms high pulse

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
}

void loop() {
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(PULSE_US);
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(1000000L / FPS - PULSE_US);
}
