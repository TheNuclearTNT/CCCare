//Nov 2
//can select age and resting heart rate
//gets heart rate reading, not accurate
//takes avg (don't know if thats accurate either, haven't checked)
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DFRobot_MAX30102.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "secrets.h" // WIFI_SSID, WIFI_PASSWORD, SHEETS_URL, SHEETS_TOKEN

// Google Sheets logging
uint32_t bootId; // random per reset; tells Apps Script to start a new tab

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected" : " failed");
}

void sendToSheets(int32_t bpm) {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;

  char body[128];
  snprintf(body, sizeof(body), "{\"boot\":%lu,\"bpm\":%ld,\"token\":\"%s\"}",
           (unsigned long)bootId, (long)bpm, SHEETS_TOKEN);

  HTTPClient http;
  http.setInsecure(); // skip certificate check; the token protects the endpoint
  http.begin(SHEETS_URL);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  // Apps Script runs doPost, then answers 302 (redirect to the result). 302 = saved.
  Serial.print("Sheets HTTP ");
  Serial.println(code);
  http.end();
}
// Screen Variables
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
int potPin = A2; // Potentiometer connected to analog pin A0
int adcValue = 0; // Variable to store the ADC reading

int age;
int rest_rate;
int max_rate;
int rate_reserve;
int low_rate;
int high_rate;
int rates[4];
int rate_avg;

const int button_pin = 2;

// Create an object from the DFRobot_MAX30102 class
DFRobot_MAX30102 particleSensor; // Allows us to call methods (functions) from the class
//global variables
int32_t SPO2;
int32_t heartRate;
int8_t SPO2Valid;
int8_t heartRateValid;

uint32_t bootId;            // Google Sheets ID that create snew sheet every time the microcontroller is reset

void setup() {
  bootId = rp2040.hwrand32(); // works on the RP2350 (Pico 2 W)
  
  Serial.begin(9600); // Start serial communication at 9600 baud
  Wire.begin();
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);  
  pinMode(button_pin, INPUT);
  int button_state = digitalRead(button_pin);
  bootId = rp2040.hwrand32();
  connectWiFi();
  while (!particleSensor.begin()) { //
    Serial.println("MAX30102 not found!");
    delay(1000); // 2 sec delay before printing the message again
  }
  particleSensor.sensorConfiguration(60, SAMPLEAVG_16, MODE_MULTILED, SAMPLERATE_400, PULSEWIDTH_411, ADCRANGE_16384);
  while (button_state == LOW){
    display.clearDisplay();
    display.setCursor(5, 0);
    display.println("Press button to select age");
    adcValue = analogRead(potPin); // Read analog voltage (0–1023)
    adcValue = (adcValue / 1023.0) * 100.0;
    display.print(adcValue);
    age = adcValue;
    display.display();
    delay(100);
    button_state = digitalRead(button_pin);
  }
  delay(1000);
  button_state = digitalRead(button_pin);
  while (button_state == LOW){
    display.clearDisplay();
    display.setCursor(5, 0);
    display.println("Press button to select resting heart rate");
    adcValue = analogRead(potPin); // Read analog voltage (0–1023)
    adcValue = ((adcValue / 1023.0) * 100.0) + 30.0;
    display.print(adcValue);
    rest_rate = adcValue;
    display.display();
    delay(100);
    button_state = digitalRead(button_pin);
  }
  display.clearDisplay();
  max_rate = 220 - age;
  rate_reserve = max_rate - rest_rate;
  low_rate = 0.4 * rate_reserve + rest_rate;
  high_rate = 0.6 * rate_reserve + rest_rate;
  for (int8_t i{}; i < 4; ++i){
    rates[i] = (low_rate + high_rate)/2.0;
  }

}
void loop() {
  delay(100);
  particleSensor.heartrateAndOxygenSaturation(&SPO2, &SPO2Valid, &heartRate, &heartRateValid);
  display.clearDisplay();
  display.setCursor(5, 0);
  display.println("Current heart rate:");
  display.println(heartRate);
  display.display();
  bool goodReading = heartRateValid && heartRate >= 30 && heartRate <= 255;
  if (goodReading) {
    // only valid readings go into the average (no -999)
    for (int i{}; i < 3; ++i){
      rates[i] = rates[i +1];
    }
    rates[3] = heartRate;
  }
  rate_avg = 0;           // start each average from zero
  for (int i{}; i < 4; ++i){
    rate_avg += rates[i];
  }
  rate_avg /= 4;
  Serial.println(rate_avg);
  if (goodReading && rate_avg > 0) {
    sendToSheets(rate_avg);
  }
  if (rate_avg < low_rate){
    display.println("Heart rate too low");
    display.display();
    delay(100);
    
  } else if (rate_avg > high_rate){
    display.println("Heart rate too high");
    display.display();
    delay(100);
  }
}