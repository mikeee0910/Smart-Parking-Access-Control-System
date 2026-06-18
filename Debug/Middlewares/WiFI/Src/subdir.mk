################################################################################
# Automatically-generated file. Do not edit!
# Toolchain: GNU Tools for STM32 (13.3.rel1)
################################################################################

# Add inputs and outputs from these tool invocations to the build variables 
C_SRCS += \
../Middlewares/WiFI/Src/es_wifi.c \
../Middlewares/WiFI/Src/es_wifi_io.c \
../Middlewares/WiFI/Src/wifi.c 

OBJS += \
./Middlewares/WiFI/Src/es_wifi.o \
./Middlewares/WiFI/Src/es_wifi_io.o \
./Middlewares/WiFI/Src/wifi.o 

C_DEPS += \
./Middlewares/WiFI/Src/es_wifi.d \
./Middlewares/WiFI/Src/es_wifi_io.d \
./Middlewares/WiFI/Src/wifi.d 


# Each subdirectory must supply rules for building sources it contributes
Middlewares/WiFI/Src/%.o Middlewares/WiFI/Src/%.su Middlewares/WiFI/Src/%.cyclo: ../Middlewares/WiFI/Src/%.c Middlewares/WiFI/Src/subdir.mk
	arm-none-eabi-gcc "$<" -mcpu=cortex-m4 -std=gnu11 -g3 -DDEBUG -DUSE_HAL_DRIVER -DSTM32L475xx -c -I../Core/Inc -I../Drivers/STM32L4xx_HAL_Driver/Inc -I../Drivers/STM32L4xx_HAL_Driver/Inc/Legacy -I../Drivers/CMSIS/Device/ST/STM32L4xx/Include -I../Drivers/CMSIS/Include -I../Middlewares/WiFi/Inc -I../Middlewares/Third_Party/FreeRTOS/Source/include -I../Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2 -I../Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F -O0 -ffunction-sections -fdata-sections -Wall -fstack-usage -fcyclomatic-complexity -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" --specs=nano.specs -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb -o "$@"

clean: clean-Middlewares-2f-WiFI-2f-Src

clean-Middlewares-2f-WiFI-2f-Src:
	-$(RM) ./Middlewares/WiFI/Src/es_wifi.cyclo ./Middlewares/WiFI/Src/es_wifi.d ./Middlewares/WiFI/Src/es_wifi.o ./Middlewares/WiFI/Src/es_wifi.su ./Middlewares/WiFI/Src/es_wifi_io.cyclo ./Middlewares/WiFI/Src/es_wifi_io.d ./Middlewares/WiFI/Src/es_wifi_io.o ./Middlewares/WiFI/Src/es_wifi_io.su ./Middlewares/WiFI/Src/wifi.cyclo ./Middlewares/WiFI/Src/wifi.d ./Middlewares/WiFI/Src/wifi.o ./Middlewares/WiFI/Src/wifi.su

.PHONY: clean-Middlewares-2f-WiFI-2f-Src

