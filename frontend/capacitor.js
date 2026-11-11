/**
 * Capacitor 原生功能整合模組
 * 使用漸進式增強：Web 環境使用瀏覽器 API，iOS 原生環境使用 Capacitor API
 */

// 除錯：把 JS 錯誤回傳到後端 /debug/jslog（正式版可留著，無後端時靜默失敗）
(function () {
  function report(msg) {
    try {
      const base = (window.MeetSumConfig && window.MeetSumConfig.apiUrl)
        ? window.MeetSumConfig.apiUrl("/debug/jslog")
        : "http://localhost:8000/debug/jslog";
      fetch(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ msg: String(msg).slice(0, 2000) }),
        keepalive: true,
      }).catch(() => {});
    } catch (_) { /* 忽略 */ }
  }
  window.addEventListener("error", (e) => report("error: " + e.message + " @ " + e.filename + ":" + e.lineno + ":" + e.colno + "\n" + (e.error && e.error.stack || "")));
  window.addEventListener("unhandledrejection", (e) => report("unhandledrejection: " + ((e.reason && (e.reason.stack || e.reason.message)) || String(e.reason))));
})();

// 檢查是否在原生平台
export function isNative() {
  return window.Capacitor?.isNativePlatform() === true;
}

// 檢查特定插件是否可用
export function hasPlugin(pluginName) {
  return isNative() && window.Capacitor?.Plugins?.[pluginName] != null;
}

/**
 * 儲存鑰匙串 / Preferences
 * iOS: Keychain, Android: SharedPreferences, Web: localStorage
 */
// Preferences 在部分環境（如 PlayCover 無 App Group entitlement）可能失敗或不持久，
// 一律同時寫 localStorage 作為後備；讀取時 Preferences 優先、取不到再讀 localStorage
export async function setSecure(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (_) { /* 私密模式等情境，忽略 */ }
  if (isNative() && hasPlugin('Preferences')) {
    const { Preferences } = window.Capacitor.Plugins;
    try {
      await Preferences.set({ key, value });
    } catch (_) { /* 後備已寫入，忽略 */ }
  }
}

export async function getSecure(key) {
  if (isNative() && hasPlugin('Preferences')) {
    const { Preferences } = window.Capacitor.Plugins;
    try {
      const { value } = await Preferences.get({ key });
      if (value != null && value !== '') return value;
    } catch (_) { /* 落到 localStorage */ }
  }
  try {
    return localStorage.getItem(key);
  } catch (_) {
    return null;
  }
}

export async function removeSecure(key) {
  try {
    localStorage.removeItem(key);
  } catch (_) { /* 忽略 */ }
  if (isNative() && hasPlugin('Preferences')) {
    const { Preferences } = window.Capacitor.Plugins;
    try {
      await Preferences.remove({ key });
    } catch (_) { /* 忽略 */ }
  }
}

export async function clearSecure() {
  try {
    localStorage.clear();
  } catch (_) { /* 忽略 */ }
  if (isNative() && hasPlugin('Preferences')) {
    const { Preferences } = window.Capacitor.Plugins;
    try {
      await Preferences.clear();
    } catch (_) { /* 忽略 */ }
  }
}

/**
 * 檔案系統存取
 * iOS: Documents 目錄, Android: 外部存儲, Web: 下載
 */
export async function writeFile(path, base64Data, directory = 'Documents') {
  if (isNative() && hasPlugin('Filesystem')) {
    const { Filesystem, Directory } = window.Capacitor.Plugins;
    const dir = Directory[directory] || Directory.Documents;
    await Filesystem.writeFile({
      path,
      data: base64Data,
      directory: dir,
      recursive: true
    });
    return { uri: `file://${dir}/${path}` };
  } else {
    // Web: 觸發下載
    const byteCharacters = atob(base64Data);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = path;
    a.click();
    URL.revokeObjectURL(url);
    return { uri: url };
  }
}

export async function readFile(path, directory = 'Documents') {
  if (isNative() && hasPlugin('Filesystem')) {
    const { Filesystem, Directory } = window.Capacitor.Plugins;
    const dir = Directory[directory] || Directory.Documents;
    return Filesystem.readFile({ path, directory: dir });
  } else {
    throw new Error('Web 環境不支援直接讀取本地檔案');
  }
}

export async function deleteFile(path, directory = 'Documents') {
  if (isNative() && hasPlugin('Filesystem')) {
    const { Filesystem, Directory } = window.Capacitor.Plugins;
    const dir = Directory[directory] || Directory.Documents;
    await Filesystem.deleteFile({ path, directory: dir });
  }
}

export async function listFiles(directory = 'Documents') {
  if (isNative() && hasPlugin('Filesystem')) {
    const { Filesystem, Directory } = window.Capacitor.Plugins;
    const dir = Directory[directory] || Directory.Documents;
    return Filesystem.readdir({ path: '', directory: dir });
  } else {
    return { files: [] };
  }
}

/**
 * 本地通知
 */
