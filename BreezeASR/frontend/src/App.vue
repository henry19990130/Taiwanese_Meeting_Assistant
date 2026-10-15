<script setup>
import { watch } from "vue";
import { useRoute } from "vue-router";
import ConfirmDialog from "./components/ConfirmDialog.vue";

const route = useRoute();

watch(
  () => route.meta.layout,
  (layout) => {
    document.body.classList.toggle("auth-page", layout === "auth");
    document.title = route.meta.title || "Breeze-ASR-26";
  },
  { immediate: true },
);
</script>

<template>
  <router-view />
  <ConfirmDialog />
</template>
