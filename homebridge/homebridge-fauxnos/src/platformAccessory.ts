import type { CharacteristicValue, PlatformAccessory, Service } from 'homebridge';

import type { FauxnosPlatform } from './platform.js';

/**
 * Platform Accessory
 * An instance of this class is created for each accessory your platform registers
 * Each accessory may expose multiple services of different service types.
 */
export class FauxnosPlatformAccessory {
  private lightService!: Service;
  private televisionService!: Service;
  private inputSourceServices: Service[] = [];

  /**
   * Audio device states
   */
  private audioStates = {
    on: true, // lightbulb on/off (audio system on/off)
    volume: 50, // brightness = volume (0-100)
    currentSource: 0, // TV input source
  };

  private deviceSources: string[] = [];

  constructor(
    private readonly platform: FauxnosPlatform,
    private readonly accessory: PlatformAccessory,
  ) {
    this.platform.log.info('[FAUXNOS] Setting up accessory:', accessory.displayName);
    
    // Initialize device sources from MQTT discovery data
    this.deviceSources = accessory.context.device.sources || [];
    this.platform.log.info(`[FAUXNOS] Device sources: ${this.deviceSources.join(', ') || 'none'}`);
    
    // set accessory information
    try {
      this.accessory.getService(this.platform.Service.AccessoryInformation)!
        .setCharacteristic(this.platform.Characteristic.Manufacturer, 'Fauxnos')
        .setCharacteristic(this.platform.Characteristic.Model, 'Audio Controller')
        .setCharacteristic(this.platform.Characteristic.SerialNumber, accessory.context.device.id);
    } catch (error) {
      this.platform.log.error('[FAUXNOS] Failed to set accessory information:', error);
    }

    // Create TV service for source selection only (non-external) - PRIMARY SERVICE
    try {
      this.televisionService = this.accessory.getService(this.platform.Service.Television) || 
        this.accessory.addService(this.platform.Service.Television, `${accessory.context.device.displayName} Sources`, 'tv');
      
      this.televisionService
        .setCharacteristic(this.platform.Characteristic.Name, `${accessory.context.device.displayName} Sources`)
        .setCharacteristic(this.platform.Characteristic.ConfiguredName, `${accessory.context.device.displayName} Sources`)
        .setCharacteristic(this.platform.Characteristic.ActiveIdentifier, 1)
        .setCharacteristic(this.platform.Characteristic.SleepDiscoveryMode, this.platform.Characteristic.SleepDiscoveryMode.ALWAYS_DISCOVERABLE);
      
      this.platform.log.info('[FAUXNOS] TV service created successfully for source control');
    } catch (error) {
      this.platform.log.error('[FAUXNOS] Failed to create TV service:', error);
    }

    // Create Lightbulb service for volume control (brightness = volume) - SECONDARY SERVICE
    try {
      this.lightService = this.accessory.getService(this.platform.Service.Lightbulb) || 
        this.accessory.addService(this.platform.Service.Lightbulb, `${accessory.context.device.displayName} Volume`, 'volume');
      
      this.lightService
        .setCharacteristic(this.platform.Characteristic.Name, `${accessory.context.device.displayName} Volume`)
        .setCharacteristic(this.platform.Characteristic.On, true)
        .setCharacteristic(this.platform.Characteristic.Brightness, 50);
      
      this.platform.log.info('[FAUXNOS] Lightbulb service created successfully for volume control');
    } catch (error) {
      this.platform.log.error('[FAUXNOS] Failed to create Lightbulb service:', error);
    }

    // Create InputSource services for source selection using device sources
    try {
      for (let i = 0; i < this.deviceSources.length; i++) {
        const inputService = this.accessory.getService(`Source ${i}`) ||
          this.accessory.addService(this.platform.Service.InputSource, `Source ${i}`, `source${i}`);
        
        // Capitalize source name for display
        const sourceName = this.deviceSources[i].charAt(0).toUpperCase() + this.deviceSources[i].slice(1);
        
        inputService
          .setCharacteristic(this.platform.Characteristic.Name, sourceName)
          .setCharacteristic(this.platform.Characteristic.Identifier, i + 1)
          .setCharacteristic(this.platform.Characteristic.ConfiguredName, sourceName)
          .setCharacteristic(this.platform.Characteristic.IsConfigured, this.platform.Characteristic.IsConfigured.CONFIGURED)
          .setCharacteristic(this.platform.Characteristic.InputSourceType, this.platform.Characteristic.InputSourceType.OTHER);
        
        // Link input source to television
        this.televisionService.addLinkedService(inputService);
        this.inputSourceServices.push(inputService);
      }
      this.platform.log.info(`[FAUXNOS] Created ${this.deviceSources.length} InputSource services and linked successfully`);
    } catch (error) {
      this.platform.log.error('[FAUXNOS] Failed to create InputSource services:', error);
    }

    // Register handlers for Lightbulb service (volume control)
    try {
      this.lightService.getCharacteristic(this.platform.Characteristic.On)
        .onSet(this.setOn.bind(this))
        .onGet(this.getOn.bind(this));
      
      this.lightService.getCharacteristic(this.platform.Characteristic.Brightness)
        .onSet(this.setBrightness.bind(this))
        .onGet(this.getBrightness.bind(this));
      
      this.platform.log.info('[FAUXNOS] Lightbulb handlers registered successfully');
    } catch (error) {
      this.platform.log.error('[FAUXNOS] Failed to register Lightbulb service handlers:', error);
    }

    // Register handlers for TV service (source control)
    try {
      this.televisionService.getCharacteristic(this.platform.Characteristic.ActiveIdentifier)
        .onSet(this.setActiveSource.bind(this))
        .onGet(this.getActiveSource.bind(this));
      
      this.platform.log.info('[FAUXNOS] TV handlers registered successfully');
    } catch (error) {
      this.platform.log.error('[FAUXNOS] Failed to register TV service handlers:', error);
    }

    this.platform.log.info('[FAUXNOS] Accessory setup complete:', accessory.displayName);
  }

