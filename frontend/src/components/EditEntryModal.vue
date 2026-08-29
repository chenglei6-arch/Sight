<script setup>
import { ref, computed, watch } from 'vue'
import Modal from './ui/Modal.vue'
import { state, saveTimelineEntry } from '../store'

const summary = ref('')
const detail = ref('')
const saving = ref(false)
const error = ref('')

const open = computed(() => !!state.editEntry)

// 每次打开时用当前条目回填表单
watch(
  () => state.editEntry,
  (entry) => {
    if (entry) {
      summary.value = entry.summary
      detail.value = entry.detail
      error.value = ''
    }
  },
  { immediate: true }
)

async function save() {
  if (!state.editEntry) return
  saving.value = true
  error.value = ''
  try {
    await saveTimelineEntry(state.editEntry.id, summary.value, detail.value)
    state.editEntry = null
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal :open="open" title="编辑时间线条目" :width="460" @close="state.editEntry = null">
    <div v-if="state.editEntry">
      <label class="f-label">摘要</label>
      <textarea v-model="summary" class="input f-textarea" rows="2" />
      <label class="f-label">详情（可留空）</label>
      <textarea v-model="detail" class="input f-textarea" rows="3" />
      <div v-if="error" class="f-error">{{ error }}</div>
      <div class="f-btns">
        <button class="btn" @click="state.editEntry = null">取消</button>
        <button class="btn btn-primary" :disabled="saving || !summary.trim()" @click="save()">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.f-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin: 10px 0 5px;
}

.f-label:first-child {
  margin-top: 0;
}

.f-textarea {
  width: 100%;
  resize: vertical;
  font-family: inherit;
}

.f-error {
  margin-top: 8px;
  font-size: 12px;
  color: var(--danger);
}

.f-btns {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>
