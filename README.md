# homeassistant-intesis_modbusrtu

This repo provides Home Assistant support for Intesis Modbus RTU gateways as a `climate` platform.

In particular this has been tested with using a [Hitachi VRF systems to Modbus RTU Interface](https://www.intesis.com/products/ac-interfaces/hitachi-gateways/hitachi-modbus-vrf-hi-rc-mbs-1?ordercode=INMBSHIT001R000)

## Installation
For now this repo needs to be placed into the `custom_components/` directory. Might get around to supporting HACS at some point.

## Configuration

This integration depends on the `modbus` component, which needs to be configured alongside this one.

```yaml
# configuration.yaml
modbus:
  - name: intesis
    type: serial
    method: rtu
    port: /dev/ttyUSB1
    baudrate: 9600
    bytesize: 8
    stopbits: 2
    parity: N
    
climate:
  - platform: intesis_modbusrtu
    name: Heat Pump
    hub: intesis                    # needs to match the hub named used above
    slave: 1                        # the address of the Intesis unit
```