export async function requestNotificationPermission() {
  if (isNative() && hasPlugin('LocalNotifications')) {
    const { LocalNotifications } = window.Capacitor.Plugins;
    const result = await LocalNotifications.requestPermissions();
    return result.display === 'granted';
  } else if ('Notification' in window) {
    const permission = await Notification.requestPermission();
    return permission === 'granted';
  }
  return false;
}

export async function scheduleNotification(notification) {
  if (isNative() && hasPlugin('LocalNotifications')) {
    const { LocalNotifications } = window.Capacitor.Plugins;
    await LocalNotifications.schedule({ notifications: [notification] });
  } else if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(notification.title, {
      body: notification.body,
      icon: notification.icon,
      tag: notification.id?.toString()
    });
  }
}

export async function cancelNotification(id) {
  if (isNative() && hasPlugin('LocalNotifications')) {
    const { LocalNotifications } = window.Capacitor.Plugins;
    await LocalNotifications.cancel({ notifications: [{ id }] });
  }
}

export async function getPendingNotifications() {
  if (isNative() && hasPlugin('LocalNotifications')) {
    const { LocalNotifications } = window.Capacitor.Plugins;
    return LocalNotifications.getPending();
  }
  return { notifications: [] };
}

/**
 * 鍵盤處理
 */
export function setupKeyboardListeners(onShow, onHide) {
  if (isNative() && hasPlugin('Keyboard')) {
    const { Keyboard } = window.Capacitor.Plugins;
    Keyboard.addListener('keyboardWillShow', onShow);
    Keyboard.addListener('keyboardWillHide', onHide);
    return () => {
      Keyboard.removeAllListeners();
    };
  } else {
    // Web: 使用 visualViewport API
    const handleResize = () => {
      const viewport = window.visualViewport;
      if (viewport) {
        const keyboardHeight = window.innerHeight - viewport.height;
        if (keyboardHeight > 150) onShow({ keyboardHeight });
        else onHide();
      }
    };
    window.visualViewport?.addEventListener('resize', handleResize);
    return () => window.visualViewport?.removeEventListener('resize', handleResize);
  }
}

/**
 * 網路狀態監聽
 */
export function setupNetworkListener(onChange) {
  if (isNative() && hasPlugin('Network')) {
    const { Network } = window.Capacitor.Plugins;
    const listener = Network.addListener('networkStatusChange', onChange);
    return () => listener.remove();
  } else {
    const handleOnline = () => onChange({ connected: true });
    const handleOffline = () => onChange({ connected: false });
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }
}

export async function getNetworkStatus() {
  if (isNative() && hasPlugin('Network')) {
    const { Network } = window.Capacitor.Plugins;
    return Network.getStatus();
  } else {
    return { connected: navigator.onLine, connectionType: 'unknown' };
  }
}

/**
 * App 生命週期
 */
export function setupAppListeners({ onPause, onResume, onExit }) {
  if (isNative() && hasPlugin('App')) {
    const { App } = window.Capacitor.Plugins;
    const listeners = [];
    if (onPause) listeners.push(App.addListener('pause', onPause));
    if (onResume) listeners.push(App.addListener('resume', onResume));
    if (onExit) listeners.push(App.addListener('exitApp', onExit));
    return () => listeners.forEach(l => l.remove());
  } else {
    const handleVisibility = () => {
      if (document.hidden) onPause?.();
      else onResume?.();
    };
    const handleBeforeUnload = () => onExit?.();
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }
}

export async function getAppInfo() {
  if (isNative() && hasPlugin('App')) {
    const { App } = window.Capacitor.Plugins;
    return App.getInfo();
  }
  return { name: '覓聲 MeetSum', version: '1.0.0', build: '1', id: 'com.meetsum.app' };
}

/**
 * Haptics 觸覺回饋
 */
export async function hapticImpact(style = 'medium') {
  if (isNative() && hasPlugin('Haptics')) {
    const { Haptics, ImpactStyle } = window.Capacitor.Plugins;
    await Haptics.impact({ style: ImpactStyle[style.charAt(0).toUpperCase() + style.slice(1)] || ImpactStyle.Medium });
  }
}

export async function hapticNotification(type = 'success') {
  if (isNative() && hasPlugin('Haptics')) {
    const { Haptics, NotificationType } = window.Capacitor.Plugins;
    await Haptics.notification({ type: NotificationType[type.charAt(0).toUpperCase() + type.slice(1)] || NotificationType.Success });
  }
}

export async function hapticSelection() {
  if (isNative() && hasPlugin('Haptics')) {
    const { Haptics } = window.Capacitor.Plugins;
    await Haptics.selectionStart();
    await Haptics.selectionChanged();
    await Haptics.selectionEnd();
  }
}

/**
 * 狀態列
 */
export async function setStatusBarStyle(style = 'dark', backgroundColor = '#1a1a2e') {
  if (isNative() && hasPlugin('StatusBar')) {
    const { StatusBar, Style } = window.Capacitor.Plugins;
    await StatusBar.setStyle({ style: Style[style.charAt(0).toUpperCase() + style.slice(1)] || Style.Dark });
    await StatusBar.setBackgroundColor({ color: backgroundColor });
  }
}

