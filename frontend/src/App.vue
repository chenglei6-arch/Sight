<script setup>
import { onMounted } from 'vue'
import SideBar from './components/SideBar.vue'
import TopBar from './components/TopBar.vue'
import ViewPlatform from './components/ViewPlatform.vue'
import ViewTimeline from './components/ViewTimeline.vue'
import DetailModal from './components/DetailModal.vue'
import QrLoginModal from './components/QrLoginModal.vue'
import EditEntryModal from './components/EditEntryModal.vue'
import { state, initStore } from './store'

onMounted(initStore)
</script>

<template>
  <div class="app-shell">
    <SideBar />
    <div class="app-main">
      <TopBar />
      <main class="app-content">
        <ViewTimeline v-if="state.view === 'timeline'" />
        <!-- key 保证切换平台时子组件状态完全重建 -->
        <ViewPlatform v-else :key="state.view" />
      </main>
    </div>

    <DetailModal />
    <QrLoginModal v-model="state.qrOpen" />
    <EditEntryModal />
  </div>
</template>
