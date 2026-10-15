import { computed, ref } from "vue";

export function transcriptTitle(item) {
  const title = String(item?.title || "").trim();
  return title || String(item?.source_filename || "");
}

export function formatTranscriptDate(iso) {
  const match = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) {
    return iso || "";
  }
  return `${match[1]}/${match[2]}/${match[3]} ${match[4]}:${match[5]}`;
}

export function transcriptDay(iso) {
  return String(iso || "").slice(0, 10);
}

export function useTranscriptFilters(history) {
  const nameQuery = ref("");
  const dateQuery = ref("");
  const tagQuery = ref("");

  const allTags = computed(() => {
    const seen = new Set();
    const tags = [];
    for (const item of history.value) {
      for (const tag of item.tags || []) {
        const key = String(tag).toLocaleLowerCase("zh-Hant");
        if (!seen.has(key)) {
          seen.add(key);
          tags.push(tag);
        }
      }
    }
    return tags;
  });

  const visible = computed(() => {
    const name = nameQuery.value.trim().toLocaleLowerCase("zh-Hant");
    const day = dateQuery.value;
    const tag = tagQuery.value.trim().toLocaleLowerCase("zh-Hant");
    return history.value.filter((item) => {
      const haystack = `${item.title || ""} ${item.source_filename || ""}`.toLocaleLowerCase("zh-Hant");
      if (name && !haystack.includes(name)) {
        return false;
      }
      if (day && transcriptDay(item.created_at) !== day) {
        return false;
      }
      if (tag) {
        const tags = (item.tags || []).map((value) => String(value).toLocaleLowerCase("zh-Hant"));
        if (!tags.some((value) => value.includes(tag))) {
          return false;
        }
      }
      return true;
    });
  });

  const hasActiveFilters = computed(
    () => Boolean(nameQuery.value.trim() || dateQuery.value || tagQuery.value.trim()),
  );

  function clearFilters() {
    nameQuery.value = "";
    dateQuery.value = "";
    tagQuery.value = "";
  }

  return {
    nameQuery,
    dateQuery,
    tagQuery,
    allTags,
    visible,
    hasActiveFilters,
    clearFilters,
  };
}
