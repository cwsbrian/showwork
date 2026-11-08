import type { IosSession } from '../model';
import { createDeviceScreen } from './deviceSessionView';

export const createIosScreen = (s: IosSession, interactive: boolean) => createDeviceScreen(s, interactive);