export async function showStatusBar() {
  if (isNative() && hasPlugin('StatusBar')) {
    const { StatusBar } = window.Capacitor.Plugins;
    await StatusBar.show();
  }
}

export async function hideStatusBar() {
  if (isNative() && hasPlugin('StatusBar')) {
    const { StatusBar } = window.Capacitor.Plugins;
    await StatusBar.hide();
  }
}

/**
 * Splash Screen
 */
export async function hideSplashScreen() {
  if (isNative() && hasPlugin('SplashScreen')) {
    const { SplashScreen } = window.Capacitor.Plugins;
    await SplashScreen.hide();
  }
}

export async function showSplashScreen(autoHide = true, duration = 2000) {
  if (isNative() && hasPlugin('SplashScreen')) {
    const { SplashScreen } = window.Capacitor.Plugins;
    await SplashScreen.show({ autoHide, showDuration: duration });
  }
}

/**
 * 相機 / 相簿存取 (用於選擇音檔或圖片)
 */
export async function pickMedia(options = {}) {
  if (isNative() && hasPlugin('Camera')) {
    const { Camera, CameraResultType, CameraSource } = window.Capacitor.Plugins;
    return Camera.getPhoto({
      quality: 90,
      resultType: CameraResultType.Uri,
      source: CameraSource.Photos,
      ...options
    });
  } else {
    // Web: 使用 input[type=file]
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = options.accept || 'audio/*,video/*,image/*';
      input.onchange = (e) => {
        const file = e.target.files[0];
        if (file) {
          const reader = new FileReader();
          reader.onload = () => resolve({
            webPath: reader.result,
            format: file.type.split('/')[1],
            path: file.name
          });
          reader.readAsDataURL(file);
        } else {
          reject(new Error('未選擇檔案'));
        }
      };
      input.click();
    });
  }
}

/**
 * 取得裝置資訊
 */
export async function getDeviceInfo() {
  if (isNative() && hasPlugin('Device')) {
    const { Device } = window.Capacitor.Plugins;
    return Device.getInfo();
  }
  return {
    name: navigator.userAgent,
    model: navigator.userAgent,
    platform: 'web',
    operatingSystem: navigator.platform,
    osVersion: '',
    manufacturer: '',
    isVirtual: false,
    mem: 0,
    diskFree: 0,
    diskTotal: 0
  };
}

/**
 * 分享功能 (iOS 原生分享表單)
 */
export async function share(options) {
  if (isNative() && hasPlugin('Share')) {
    const { Share } = window.Capacitor.Plugins;
    return Share.share(options);
  } else if (navigator.share) {
    return navigator.share(options);
  } else {
    // 降級：複製到剪貼簿
    const text = `${options.title}\n${options.text}\n${options.url || ''}`;
    await navigator.clipboard.writeText(text);
    return { shared: true };
  }
}

/**
 * 初始化 Capacitor 整合
 * 在 app.js 載入後呼叫
 */
export async function initCapacitor() {
  if (!isNative()) {
    console.log('[Capacitor] Web 模式，使用瀏覽器 API');
    return;
  }

  console.log('[Capacitor] 原生模式初始化');

  // 每一步獨立容錯：單一 plugin 失敗不影響其他初始化
  try {
    await setStatusBarStyle('dark', '#1a1a2e');
  } catch (err) { console.warn('[Capacitor] StatusBar 失敗:', err); }

  try {
    await hideSplashScreen();
  } catch (err) { console.warn('[Capacitor] SplashScreen 失敗:', err); }

  try {
    const hasNotifPerm = await requestNotificationPermission();
    if (!hasNotifPerm) {
      console.warn('[Capacitor] 通知權限未授予');
    }
  } catch (err) { console.warn('[Capacitor] 通知權限檢查失敗:', err); }

  // 設定鍵盤監聽 (可選)
  setupKeyboardListeners(
    (info) => document.body.classList.add('keyboard-open'),
    () => document.body.classList.remove('keyboard-open')
  );

  // 設定網路監聽
  setupNetworkListener((status) => {
    document.body.classList.toggle('offline', !status.connected);
    if (!status.connected) {
      console.warn('[Capacitor] 網路已斷線');
    }
  });

  // 設定 App 生命週期
  setupAppListeners({
    onPause: () => console.log('[Capacitor] App 進入背景'),
    onResume: () => console.log('[Capacitor] App 回到前景'),
    onExit: () => console.log('[Capacitor] App 即將結束')
  });

  console.log('[Capacitor] 初始化完成');
}

export default {
  isNative,
  hasPlugin,
  setSecure,
  getSecure,
  removeSecure,
  clearSecure,
  writeFile,
  readFile,
  deleteFile,
  listFiles,
  requestNotificationPermission,
  scheduleNotification,
  cancelNotification,
  getPendingNotifications,
  setupKeyboardListeners,
  setupNetworkListener,
  getNetworkStatus,
  setupAppListeners,
  getAppInfo,
  hapticImpact,
  hapticNotification,
  hapticSelection,
  setStatusBarStyle,
  showStatusBar,
  hideStatusBar,
  hideSplashScreen,
  showSplashScreen,
  pickMedia,
  getDeviceInfo,
  share,
  initCapacitor
};