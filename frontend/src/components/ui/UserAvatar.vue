<script setup>
import { ref, watch, computed } from 'vue'

/**
 * 圆形头像，加载失败时回退为「首字 + 平台色」占位块
 */
const props = defineProps({
  src: { type: String, default: '' },
  name: { type: String, default: '?' },
  size: { type: Number, default: 40 },
  color: { type: String, default: '#9aa1ab' },
})

const failed = ref(false)
watch(
  () => props.src,
  () => {
    failed.value = false
  }
)

const initial = computed(() => (props.name || '?').trim().charAt(0).toUpperCase() || '?')
</script>

<template>
  <span
    class="avatar"
    :style="{ width: size + 'px', height: size + 'px', background: color + '1f', color, fontSize: Math.round(size * 0.42) + 'px' }"
  >
    <img
      v-if="src && !failed"
      :src="src"
      referrerpolicy="no-referrer"
      loading="lazy"
      alt=""
      @error="failed = true"
    />
    <span v-else class="avatar-initial">{{ initial }}</span>
  </span>
</template>

<style scoped>
.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  user-select: none;
}

.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-initial {
  font-weight: 600;
  line-height: 1;
}
</style>
