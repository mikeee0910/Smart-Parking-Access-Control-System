/*
 * button.h
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */

#ifndef INC_BUTTON_H_
#define INC_BUTTON_H_

#include "main.h"
#include <stdint.h>

void Button_Init(void);
void Button_EXTI_Callback(uint16_t GPIO_Pin);
uint8_t Button_WasPressed(void);

#endif /* INC_BUTTON_H_ */
