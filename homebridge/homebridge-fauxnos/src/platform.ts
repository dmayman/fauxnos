import type { API, Characteristic, DynamicPlatformPlugin, Logging, PlatformAccessory, PlatformConfig, Service } from 'homebridge';
import * as mqtt from 'mqtt';

import { FauxnosPlatformAccessory } from './platformAccessory.js';
import { PLATFORM_NAME, PLUGIN_NAME } from './settings.js';

// This is only required when using Custom Services and Characteristics not support by HomeKit
import { EveHomeKitTypes } from 'homebridge-lib/EveHomeKitTypes';

/**
 * HomebridgePlatform
 * This class is the main constructor for your plugin, this is where you should
 * parse the user config and discover/register accessories with Homebridge.
 */
export class FauxnosPlatform implements DynamicPlatformPlugin {
  public readonly Service: typeof Service;
  public readonly Characteristic: typeof Characteristic;

  // this is used to track restored cached accessories
  public readonly accessories: Map<string, PlatformAccessory> = new Map();
  public readonly discoveredCacheUUIDs: string[] = [];

  // MQTT client for device discovery
  private mqttClient: mqtt.MqttClient | null = null;
  private discoveredDevices: Map<string, any> = new Map();
  private deviceDiscoveryTimeout: NodeJS.Timeout | null = null;
  private readonly TESTING_MODE = true; // Remove cached accessories on startup

  // This is only required when using Custom Services and Characteristics not support by HomeKit
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  public readonly CustomServices: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  public readonly CustomCharacteristics: any;

  constructor(
    public readonly log: Logging,
    public readonly config: PlatformConfig,
    public readonly api: API,
  ) {
    this.log.info('[FAUXNOS] Platform initializing...');

    this.Service = api.hap.Service;
    this.Characteristic = api.hap.Characteristic;

    // This is only required when using Custom Services and Characteristics not support by HomeKit
    try {
      this.CustomServices = new EveHomeKitTypes(this.api).Services;
      this.CustomCharacteristics = new EveHomeKitTypes(this.api).Characteristics;
    } catch (error) {
      this.log.error('[FAUXNOS] Custom services initialization failed:', error);
    }

    this.log.info('[FAUXNOS] Platform initialized successfully');

    // When this event is fired it means Homebridge has restored all cached accessories from disk.
    // Dynamic Platform plugins should only register new accessories after this event was fired,
    // in order to ensure they weren't added to homebridge already. This event can also be used
    // to start discovery of new accessories.
    this.api.on('didFinishLaunching', () => {
      this.discoverDevices();
    });
  }

  /**
   * This function is invoked when homebridge restores cached accessories from disk at startup.
   * It should be used to set up event handlers for characteristics and update respective values.
   */
  configureAccessory(accessory: PlatformAccessory) {
    // TESTING MODE: Load cached accessories so we can remove them in cleanup
    // TODO: Re-enable normal caching after testing
    this.accessories.set(accessory.UUID, accessory);

    this.log.info('[FAUXNOS] TESTING MODE: Loading cached accessory for cleanup:', accessory.displayName);
  }

  /**
   * Discover Fauxnos devices on the local network via MQTT.
   * Listens for "hello" messages from devices and registers them as HomeKit accessories.
   */
  discoverDevices() {
    this.log.info('[FAUXNOS] Starting MQTT device discovery...');

    // TESTING MODE: Remove ALL cached accessories first
    if (this.TESTING_MODE) {
      this.log.info('[FAUXNOS] TESTING MODE: Removing all cached accessories...');
      for (const [uuid, accessory] of this.accessories) {
        this.log.info('[FAUXNOS] Removing cached accessory:', accessory.displayName);
        this.api.unregisterPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, [accessory]);
      }
      // Clear the accessories map
      this.accessories.clear();
      this.log.info('[FAUXNOS] All cached accessories removed');
    }

    // Connect to MQTT broker for device discovery
    this.connectToMQTT();

