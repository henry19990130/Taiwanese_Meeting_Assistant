<script setup>
import { nextTick, onMounted, onUnmounted, ref } from "vue";

defineProps({
  active: { type: Boolean, default: false },
  label: { type: String, required: true },
  iconOnly: { type: Boolean, default: false },
});

const root = ref(null);
const open = ref(false);

function close() {
  open.value = false;
}

function toggle() {
  open.value = !open.value;
  if (open.value) {
    nextTick(() => {
      root.value?.querySelector("input")?.focus();
    });
  }
}

function onDocumentClick(event) {
  if (!root.value?.contains(event.target)) {
    close();
  }
}

function onEscape(event) {
  if (event.key === "Escape") {
    close();
  }
}

onMounted(() => {
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onEscape);
});

onUnmounted(() => {
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("keydown", onEscape);
});

defineExpose({ close });
</script>

<template>
  <div ref="root" class="filter-menu">
    <button
      type="button"
      class="ghost compact filter-menu-toggle"
      :class="{ 'is-icon': iconOnly }"
      :aria-expanded="open"
      :aria-label="label"
      aria-haspopup="dialog"
      :aria-pressed="active"
      @click="toggle"
    >
      <slot name="toggle" />
    </button>
    <div v-show="open" class="filter-menu-panel" role="dialog" :aria-label="label">
      <slot name="panel" :close="close" />
    </div>
  </div>
</template>
