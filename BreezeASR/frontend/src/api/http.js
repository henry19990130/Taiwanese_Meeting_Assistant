export function errorDetail(payload) {
  if (payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return "操作失敗";
}

export async function readJson(response) {
  return response.json().catch(() => ({}));
}

export async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await readJson(response);
  if (!response.ok) {
    const error = new Error(errorDetail(payload));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}
