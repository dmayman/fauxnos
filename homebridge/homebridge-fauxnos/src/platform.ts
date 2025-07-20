import type { API, Characteristic, DynamicPlatformPlugin, Logging, PlatformAccessory, PlatformConfig, Service } from 'homebridge';

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
   * This is an example method showing how to register discovered accessories.
   * Accessories must only be registered once, previously created accessories
   * must not be registered again to prevent "duplicate UUID" errors.
   */
  discoverDevices() {
    this.log.info('[FAUXNOS] Discovering audio devices...');

    // TESTING MODE: Remove ALL cached accessories first
    const TESTING_MODE = true;
    if (TESTING_MODE) {
      this.log.info('[FAUXNOS] TESTING MODE: Removing all cached accessories...');
      for (const [uuid, accessory] of this.accessories) {
        this.log.info('[FAUXNOS] Removing cached accessory:', accessory.displayName);
        this.api.unregisterPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, [accessory]);
      }
      // Clear the accessories map
      this.accessories.clear();
      this.log.info('[FAUXNOS] All cached accessories removed');
    }

    // Hardcoded fauxnos audio devices for testing
    const exampleDevices = [
      {
        exampleUniqueId: 'FAUXNOS-005',
        exampleDisplayName: 'Fauxnos Test 05',
      },
      {
        exampleUniqueId: 'FAUXNOS-006',
        exampleDisplayName: 'Fauxnos Test 06',
      },
    ];

    // loop over the discovered devices and register each one if it has not already been registered
    for (const device of exampleDevices) {
      // generate a unique id for the accessory this should be generated from
      // something globally unique, but constant, for example, the device serial
      // number or MAC address
      const uuid = this.api.hap.uuid.generate(device.exampleUniqueId);

      // see if an accessory with the same uuid has already been registered and restored from
      // the cached devices we stored in the `configureAccessory` method above
      const existingAccessory = this.accessories.get(uuid);

      // In testing mode, all accessories were already removed, so just create new ones
      if (existingAccessory && !TESTING_MODE) {
        // the accessory already exists (normal mode)
        this.log.info('[FAUXNOS] Restoring existing accessory:', existingAccessory.displayName);

        // if you need to update the accessory.context then you should run `api.updatePlatformAccessories`. e.g.:
        // existingAccessory.context.device = device;
        // this.api.updatePlatformAccessories([existingAccessory]);

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
        this.log.info('[FAUXNOS] Adding new accessory:', device.exampleDisplayName);

        // create a new accessory
        const accessory = new this.api.platformAccessory(device.exampleDisplayName, uuid);

        // store a copy of the device object in the `accessory.context`
        // the `context` property can be used to store any data about the accessory you may need
        accessory.context.device = device;

        // create the accessory handler for the newly create accessory
        // this is imported from `platformAccessory.ts`
        try {
          new FauxnosPlatformAccessory(this, accessory);
        } catch (error) {
          this.log.error('[FAUXNOS] Failed to create accessory handler for', device.exampleDisplayName, ':', error);
        }

        // register as platform accessory
        try {
          this.api.registerPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, [accessory]);
          this.log.info('[FAUXNOS] Registered platform accessory:', device.exampleDisplayName);
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
