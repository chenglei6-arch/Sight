<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import { PLATFORM_MAP, splitTitle } from '../platforms'
import { fmtNum, fmtDuration, fmtEventTime } from '../utils'
import { openDetail } from '../store'

/**
 * 内容网格。同一组件按平台渲染 5 种卡片：
 * playlist 歌单 / video B站投稿 / work 抖音作品 / post 微博 / character 原神角色
 */
const props = defineProps({
  platformId: { type: String, required: true },
  items: { type: Array, default: () => [] },
})

const platform = PLATFORM_MAP[props.platformId]
const kind = platform.contentKind

const shown = computed(() => props.items.slice(0, 60))

function charName(it) {
  return splitTitle(it.title).name
}

function onCardClick(it) {
  if (kind === 'playlist' && platform.hasDetail) {
    openDetail(props.platformId, it.item_id)
    return
  }
  const link = platform.itemLink(it)
  if (link) window.open(link, '_blank', 'noopener')
}

function cardClickable(it) {
  return (kind === 'playlist' && platform.hasDetail) || !!platform.itemLink(it)
}
</script>

<template>
  <div v-if="items.length" class="content-grid" :class="'kind-' + kind">
    <!-- 歌单（网易云 / QQ音乐） -->
    <template v-if="kind === 'playlist'">
      <button v-for="it in shown" :key="it.item_id" class="citem" @click="onCardClick(it)">
        <span class="cover" :style="{ background: platform.color + '14' }">
          <img
            v-if="it.cover_url"
            :src="it.cover_url"
            referrerpolicy="no-referrer"
            loading="lazy"
            alt=""
            @error="$event.target.style.display = 'none'"
          />
        </span>
        <span class="ci-body">
          <span class="ci-title" :title="it.title">{{ it.title || '未命名歌单' }}</span>
          <span class="ci-meta">
            {{ it.count || 0 }} 首
            <template v-if="it.view_count"> · {{ fmtNum(it.view_count) }} 次播放</template>
          </span>
          <span class="ci-sub">
            {{ it.is_owner === false ? '收藏' : '创建' }}
            <template v-if="it.creator"> · {{ it.creator }}</template>
          </span>
        </span>
        <Icon v-if="platform.itemLink(it)" name="external" :size="12" class="ci-link" />
      </button>
    </template>

    <!-- B站投稿 -->
    <template v-else-if="kind === 'video'">
      <button v-for="it in shown" :key="it.item_id" class="citem media" @click="onCardClick(it)">
        <span class="cover wide" :style="{ background: platform.color + '14' }">
          <img
            v-if="it.cover_url"
            :src="it.cover_url"
            referrerpolicy="no-referrer"
            loading="lazy"
            alt=""
            @error="$event.target.style.display = 'none'"
          />
        </span>
        <span class="ci-body">
          <span class="ci-title" :title="it.title">{{ it.title || '无标题' }}</span>
          <span class="ci-meta">
            <template v-if="it.view_count">{{ fmtNum(it.view_count) }} 播放</template>
            <template v-if="it.extra?.danmaku_count"> · {{ fmtNum(it.extra.danmaku_count) }} 弹幕</template>
            <template v-if="it.extra?.length"> · {{ it.extra.length }}</template>
          </span>
          <span class="ci-sub">{{ it.create_time ? fmtEventTime(Number(it.create_time)) : '' }}</span>
        </span>
      </button>
    </template>

    <!-- 抖音作品 -->
    <template v-else-if="kind === 'work'">
      <button v-for="it in shown" :key="it.item_id" class="citem media" @click="onCardClick(it)">
        <span class="cover wide" :style="{ background: platform.color + '14' }">
          <img
            v-if="it.cover_url"
            :src="it.cover_url"
            referrerpolicy="no-referrer"
            loading="lazy"
            alt=""
            @error="$event.target.style.display = 'none'"
          />
        </span>
        <span class="ci-body">
          <span class="ci-title" :title="it.title">{{ it.title || '无标题' }}</span>
          <span class="ci-meta">
            <template v-if="it.view_count">{{ fmtNum(it.view_count) }} 播放</template>
            <template v-if="it.extra?.digg_count"> · {{ fmtNum(it.extra.digg_count) }} 赞</template>
            <template v-if="it.extra?.comment_count"> · {{ fmtNum(it.extra.comment_count) }} 评论</template>
            <template v-if="it.extra?.duration"> · {{ fmtDuration(it.extra.duration) }}</template>
          </span>
          <span class="ci-sub">{{ it.create_time ? fmtEventTime(Number(it.create_time)) : '' }}</span>
        </span>
      </button>
    </template>

    <!-- 微博帖子（无封面，文本卡片） -->
    <template v-else-if="kind === 'post'">
      <div v-for="it in shown" :key="it.item_id" class="citem post">
        <span class="ci-body">
          <span class="ci-title post-text" :title="it.title">{{ it.title || '（无文字）' }}</span>
          <span class="ci-meta">
            <template v-if="it.create_time">{{ fmtEventTime(Number(it.create_time)) }}</template>
            <template v-if="it.extra?.source"> · 来自{{ it.extra.source }}</template>
          </span>
          <span class="ci-sub">
            <template v-if="it.extra?.reposts_count">{{ fmtNum(it.extra.reposts_count) }} 转发</template>
            <template v-if="it.extra?.comments_count"> · {{ fmtNum(it.extra.comments_count) }} 评论</template>
            <template v-if="it.extra?.attitudes_count"> · {{ fmtNum(it.extra.attitudes_count) }} 赞</template>
            <span v-if="it.extra?.is_retweet" class="tag retweet">转发</span>
          </span>
        </span>
      </div>
    </template>

    <!-- 原神角色展柜 -->
    <template v-else-if="kind === 'character'">
      <div v-for="(it, i) in shown" :key="it.item_id || i" class="citem character">
        <span class="cover char" :style="{ background: platform.color + '14' }">
          <img
            v-if="it.cover_url"
            :src="it.cover_url"
            referrerpolicy="no-referrer"
            loading="lazy"
            alt=""
            @error="$event.target.style.display = 'none'"
          />
        </span>
        <span class="ci-body">
          <span class="ci-title">{{ charName(it) }}</span>
          <span class="ci-meta">
            <template v-if="it.extra?.level">Lv.{{ it.extra.level }}</template>
            <template v-if="it.extra?.element"> · {{ it.extra.element }}</template>
            <template v-if="Number(it.extra?.constellation) > 0"> · {{ it.extra.constellation }}命</template>
          </span>
          <span v-if="it.extra?.weapon_name" class="ci-sub">
            {{ it.extra.weapon_name }}
            <template v-if="it.extra.weapon_level"> Lv.{{ it.extra.weapon_level }}</template>
          </span>
        </span>
      </div>
    </template>
  </div>

  <div v-else class="empty-inline">暂无{{ platform.contentLabel }}</div>
</template>

<style scoped>
.content-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}

.citem {
  position: relative;
  display: flex;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  text-align: left;
  font: inherit;
  color: inherit;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

button.citem {
  cursor: pointer;
}

button.citem:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-card);
}

.cover {
  position: relative;
  width: 46px;
  height: 46px;
  border-radius: 7px;
  overflow: hidden;
  flex-shrink: 0;
}

.cover.wide {
  width: 84px;
  height: 56px;
}

.cover.char {
  width: 56px;
  height: 56px;
  border-radius: 50%;
}

.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.ci-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ci-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.ci-meta {
  font-size: 11.5px;
  color: var(--text-2);
}

.ci-sub {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-link {
  position: absolute;
  top: 8px;
  right: 8px;
  color: var(--text-3);
  opacity: 0;
  transition: opacity 0.15s;
}

.citem:hover .ci-link {
  opacity: 1;
}

.retweet {
  margin-left: 6px;
  background: #fff4e8;
  color: #c76a1a;
}

.empty-inline {
  padding: 18px 16px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  font-size: 12.5px;
  text-align: center;
}
</style>
