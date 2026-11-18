// Copy this file to secrets.h (same folder as the .ino) and fill in your values.
// secrets.h is in .gitignore so your password and token stay off GitHub.
#pragma once

#define WIFI_SSID     "your-wifi-name"
#define WIFI_PASSWORD "your-wifi-password"

// Web app URL from Deploy > Manage deployments (ends in /exec)
#define SHEETS_URL    "https://script.google.com/macros/s/XXXXXXXX/exec"

// Must match the "token" script property in Apps Script
#define SHEETS_TOKEN  "pick-a-long-random-string"
