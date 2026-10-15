<script setup>
import { ref, watch } from "vue";
import { useConfirm } from "../composables/useConfirm";

const { dialog, close } = useConfirm();
const dialogEl = ref(null);

watch(
  () => dialog.open,
  (open) => {
    if (open) {
      dialogEl.value?.showModal();
    } else {
      dialogEl.value?.close();
    }
  },
);
</script>

<template>
  <dialog ref="dialogEl" class="confirm-dialog" @close="close(false)">
    <h2>{{ dialog.title }}</h2>
    <p>{{ dialog.body }}</p>
    <form method="dialog" @submit.prevent>
      <button type="button" class="ghost" @click="close(false)">取消</button>
      <button type="button" class="danger" @click="close(true)">{{ dialog.confirmLabel }}</button>
    </form>
  </dialog>
</template>
