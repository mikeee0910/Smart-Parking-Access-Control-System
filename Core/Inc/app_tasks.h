#ifndef INC_APP_TASKS_H_
#define INC_APP_TASKS_H_

#include "cmsis_os.h"

extern osMessageQueueId_t wifiEventQueueHandle;
extern osMutexId_t        doorMutexHandle;
extern uint8_t            door_locked;

void RFIDTask_Entry(void *argument);
void ButtonTask_Entry(void *argument);
void WiFiTask_Entry(void *argument);

#endif /* INC_APP_TASKS_H_ */
