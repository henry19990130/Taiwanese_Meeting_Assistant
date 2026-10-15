<script setup>
import { computed, ref } from "vue";
import { preferredTheme, themeLabel, toggleTheme } from "../composables/useTheme";

const theme = ref(preferredTheme());
const label = computed(() => themeLabel(theme.value));

function onToggle() {
  theme.value = toggleTheme();
}
</script>

<template>
  <button
    id="theme-toggle"
    type="button"
    class="ghost compact"
    aria-label="切換亮色或暗色模式"
    :aria-pressed="theme === 'dark'"
    @click="onToggle"
  >
    <span data-theme-label>{{ label }}</span>
  </button>
</template>
