<script setup>
import { watch, onBeforeUnmount } from 'vue'

/**
 * 通用弹窗外壳：遮罩 + 卡片（标题 / 关闭按钮 / 内容插槽）
 */
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: Number, default: 560 },
})

const emit = defineEmits(['close'])

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  (v) => {
    if (v) document.addEventListener('keydown', onKeydown)
    else document.removeEventListener('keydown', onKeydown)
  }
)

onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-overlay" @mousedown.self="emit('close')">
      <div class="modal-card" :style="{ maxWidth: width + 'px' }">
        <div class="modal-head">
          <div class="modal-title">{{ title }}</div>
          <button class="btn btn-icon btn-sm" title="关闭 (Esc)" @click="emit('close')">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>
