/*
 * servo.h
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */

#ifndef INC_SERVO_H_
#define INC_SERVO_H_

#include "main.h"
#include <stdint.h>

void Servo_Init(void);
void Servo_Stop(void);
void Servo_UnlockSequence(void);
int  Servo_UnlockOnly(void);   /* 0=OK (no-op if already unlocked) */
int  Servo_LockOnly(void);     /* 0=OK (no-op if already locked) */
int  Servo_IsLocked(void);     /* 1=locked, 0=unlocked (software state) */

#endif /* INC_SERVO_H_ */
