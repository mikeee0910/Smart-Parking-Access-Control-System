# Smart Doorbell + RFID Access Control System — System Logic

## Hardware

| Component | Interface | Pin |
|-----------|-----------|-----|
| RC522 RFID Reader | SPI1 | CS=PA3, RST=PA4 |
| SG90 360 Servo (continuous rotation) | TIM2 CH1 PWM | PA15 |
| Doorbell Button | GPIO EXTI | PC13 |
| ISM43362 WiFi Module | SPI3 | (board internal) |
| Reed Switch (lock position sensor) | GPIO Input | PD14 (ARD_D2) |

### Reed Switch Wiring

```
3.3V ──── [Reed Switch] ──── PD14
                               │
                         Internal Pull-Down
```

- Magnet on servo shaft, reed switch fixed nearby
- Magnet near reed switch -> GPIO HIGH
- Magnet away -> GPIO LOW
- Each full rotation the magnet passes once

---

## RTOS Architecture

FreeRTOS (CMSIS_V2), 3 user tasks + 1 CubeMX default task.

### Task Overview

| Task | Stack | Priority | Cycle | Role |
|------|-------|----------|-------|------|
| RFIDTask | 512x4 | Normal | 200ms | Poll RC522 for cards |
| ButtonTask | 256x4 | Normal | 50ms | Detect doorbell press |
| WiFiTask | 1024x4 | BelowNormal | Event-driven | All HTTP + servo control |
| defaultTask | 128x4 | Normal | idle | CubeMX placeholder |

### Inter-Task Communication

```
RFIDTask ──── EVT_RFID ────┐
                            ├──→ osMessageQueue (8 slots) ──→ WiFiTask
ButtonTask ── EVT_DOORBELL ─┘
```

- `osMessageQueue`: RFIDTask/ButtonTask send events, WiFiTask receives
- `osMutex (doorMutex)`: protects shared `door_locked` variable
- WiFi SPI is NOT reentrant, all HTTP calls are serialized through WiFiTask

---

## Task Details

### RFIDTask

```
Loop:
  RC522 detect card?
    No  -> osDelay(200), continue
    Yes -> Read UID
        -> Send EVT_RFID (with UID) to queue
        -> osDelay(1000) debounce
```

Only detects cards. Does not touch WiFi or servo.

### ButtonTask

```
Loop:
  Button pressed?
    No  -> osDelay(50), continue
    Yes -> Send EVT_DOORBELL to queue
```

Only detects button press. Does not touch WiFi or servo.

### WiFiTask

```
Boot -> WiFi_HTTP_Init() (connect to AP)

Loop:
  Check queue (100ms timeout):

  [Event found]
    EVT_RFID:
      -> POST /stm32/rfid?uid=XXXXXXXX to server
      -> Server responds UNLOCK?
           Yes -> Servo_UnlockOnly()
                  -> Success: door_locked = 0
                  -> Fail (timeout): print error
           No  -> "DENY", do nothing

    EVT_DOORBELL:
      -> POST /stm32/doorbell to server
      -> Server notifies LINE user

  [No event]
    -> Long poll POST /stm32/poll (up to 25s server hold, 30s client timeout)
    -> Abort mechanism: if queue gets new event during poll,
       abort within ~350ms and go handle it

    Response from server:
      UNLOCK -> Servo_UnlockOnly()
                -> Success: door_locked=0, ACK "OK_UNLOCKED"
                -> Fail:    ACK "FAIL_UNLOCK"
      LOCK   -> Servo_LockOnly()
                -> Success: door_locked=1, ACK "OK_LOCKED"
                -> Fail:    ACK "FAIL_LOCK"
      STATUS -> ACK "LOCKED" or "UNLOCKED"
      NONE   -> Do nothing, restart loop
```

---

## Servo Control (360 Continuous Rotation + Reed Switch)

### PWM Values

| Pulse | Action |
|-------|--------|
| 1500us | Stop |
| 1700us | Rotate forward (unlock direction) |
| 1300us | Rotate reverse (lock direction) |

