import { reactive } from "vue";

const dialog = reactive({
  open: false,
  title: "",
  body: "",
  confirmLabel: "確定",
  resolve: null,
});

export function useConfirm() {
  function askConfirm({ title, body, confirmLabel = "確定刪除" }) {
    dialog.open = true;
    dialog.title = title;
    dialog.body = body;
    dialog.confirmLabel = confirmLabel;
    return new Promise((resolve) => {
      dialog.resolve = resolve;
    });
  }

  function close(result) {
    dialog.open = false;
    if (dialog.resolve) {
      dialog.resolve(result);
      dialog.resolve = null;
    }
  }

  return { dialog, askConfirm, close };
}
