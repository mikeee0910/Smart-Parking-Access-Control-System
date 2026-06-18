#ifndef INC_APP_EVENTS_H_
#define INC_APP_EVENTS_H_

#include <stdint.h>

typedef enum {
    EVT_RFID,
    EVT_DOORBELL
} EventType_t;

typedef struct {
    EventType_t type;
    uint8_t     uid[5];
} AppEvent_t;

#endif /* INC_APP_EVENTS_H_ */
