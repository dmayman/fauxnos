# Homebridge MQTT Integration Plan

## Objective
Integrate the Homebridge plugin directly with MQTT to control Fauxnos audio clients, replacing hardcoded sources with dynamic MQTT-discovered devices.

## Implementation Steps

### 1. Add MQTT Client to Homebridge Plugin
- Install `mqtt` Node.js package as dependency
- Create MQTT client service class for connecting to Mosquitto broker
- Implement connection management with retry logic and error handling

### 2. Device Discovery via MQTT
- Subscribe to `status/clients/+/hello` topic to discover Fauxnos devices
- Parse device capabilities and create corresponding HomeKit accessories dynamically
- Replace hardcoded sources with MQTT-discovered device sources
- Handle device online/offline states based on MQTT activity

### 3. Real-time Status Updates
- Subscribe to device status topics (`status/clients/+/{mode,volume,activity}`)
- Update HomeKit characteristics in real-time when devices report changes
- Maintain bidirectional sync between MQTT state and HomeKit state

### 4. HomeKit Control Commands
- Implement volume control by publishing to `set/clients/{deviceId}/volume`
- Implement source switching by publishing to `set/clients/{deviceId}/mode`
- Map HomeKit lightbulb brightness to volume (0-100%)
- Map HomeKit TV input sources to audio source modes (spotify/analog/snapcast)

### 5. Configuration Management
- Add MQTT broker configuration to Homebridge plugin config
- Support custom MQTT broker host/port settings
- Add device filtering and naming customization options
- Implement proper error handling and logging

### 6. Update Plugin Structure
- Refactor `platform.ts` to use MQTT discovery instead of hardcoded devices
- Update `platformAccessory.ts` to send MQTT commands instead of local state changes
- Add MQTT service class for managing broker connections and subscriptions
- Update TypeScript types and interfaces for MQTT integration

## Benefits
- **Dynamic Discovery**: Automatically discover and manage Fauxnos devices
- **Real-time Sync**: HomeKit reflects actual device state changes
- **Scalable**: Support multiple Fauxnos devices across the network
- **Reliable**: Direct MQTT communication with proper error handling
- **Native HomeKit**: Full integration with Siri, automations, and Home app

## Testing Approach
- Use existing MQTT server script for development/testing alongside plugin
- Verify device discovery, volume control, and source switching via HomeKit
- Test multi-device scenarios and error conditions
- Validate real-time status updates and bidirectional sync

## Architecture Flow
```
HomeKit App ↔ Homebridge Plugin ↔ MQTT Broker ↔ Fauxnos Audio Clients
```

## MQTT Topics Used
- **Discovery**: `status/clients/+/hello`
- **Status Updates**: `status/clients/+/{mode,volume,activity}`
- **Control Commands**: `set/clients/{deviceId}/{volume,mode}`
- **Status Requests**: `get/clients/{deviceId}/{status,volume,activity}`

## Recommended Approach
**Direct MQTT Integration** over intermediate server script for:
- Reduced complexity and latency
- Better performance and reliability
- Real-time HomeKit updates
- Scalable multi-device support

The server script (`main.py`) remains useful for:
- Development/testing with CLI interface
- Standalone management without HomeKit
- System monitoring and debugging
- Backup control interface