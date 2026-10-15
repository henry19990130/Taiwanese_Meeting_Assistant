<script setup>
import AccountMenu from "./AccountMenu.vue";
import ThemeToggle from "./ThemeToggle.vue";

defineProps({
  user: { type: Object, default: null },
});
</script>

<template>
  <div class="topbar">
    <span class="brand">Breeze ASR</span>
    <div class="topbar-actions">
      <slot />
      <ThemeToggle />
      <AccountMenu v-if="user" :user="user" />
    </div>
  </div>
</template>
