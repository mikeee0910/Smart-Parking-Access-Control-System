/*
 * button.c
 *
 *  Created on: May 10, 2026
 *      Author: USER
 */
#include "button.h"

#define BUTTON_DEBOUNCE_MS 300

static volatile uint8_t button_pressed_flag = 0;
static volatile uint32_t last_button_tick = 0;

void Button_Init(void)
{
    button_pressed_flag = 0;
    last_button_tick = 0;
}

void Button_EXTI_Callback(uint16_t GPIO_Pin)
{
    if (GPIO_Pin == BUTTON_EXTI13_Pin)
    {
        uint32_t now = HAL_GetTick();

        if (now - last_button_tick > BUTTON_DEBOUNCE_MS)
        {
            button_pressed_flag = 1;
            last_button_tick = now;
        }
    }
}

uint8_t Button_WasPressed(void)
{
    if (button_pressed_flag)
    {
        button_pressed_flag = 0;
        return 1;
    }

    return 0;
}
