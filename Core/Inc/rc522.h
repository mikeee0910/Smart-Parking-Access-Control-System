/*
 * rc522.h
 *
 *  Created on: May 9, 2026
 *      Author: USER
 */

#ifndef INC_RC522_H_
#define INC_RC522_H_

#include "main.h"
#include <stdint.h>

/* RC522 Status */
#define MI_OK             0
#define MI_NOTAGERR       1
#define MI_ERR            2

/* PICC Commands */
#define PICC_REQIDL       0x26
#define PICC_ANTICOLL     0x93

/* RC522 Registers that main may need */
#define VersionReg        0x37
#define TxControlReg      0x14

void RC522_Init(void);
uint8_t RC522_Request(uint8_t reqMode, uint8_t *tagType);
uint8_t RC522_Anticoll(uint8_t *serNum);

uint8_t RC522_ReadReg(uint8_t reg);
void RC522_WriteReg(uint8_t reg, uint8_t value);

void RC522_AntennaOn(void);

#endif /* INC_RC522_H_ */
