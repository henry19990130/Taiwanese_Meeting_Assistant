<script setup>
import { ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import AuthLayout from "../components/AuthLayout.vue";
import { useAuth } from "../composables/useAuth";

const router = useRouter();
const { register } = useAuth();
const username = ref("");
const password = ref("");
const status = ref("");
const submitting = ref(false);

async function onSubmit() {
  status.value = "";
  submitting.value = true;
  try {
    await register(username.value.trim(), password.value);
    await router.push("/");
  } catch (error) {
    status.value = error.message || "註冊失敗";
    submitting.value = false;
  }
}
</script>

<template>
  <AuthLayout>
    <header class="page-header">
      <p class="eyebrow">身分驗證</p>
      <h1>建立專屬帳號</h1>
      <p class="lead">帳號必須唯一。密碼至少 12 碼，且需包含英文字母與數字。</p>
    </header>
    <form id="auth-form" class="card" @submit.prevent="onSubmit">
      <label for="username">帳號</label>
      <input id="username" v-model="username" name="username" type="text" autocomplete="username" required minlength="3" maxlength="32" pattern="[A-Za-z0-9_]+">
      <p class="hint">3 到 32 碼，只能用英數字與底線。</p>
      <label for="password">密碼</label>
      <input id="password" v-model="password" name="password" type="password" autocomplete="new-password" required minlength="12">
      <button type="submit" :disabled="submitting">建立並登入</button>
      <p id="auth-status" class="error" role="status">{{ status }}</p>
      <p class="hint">已有帳號？<RouterLink to="/login">返回登入</RouterLink></p>
    </form>
  </AuthLayout>
</template>
