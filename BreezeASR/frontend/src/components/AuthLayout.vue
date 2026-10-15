<script setup>
import AppTopbar from "./AppTopbar.vue";
</script>

<template>
  <div class="auth-page">
    <aside class="auth-visual" aria-hidden="true">
      <img src="/background1.jpg" alt="">
    </aside>
    <div class="auth-panel">
      <div class="app-shell auth-shell">
        <AppTopbar />
        <div class="stack">
          <slot />
        </div>
      </div>
    </div>
  </div>
</template>
