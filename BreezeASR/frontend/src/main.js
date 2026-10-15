import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import { applyTheme, preferredTheme } from "./composables/useTheme";
import "./styles/main.css";

applyTheme(preferredTheme());

createApp(App).use(router).mount("#app");
