#ifndef __ES_WIFI_CONF_H
#define __ES_WIFI_CONF_H

#ifdef __cplusplus
 extern "C" {
#endif

#define ES_WIFI_MAX_SSID_NAME_SIZE                  32
#define ES_WIFI_MAX_PSWD_NAME_SIZE                  32
#define ES_WIFI_PRODUCT_ID_SIZE                     32
#define ES_WIFI_PRODUCT_NAME_SIZE                   32
#define ES_WIFI_FW_REV_SIZE                         24
#define ES_WIFI_API_REV_SIZE                        16
#define ES_WIFI_STACK_REV_SIZE                      16
#define ES_WIFI_RTOS_REV_SIZE                       16

#define ES_WIFI_DATA_SIZE                           1400
#define ES_WIFI_MAX_DETECTED_AP                     10

#define ES_WIFI_TIMEOUT                             0xFFFF

#define ES_WIFI_USE_PING                            1
#define ES_WIFI_USE_AWS                             0
#define ES_WIFI_USE_FIRMWAREUPDATE                  0
#define ES_WIFI_USE_WPS                             0

#define ES_WIFI_USE_SPI                             1
#define ES_WIFI_USE_UART                            (!ES_WIFI_USE_SPI)

#define SPI_INTERFACE_PRIO                          5

#define LOCK_SPI()
#define LOCK_WIFI()
#define UNLOCK_SPI()
#define UNLOCK_WIFI()
#define SEM_SIGNAL(a)

#ifdef __cplusplus
}
#endif
#endif /* __ES_WIFI_CONF_H */
