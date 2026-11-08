import type { AndroidSession } from '../model';
import { createDeviceScreen } from './deviceSessionView';

export const createAndroidScreen = (s: AndroidSession, interactive: boolean) => createDeviceScreen(s, interactive);
