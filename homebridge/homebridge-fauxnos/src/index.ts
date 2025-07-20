import type { API } from 'homebridge';

import { FauxnosPlatform } from './platform.js';
import { PLATFORM_NAME } from './settings.js';

/**
 * This method registers the platform with Homebridge
 */
export default (api: API) => {
  // Note: No logger available in index.ts, using console for plugin registration only
  
  try {
    api.registerPlatform(PLATFORM_NAME, FauxnosPlatform);
  } catch (error) {
    console.error('[FAUXNOS] Platform registration FAILED:', error);
  }
};
