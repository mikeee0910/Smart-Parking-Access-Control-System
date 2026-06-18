/*
 * rc522.c
 *
 *  Created on: May 9, 2026
 *      Author: USER
 */

#include "rc522.h"

/* External SPI handle from main.c */
extern SPI_HandleTypeDef hspi1;

/* CS / RST control */
#define RC522_CS_LOW()    HAL_GPIO_WritePin(GPIOA, RC522_CS_Pin, GPIO_PIN_RESET)
#define RC522_CS_HIGH()   HAL_GPIO_WritePin(GPIOA, RC522_CS_Pin, GPIO_PIN_SET)

#define RC522_RST_LOW()   HAL_GPIO_WritePin(GPIOA, RC522_RST_Pin, GPIO_PIN_RESET)
#define RC522_RST_HIGH()  HAL_GPIO_WritePin(GPIOA, RC522_RST_Pin, GPIO_PIN_SET)

/* RC522 Registers */
#define CommandReg        0x01
#define ComIEnReg         0x02
#define DivIEnReg         0x03
#define ComIrqReg         0x04
#define DivIrqReg         0x05
#define ErrorReg          0x06
#define Status2Reg        0x08
#define FIFODataReg       0x09
#define FIFOLevelReg      0x0A
#define ControlReg        0x0C
#define BitFramingReg     0x0D
#define ModeReg           0x11
#define TxASKReg          0x15
#define TModeReg          0x2A
#define TPrescalerReg     0x2B
#define TReloadRegH       0x2C
#define TReloadRegL       0x2D

/* RC522 Commands */
#define PCD_IDLE          0x00
#define PCD_RESETPHASE    0x0F
#define PCD_AUTHENT       0x0E
#define PCD_TRANSCEIVE    0x0C

#define MAX_LEN           16

void RC522_WriteReg(uint8_t reg, uint8_t value)
{
    uint8_t data[2];

    data[0] = (reg << 1) & 0x7E;
    data[1] = value;

    RC522_CS_LOW();
    HAL_SPI_Transmit(&hspi1, data, 2, HAL_MAX_DELAY);
    RC522_CS_HIGH();
}

uint8_t RC522_ReadReg(uint8_t reg)
{
    uint8_t addr;
    uint8_t value = 0;

    addr = ((reg << 1) & 0x7E) | 0x80;

    RC522_CS_LOW();
    HAL_SPI_Transmit(&hspi1, &addr, 1, HAL_MAX_DELAY);
    HAL_SPI_Receive(&hspi1, &value, 1, HAL_MAX_DELAY);
    RC522_CS_HIGH();

    return value;
}

static void RC522_SetBitMask(uint8_t reg, uint8_t mask)
{
    uint8_t tmp = RC522_ReadReg(reg);
    RC522_WriteReg(reg, tmp | mask);
}

static void RC522_ClearBitMask(uint8_t reg, uint8_t mask)
{
    uint8_t tmp = RC522_ReadReg(reg);
    RC522_WriteReg(reg, tmp & (~mask));
}

static void RC522_HardReset(void)
{
    RC522_RST_LOW();
    HAL_Delay(50);
    RC522_RST_HIGH();
    HAL_Delay(50);
}

void RC522_AntennaOn(void)
{
    uint8_t temp = RC522_ReadReg(TxControlReg);

    if ((temp & 0x03) != 0x03)
    {
        RC522_SetBitMask(TxControlReg, 0x03);
    }
}

void RC522_Init(void)
{
    RC522_HardReset();

    RC522_WriteReg(CommandReg, PCD_RESETPHASE);
    HAL_Delay(50);

    RC522_WriteReg(TModeReg, 0x8D);
    RC522_WriteReg(TPrescalerReg, 0x3E);
    RC522_WriteReg(TReloadRegL, 30);
    RC522_WriteReg(TReloadRegH, 0);

    RC522_WriteReg(TxASKReg, 0x40);
    RC522_WriteReg(ModeReg, 0x3D);

    RC522_AntennaOn();
}

static uint8_t RC522_ToCard(uint8_t command, uint8_t *sendData, uint8_t sendLen,
                            uint8_t *backData, uint16_t *backLen)
{
    uint8_t status = MI_ERR;
    uint8_t irqEn = 0x00;
    uint8_t waitIRq = 0x00;
    uint8_t lastBits;
    uint8_t n;
    uint16_t i;

    if (command == PCD_AUTHENT)
    {
        irqEn = 0x12;
        waitIRq = 0x10;
    }
    else if (command == PCD_TRANSCEIVE)
    {
        irqEn = 0x77;
        waitIRq = 0x30;
    }

    RC522_WriteReg(ComIEnReg, irqEn | 0x80);
    RC522_ClearBitMask(ComIrqReg, 0x80);
    RC522_SetBitMask(FIFOLevelReg, 0x80);

    RC522_WriteReg(CommandReg, PCD_IDLE);

    for (i = 0; i < sendLen; i++)
    {
        RC522_WriteReg(FIFODataReg, sendData[i]);
    }

    RC522_WriteReg(CommandReg, command);

    if (command == PCD_TRANSCEIVE)
    {
        RC522_SetBitMask(BitFramingReg, 0x80);
    }

    i = 2000;

    do
    {
        n = RC522_ReadReg(ComIrqReg);
        i--;
    }
    while ((i != 0) && !(n & 0x01) && !(n & waitIRq));

    RC522_ClearBitMask(BitFramingReg, 0x80);

    if (i != 0)
    {
        if (!(RC522_ReadReg(ErrorReg) & 0x1B))
        {
            status = MI_OK;

            if (n & irqEn & 0x01)
            {
                status = MI_NOTAGERR;
            }

            if (command == PCD_TRANSCEIVE)
            {
                n = RC522_ReadReg(FIFOLevelReg);
                lastBits = RC522_ReadReg(ControlReg) & 0x07;

                if (lastBits)
                {
                    *backLen = (n - 1) * 8 + lastBits;
                }
                else
                {
                    *backLen = n * 8;
                }

                if (n == 0)
                {
                    n = 1;
                }

                if (n > MAX_LEN)
                {
                    n = MAX_LEN;
                }

                for (i = 0; i < n; i++)
                {
                    backData[i] = RC522_ReadReg(FIFODataReg);
                }
            }
        }
        else
        {
            status = MI_ERR;
        }
    }

    return status;
}

uint8_t RC522_Request(uint8_t reqMode, uint8_t *tagType)
{
    uint8_t status;
    uint16_t backBits;

    RC522_WriteReg(BitFramingReg, 0x07);

    tagType[0] = reqMode;

    status = RC522_ToCard(PCD_TRANSCEIVE, tagType, 1, tagType, &backBits);

    if ((status != MI_OK) || (backBits != 0x10))
    {
        status = MI_ERR;
    }

    return status;
}

uint8_t RC522_Anticoll(uint8_t *serNum)
{
    uint8_t status;
    uint8_t i;
    uint8_t serNumCheck = 0;
    uint16_t unLen;

    RC522_WriteReg(BitFramingReg, 0x00);

    serNum[0] = PICC_ANTICOLL;
    serNum[1] = 0x20;

    status = RC522_ToCard(PCD_TRANSCEIVE, serNum, 2, serNum, &unLen);

    if (status == MI_OK)
    {
        for (i = 0; i < 4; i++)
        {
            serNumCheck ^= serNum[i];
        }

        if (serNumCheck != serNum[4])
        {
            status = MI_ERR;
        }
    }

    return status;
}