    // Set discovery timeout to register devices after collecting responses
    this.deviceDiscoveryTimeout = setTimeout(() => {
      this.registerDiscoveredDevices();
    }, 5000); // Wait 5 seconds for device responses
  }

  /**
   * Connect to MQTT broker and listen for device announcements
   */
  private connectToMQTT() {
    const brokerUrl = this.config.mqttBroker || 'mqtt://localhost:1883';
    this.log.info('[FAUXNOS] Connecting to MQTT broker:', brokerUrl);

    try {
      this.mqttClient = mqtt.connect(brokerUrl);

      this.mqttClient.on('connect', () => {
        this.log.info('[FAUXNOS] Connected to MQTT broker');
        
        // Subscribe to device hello messages
        this.mqttClient!.subscribe('status/clients/+/hello', (err) => {
          if (err) {
            this.log.error('[FAUXNOS] Failed to subscribe to device hello messages:', err);
          } else {
            this.log.info('[FAUXNOS] Subscribed to device hello messages');
            
            // Request all devices to announce themselves
            this.requestDeviceDiscovery();
          }
        });
      });

      this.mqttClient.on('message', (topic, message) => {
        this.handleMqttMessage(topic, message);
      });

      this.mqttClient.on('error', (error) => {
        this.log.error('[FAUXNOS] MQTT connection error:', error);
      });

      this.mqttClient.on('close', () => {
        this.log.info('[FAUXNOS] MQTT connection closed');
      });

    } catch (error) {
      this.log.error('[FAUXNOS] Failed to connect to MQTT broker:', error);
      // Fall back to empty device list if MQTT fails
      this.registerDiscoveredDevices();
    }
  }

  /**
   * Request all Fauxnos devices to announce themselves using existing protocol
   */
  private requestDeviceDiscovery() {
    if (!this.mqttClient) return;
    
    this.log.info('[FAUXNOS] Broadcasting discovery request...');
    
    // Use a broadcast topic that all devices can listen to
    // Publish to a general status request topic
    this.mqttClient.publish('get/clients/all/status', JSON.stringify({
      requester: 'homebridge-fauxnos',
      timestamp: Date.now()
    }));
    
    this.log.info('[FAUXNOS] Sent broadcast discovery request to all devices');
  }

  /**
   * Handle incoming MQTT messages from Fauxnos devices
   */
  private handleMqttMessage(topic: string, message: Buffer) {
    try {
      // Parse topic to extract device ID
      const topicParts = topic.split('/');
      if (topicParts.length >= 4 && topicParts[0] === 'status' && topicParts[1] === 'clients' && topicParts[3] === 'hello') {
        const deviceId = topicParts[2];
        const helloData = JSON.parse(message.toString());
        
        this.log.info(`[FAUXNOS] Discovered device: ${helloData.name} (ID: ${deviceId})`);
        this.log.info(`[FAUXNOS] Device sources: ${helloData.sources?.join(', ') || 'none'}`);
        
        // Store discovered device
        this.discoveredDevices.set(deviceId, {
          id: deviceId,
          name: helloData.name || deviceId,
          displayName: helloData.name || `Fauxnos ${deviceId}`,
          sources: helloData.sources || []
        });
      }
    } catch (error) {
      this.log.error('[FAUXNOS] Error parsing MQTT message:', error);
    }
  }

  /**
   * Register all discovered devices as HomeKit accessories
   */
  private registerDiscoveredDevices() {
    this.log.info(`[FAUXNOS] Registering ${this.discoveredDevices.size} discovered devices...`);

    // Disconnect from MQTT after discovery
    if (this.mqttClient) {
      this.mqttClient.end();
      this.mqttClient = null;
    }

    // Register each discovered device as an accessory
    for (const [deviceId, device] of this.discoveredDevices) {
      // generate a unique id for the accessory using the device ID
      const uuid = this.api.hap.uuid.generate(device.id);

      // see if an accessory with the same uuid has already been registered and restored from
      // the cached devices we stored in the `configureAccessory` method above
      const existingAccessory = this.accessories.get(uuid);

      // In testing mode, all accessories were already removed, so just create new ones
      if (existingAccessory && !this.TESTING_MODE) {
        // the accessory already exists (normal mode)
        this.log.info('[FAUXNOS] Restoring existing accessory:', existingAccessory.displayName);

        // Update the accessory context with fresh device data including sources
        existingAccessory.context.device = device;
        this.api.updatePlatformAccessories([existingAccessory]);

        // create the accessory handler for the restored accessory
        // this is imported from `platformAccessory.ts`
        try {
          new FauxnosPlatformAccessory(this, existingAccessory);
        } catch (error) {
          this.log.error('[FAUXNOS] Failed to create accessory handler for', existingAccessory.displayName, ':', error);
        }
      } else {
        // Create new accessory (testing mode or no existing accessory)
        // the accessory does not yet exist, so we need to create it
        this.log.info('[FAUXNOS] Adding new accessory:', device.displayName);

        // create a new accessory
        const accessory = new this.api.platformAccessory(device.displayName, uuid);

        // store a copy of the device object in the `accessory.context`
        // the `context` property can be used to store any data about the accessory you may need
        accessory.context.device = device;

        // create the accessory handler for the newly create accessory
        // this is imported from `platformAccessory.ts`
        try {
          new FauxnosPlatformAccessory(this, accessory);
        } catch (error) {
          this.log.error('[FAUXNOS] Failed to create accessory handler for', device.displayName, ':', error);
        }

        // register as platform accessory
        try {
          this.api.registerPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, [accessory]);
          this.log.info('[FAUXNOS] Registered platform accessory:', device.displayName);
        } catch (error) {
          this.log.error('[FAUXNOS] Failed to register platform accessory:', error);
        }
        // push into discoveredCacheUUIDs
        this.discoveredCacheUUIDs.push(uuid);
      }
    }
    this.log.info('[FAUXNOS] Device discovery complete');

    // you can also deal with accessories from the cache which are no longer present by removing them from Homebridge
    // for example, if your plugin logs into a cloud account to retrieve a device list, and a user has previously removed a device
    // from this cloud account, then this device will no longer be present in the device list but will still be in the Homebridge cache
    for (const [uuid, accessory] of this.accessories) {
      if (!this.discoveredCacheUUIDs.includes(uuid)) {
        this.log.info('Removing existing accessory from cache:', accessory.displayName);
        this.api.unregisterPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, [accessory]);
      }
    }
  }
}
