import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.meetsum.app',
  appName: '覓聲 MeetSum',
  webDir: 'frontend',
  server: {
    url: 'https://api.meetsum.example.com',  // 生產環境 API
    cleartext: false,                         // HTTPS only
    // 開發時可改為 localhost:8000，cleartext: true
  },
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