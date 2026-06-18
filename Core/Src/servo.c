/*
 * servo.c
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */
#include "servo.h"
#include "cmsis_os.h"
#include <stdio.h>

extern TIM_HandleTypeDef htim2;

#define SERVO_TIMER      htim2
#define SERVO_CHANNEL    TIM_CHANNEL_1

#define SERVO_STOP_US    1500
#define SERVO_UNLOCK_US  1760   /* open: speed = |pulse - 1500| = 200 */
#define SERVO_LOCK_US    1230   /* close: speed = |pulse - 1500| = 200 (same as open) */

/* Same rotation time for both open and close (continuous-rotation servo). */
#define SERVO_RUN_MS     1500

/* Current door state, tracked in software so a repeated command does not
 * drive the motor again. 1 = locked, 0 = unlocked. Assumed locked at boot. */
static volatile uint8_t s_locked = 1;

static void Servo_SetPulse(uint16_t pulse_us)
{
    __HAL_TIM_SET_COMPARE(&SERVO_TIMER, SERVO_CHANNEL, pulse_us);
}

/* Drive the servo in one direction for a fixed time, then stop. */
static void Servo_RunForMs(uint16_t pulse_us, uint32_t ms)
{
    Servo_SetPulse(pulse_us);
    osDelay(ms);
    Servo_Stop();
}

void Servo_Init(void)
{
    HAL_TIM_PWM_Start(&SERVO_TIMER, SERVO_CHANNEL);
    Servo_Stop();
}

void Servo_Stop(void)
{
    Servo_SetPulse(SERVO_STOP_US);
}

void Servo_UnlockSequence(void)
{
    Servo_UnlockOnly();
    osDelay(4000);
    Servo_LockOnly();
}

int Servo_UnlockOnly(void)
{
    if (!s_locked) {
        printf("Servo: already unlocked, skip\r\n");
        return 0;
    }
    printf("Servo: unlocking...\r\n");
    Servo_RunForMs(SERVO_UNLOCK_US, SERVO_RUN_MS);
    s_locked = 0;
    printf("Servo: unlocked\r\n");
    return 0;
}

int Servo_LockOnly(void)
{
    if (s_locked) {
        printf("Servo: already locked, skip\r\n");
        return 0;
    }
    printf("Servo: locking...\r\n");
    Servo_RunForMs(SERVO_LOCK_US, SERVO_RUN_MS);
    s_locked = 1;
    printf("Servo: locked\r\n");
    return 0;
}

int Servo_IsLocked(void)
{
    return s_locked;
}
