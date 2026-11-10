import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.meetsum.app',
  appName: '覓聲 MeetSum',
  webDir: 'dist',
  // server.url 故意留空：iOS 原生建構需載入本地檔案
  // 僅在開發時使用 live reload 才設定 server.url
  // server: {
  //   url: 'http://localhost:5173',
  //   cleartext: true,
  // },
  ios: {
    scheme: 'meetsum',
    contentInset: 'automatic',
    scrollEnabled: true,
    limitsLocalSchemes: true,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 2000,
      backgroundColor: '#1a1a2e',
      showSpinner: false,
    },
    StatusBar: { style: 'dark', backgroundColor: '#1a1a2e' },
    Keyboard: { resize: 'body', style: 'dark', resizeOnFullScreen: true },
    LocalNotifications: { smallIcon: 'ic_stat_icon', iconColor: '#5E7A5A' },
    Preferences: { group: 'meetsum.preferences' }, // iOS App Groups
    Filesystem: { iosDocumentFolder: 'Documents' },
  },
};

export default config;