  /**
   * Handle lightbulb on/off (audio system power)
   */
  async setOn(value: CharacteristicValue) {
    this.audioStates.on = value as boolean;
    this.platform.log.info(`[${this.accessory.context.device.displayName}] Audio system power:`, value ? 'ON' : 'OFF');
  }

  async getOn(): Promise<CharacteristicValue> {
    return this.audioStates.on;
  }

  /**
   * Handle brightness (volume control)
   */
  async setBrightness(value: CharacteristicValue) {
    const volume = value as number;
    this.audioStates.volume = volume;
    this.platform.log.info(`[${this.accessory.context.device.displayName}] Volume (brightness) set to:`, volume + '%');
    
    // Send MQTT command to device
    this.platform.sendMqttCommand(this.accessory.context.device.id, 'volume', volume);
  }

  async getBrightness(): Promise<CharacteristicValue> {
    this.platform.log.debug(`[${this.accessory.context.device.displayName}] Get Volume (brightness):`, this.audioStates.volume);
    return this.audioStates.volume;
  }

  /**
   * Handle TV active state
   */
  async setTVActive(value: CharacteristicValue) {
    this.platform.log.info(`[${this.accessory.context.device.displayName}] TV active:`, value ? 'ACTIVE' : 'INACTIVE');
  }

  async getTVActive(): Promise<CharacteristicValue> {
    return true; // Always active for source selection
  }

  /**
   * Handle active source selection
   */
  async setActiveSource(value: CharacteristicValue) {
    const sourceIndex = (value as number) - 1; // Convert from 1-based to 0-based
    this.audioStates.currentSource = value as number;
    const sourceName = this.deviceSources[sourceIndex] || 'Unknown';
    this.platform.log.info(`[${this.accessory.context.device.displayName}] Active source set to:`, sourceName, `(ID: ${value})`);
    
    // Send MQTT command to device - use the actual source name, not the display index
    if (sourceName !== 'Unknown') {
      this.platform.sendMqttCommand(this.accessory.context.device.id, 'mode', sourceName);
    }
  }

  async getActiveSource(): Promise<CharacteristicValue> {
    return this.audioStates.currentSource;
  }

  /**
   * Update accessory state from MQTT status messages (bidirectional sync)
   */
  updateFromMqtt(statusType: string, value: string) {
    try {
      switch (statusType) {
        case 'volume':
          const volume = parseInt(value);
          if (!isNaN(volume) && volume !== this.audioStates.volume) {
            this.audioStates.volume = volume;
            this.lightService.updateCharacteristic(this.platform.Characteristic.Brightness, volume);
            this.platform.log.info(`[${this.accessory.context.device.displayName}] Volume updated from MQTT: ${volume}%`);
          }
          break;
          
        case 'mode':
          // Find the source index for the mode
          const sourceIndex = this.deviceSources.indexOf(value);
          if (sourceIndex !== -1) {
            const sourceId = sourceIndex + 1; // Convert to 1-based
            if (sourceId !== this.audioStates.currentSource) {
              this.audioStates.currentSource = sourceId;
              this.televisionService.updateCharacteristic(this.platform.Characteristic.ActiveIdentifier, sourceId);
              this.platform.log.info(`[${this.accessory.context.device.displayName}] Source updated from MQTT: ${value} (ID: ${sourceId})`);
            }
          }
          break;
          
        default:
          this.platform.log.debug(`[${this.accessory.context.device.displayName}] Unhandled MQTT status: ${statusType} -> ${value}`);
      }
    } catch (error) {
      this.platform.log.error(`[${this.accessory.context.device.displayName}] Error updating from MQTT:`, error);
    }
  }
}