### Position Detection

The servo has no built-in angle feedback. A reed switch + magnet counts rotations:

```
Servo starts rotating
  -> Magnet passes reed switch (HIGH -> LOW transition) = 1 turn
  -> Magnet passes again = 2 turns
  -> count == NUM_TURNS -> Stop motor -> Success

  -> 5 seconds timeout without reaching NUM_TURNS -> Stop motor -> Fail
```

### Configuration

```c
#define NUM_TURNS        2       // lock/unlock need 2 full turns
#define SERVO_TIMEOUT_MS 5000    // max 5 seconds
```

### Unlock Flow

```
Servo_UnlockOnly():
  Set PWM to 1700us (forward)
  Wait for 2 falling edges on reed switch
    -> turn 1/2
    -> turn 2/2
  Stop motor
  Return 0 (success)
```

### Lock Flow

```
Servo_LockOnly():
  Set PWM to 1300us (reverse)
  Wait for 2 falling edges on reed switch
    -> turn 1/2
    -> turn 2/2
  Stop motor
  Return 0 (success)
```

### Timeout (motor stuck)

```
Servo_WaitTurns():
  5 seconds elapsed, only completed 1/2 turns
  Stop motor immediately
  Return -1 (fail)
  -> WiFiTask sends FAIL_UNLOCK or FAIL_LOCK to server
```

---

## Long Poll Abort Mechanism

### Problem

WiFiTask long poll blocks up to 30 seconds. If RFID/doorbell event arrives during poll, it would wait up to 30 seconds.

### Solution

During the HTTP receive loop, check if the message queue has pending events:

```
http_post_ex() receive loop:
  WIFI_ReceiveData (300ms timeout per attempt)
  No data received?
    -> Check osMessageQueueGetCount(abort_queue)
    -> If queue has items: close connection, return -3
    -> WiFiTask sees -3, goes back to check queue
```

### Result

| Scenario | Latency |
|----------|---------|
| LINE command (no abort) | Near-instant |
| RFID/doorbell during long poll | ~350ms max |

---

## HTTP Endpoints

| Endpoint | Trigger | Purpose |
|----------|---------|---------|
| POST /stm32/rfid?uid=XX | RFID card detected | Verify card, server responds UNLOCK or DENY |
| POST /stm32/doorbell | Button pressed | Notify LINE user someone is at the door |
| POST /stm32/poll | WiFiTask idle loop | Long poll for LINE commands (UNLOCK/LOCK/STATUS) |
| POST /stm32/ack?result=XX | After executing command | Report result back to server |

### ACK Results

| Result | Meaning |
|--------|---------|
| OK_UNLOCKED | Unlock command executed, servo confirmed at position |
| OK_LOCKED | Lock command executed, servo confirmed at position |
| FAIL_UNLOCK | Unlock attempted, servo did not reach position (timeout) |
| FAIL_LOCK | Lock attempted, servo did not reach position (timeout) |
| LOCKED | Status query response: door is locked |
| UNLOCKED | Status query response: door is unlocked |

---

## File Structure

| File | Role |
|------|------|
| `Core/Inc/app_events.h` | Event types (EVT_RFID, EVT_DOORBELL) and AppEvent_t struct |
| `Core/Inc/app_tasks.h` | Task entry function declarations, extern handles |
| `Core/Src/app_tasks.c` | RFIDTask, ButtonTask, WiFiTask implementations |
| `Core/Inc/servo.h` | Servo + reed switch pin definitions, function declarations |
| `Core/Src/servo.c` | Servo PWM control + reed switch rotation counting |
| `Core/Inc/wifi_http.h` | WiFi/HTTP config (SSID, server IP), function declarations |
| `Core/Src/wifi_http.c` | WiFi init, HTTP POST, long poll with abort mechanism |
| `Core/Src/main.c` | CubeMX HAL init, RTOS kernel init, task/queue/mutex creation |
| `Core/Inc/FreeRTOSConfig.h` | FreeRTOS config (heap=15360, tick=1000Hz) |
