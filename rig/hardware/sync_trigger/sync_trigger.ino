// mouse-project — camera hardware trigger for Arduino UNO / Nano (ATmega328P)
//
// Sends one rising edge to every camera at the same instant, FPS times per second.
// The cameras must be in trigger mode (recorder.yaml: trigger: "line0").
//
// Wiring (Hikrobot 6-pin IO cable MV-ACC-01-2101; check the colours on your cable):
//   D9  -> cam-1 Line0+ (pin 2, yellow)      D10 -> cam-2 Line0+ (pin 2, yellow)
//   D11 -> cam-3 Line0+ (pin 2, yellow)      D12 -> cam-4 Line0+ (pin 2, yellow)
//   GND -> Line0- (pin 5, green) of EVERY camera
// Each camera has its own output pin, so no pin drives more than one camera.
// D9..D12 are bits PB1..PB4 of PORTB: one register write switches all four
// together (skew < 1 microsecond). The on-board LED (D13) toggles once per second.
//
// Serial Monitor at 115200 baud, line ending "Newline":
//   a number 1..200 -> set FPS      s -> stop pulses      r -> run      ? -> status

const uint8_t TRIG_MASK = _BV(1) | _BV(2) | _BV(3) | _BV(4);  // D9, D10, D11, D12
const uint8_t LED_BIT = _BV(5);                               // D13 (on-board LED)
const unsigned long PULSE_US = 1000;                          // 1 ms high pulse

unsigned long fps = 60;          // default frame rate; must match recorder.yaml fps
unsigned long periodUs = 1000000UL / 60;
unsigned long nextUs = 0;
unsigned long pulses = 0;
bool running = true;

void printStatus() {
  Serial.print(F("fps="));
  Serial.print(fps);
  Serial.print(F(" running="));
  Serial.print(running ? F("yes") : F("no"));
  Serial.print(F(" pulses="));
  Serial.println(pulses);
}

void handleSerial() {
  static char buf[8];
  static uint8_t n = 0;
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (n == 0) continue;
      buf[n] = '\0';
      n = 0;
      if (buf[0] == 's') {
        running = false;
      } else if (buf[0] == 'r') {
        running = true;
        nextUs = micros();
      } else if (buf[0] != '?') {
        long v = atol(buf);
        if (v >= 1 && v <= 200) {
          fps = (unsigned long)v;
          periodUs = 1000000UL / fps;
          nextUs = micros();
        } else {
          Serial.println(F("FPS must be 1..200"));
        }
      }
      printStatus();
    } else if (n < sizeof(buf) - 1) {
      buf[n++] = c;
    }
  }
}

void setup() {
  DDRB |= TRIG_MASK | LED_BIT;     // outputs
  PORTB &= ~(TRIG_MASK | LED_BIT);  // all low
  Serial.begin(115200);
  Serial.println(F("mouse-project trigger ready"));
  printStatus();
  nextUs = micros();
}

void loop() {
  handleSerial();
  if (!running) return;
  if ((long)(micros() - nextUs) < 0) return;  // overflow-safe wait for the next frame
  PORTB |= TRIG_MASK;                          // rising edge on all cameras at once
  delayMicroseconds(PULSE_US);
  PORTB &= ~TRIG_MASK;
  nextUs += periodUs;
  pulses++;
  if (pulses % fps == 0) PORTB ^= LED_BIT;     // heartbeat: LED changes once per second
}
