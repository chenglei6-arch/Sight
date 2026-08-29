/**
 * 平台元信息与渲染配置。
 * 字段名与后端 app/platforms 下各 adapter.py 的返回严格对应，
 * 改动后端字段时需同步这里。
 */
import { fmtNum, fmtDate } from './utils'

function stat(list, label, value) {
  // 数值缺失 / 0 不展示，保持界面干净
  if (value === undefined || value === null || value === '' || Number(value) === 0) return
  list.push({ label, value: typeof value === 'number' ? fmtNum(value) : String(value) })
}

function splitTitle(title) {
  // 原神角色卡片 title 形如 "胡桃 Lv.90"
  const m = String(title || '').split(/ ?Lv\./)
  return { name: m[0] || title, level: m[1] || '' }
}

export const PLATFORMS = [
  {
    id: 'netease',
    name: '网易云音乐',
    color: '#e60026',
    searchPlaceholder: '输入 UID 或昵称，回车搜索',
    uidHint: '网易云 UID 为纯数字',
    contentLabel: '歌单',
    contentKind: 'playlist',
    hasDetail: true,
    hasRecords: true,
    hasEvents: true,
    hasSocial: true,
    looksLikeUid: (s) => /^\d+$/.test(s),
    resultUid: (u) => String(u.uid ?? ''),
    itemLink: (it) => (it.item_id ? `https://music.163.com/#/playlist?id=${it.item_id}` : ''),
    vipLabel: (p) => (p.is_vip ? p.vip_label || '黑胶VIP' : ''),
    metaLine: (p) => {
      const out = []
      if (p.level > 0) out.push(`Lv.${p.level}`)
      const join = fmtDate(p.join_time)
      if (join) out.push(`${join} 注册`)
      return out
    },
    stats: (p) => {
      const e = p.extra || {}
      const out = []
      stat(out, '粉丝', e.followeds)
      stat(out, '关注', e.follows)
      stat(out, '累计听歌', e.listenSongs)
      stat(out, '创建歌单', e.createdPlaylistCount)
      stat(out, '动态', e.eventCount)
      return out
    },
  },
  {
    id: 'bilibili',
    name: '哔哩哔哩',
    color: '#fb7299',
    searchPlaceholder: '输入 UID 或昵称，回车搜索',
    uidHint: 'B站 UID 为纯数字',
    contentLabel: '投稿视频',
    contentKind: 'video',
    hasDetail: false,
    hasRecords: false,
    hasEvents: true,
    hasSocial: true,
    looksLikeUid: (s) => /^\d+$/.test(s),
    resultUid: (u) => String(u.uid ?? ''),
    itemLink: (it) => (it.extra && it.extra.bvid ? `https://www.bilibili.com/video/${it.extra.bvid}` : ''),
    vipLabel: (p) => (p.is_vip ? p.vip_label || '大会员' : ''),
    metaLine: (p) => {
      const out = []
      if (p.level > 0) out.push(`LV${p.level}`)
      if (p.birthday) out.push(p.birthday)
      const official = (p.extra || {}).official
      if (official) out.push(official)
      return out
    },
    stats: (p) => {
      const e = p.extra || {}
      const out = []
      stat(out, '粉丝', e.follower_count)
      stat(out, '关注', e.following_count)
      stat(out, '播放总量', e.video_count)
      stat(out, '获赞', e.likes)
      return out
    },
  },
  {
    id: 'douyin',
    name: '抖音',
    color: '#fe2c55',
    searchPlaceholder: '昵称搜索，或直接输入数字UID / sec_uid',
    uidHint: '支持数字 UID 或 MS4wLjAB 开头的 sec_uid',
    contentLabel: '作品',
    contentKind: 'work',
    hasDetail: false,
    hasRecords: false,
    hasEvents: true,
    hasSocial: true,
    looksLikeUid: (s) => /^\d+$/.test(s) || /^MS4wLjAB/.test(s),
    resultUid: (u) => String(u.sec_uid || u.uid || ''),
    itemLink: (it) => (it.item_id ? `https://www.douyin.com/video/${it.item_id}` : ''),
    vipLabel: (p) => (p.is_vip ? '明星' : ''),
    metaLine: (p) => {
      const e = p.extra || {}
      const out = []
      if (e.unique_id) out.push(`抖音号：${e.unique_id}`)
      if (p.location) out.push(p.location)
      if (p.birthday) out.push(p.birthday)
      return out
    },
    stats: (p) => {
      const e = p.extra || {}
      const out = []
      stat(out, '粉丝', e.follower_count)
      stat(out, '关注', e.following_count)
      stat(out, '作品', e.aweme_count)
      stat(out, '获赞', e.total_favorited)
      return out
    },
  },
  {
    id: 'qqmusic',
    name: 'QQ音乐',
    color: '#31c27c',
    searchPlaceholder: '输入昵称搜索，或直接输入 QQ 号',
    uidHint: '昵称搜索后从结果中选择；QQ 号为纯数字',
    contentLabel: '歌单',
    contentKind: 'playlist',
    hasDetail: true,
    hasRecords: false,
    hasEvents: false, // QQ音乐的"动态"只是歌单复刻，与下方歌单列表重复，不展示
    hasSocial: true,
    hasQrLogin: true,
    looksLikeUid: (s) => /^\d+$/.test(s) || /\*\*$/.test(s),
    resultUid: (u) => String(u.uid ?? ''),
    itemLink: (it) => (it.item_id ? `https://y.qq.com/n/ryqq/playlist/${it.item_id}` : ''),
    vipLabel: () => '',
    metaLine: (p) => {
      const e = p.extra || {}
      const out = []
      if (e.source === 'mobile_ssr') out.push('移动端页面解析')
      return out
    },
    stats: (p) => {
      const e = p.extra || {}
      const out = []
      stat(out, '粉丝', e.fan_count ?? e.mFansNum)
      stat(out, '关注', e.follow_count ?? e.mFollowNum)
      return out
    },
  },
  {
    id: 'weibo',
    name: '微博',
    color: '#e6702e',
    searchPlaceholder: '输入数字 UID 查询；昵称搜索需登录 Cookie',
    uidHint: '微博 UID 为纯数字',
    contentLabel: '微博',
    contentKind: 'post',
    hasDetail: false,
    hasRecords: false,
    hasEvents: true,
    hasSocial: true,
    looksLikeUid: (s) => /^\d+$/.test(s),
    resultUid: (u) => String(u.uid ?? ''),
    itemLink: () => '',
    vipLabel: (p) => (p.is_vip ? '认证' : ''),
    metaLine: (p) => {
      const out = []
      if (p.location) out.push(p.location)
      return out
    },
    stats: (p) => {
      const e = p.extra || {}
      const out = []
      stat(out, '粉丝', e.fans_count)
      stat(out, '关注', e.follow_count)
      stat(out, '微博', e.weibo_count)
      return out
    },
  },
  {
    id: 'genshin',
    name: '原神',
    color: '#9d7c50',
    searchPlaceholder: '输入游戏 UID（纯数字）',
    uidHint: '原神仅支持数字游戏 UID；留空时可用 Cookie 绑定账号',
    contentLabel: '角色展柜',
    contentKind: 'character',
    hasDetail: false,
    hasRecords: false,
    hasEvents: false,
    hasSocial: false,
    looksLikeUid: (s) => /^\d+$/.test(s),
    resultUid: (u) => String(u.uid ?? ''),
    itemLink: () => '',
    vipLabel: () => '',
    metaLine: (p) => {
      const e = p.extra || {}
      const out = []
      if (p.level > 0) out.push(`冒险等阶 ${p.level}`)
      if (e.server_name) out.push(e.server_name)
      return out
    },
    stats: (p) => {
      const e = p.extra || {}
      const out = []
      stat(out, '世界等级', e.world_level)
      stat(out, '成就', e.achievements)
      if (Number(e.abyss_floor) > 0) {
        out.push({ label: '深渊', value: `${e.abyss_floor}-${e.abyss_room || '?'}` })
      }
      stat(out, '展柜角色', e.characters_count)
      return out
    },
  },
]

export const PLATFORM_MAP = Object.fromEntries(PLATFORMS.map((p) => [p.id, p]))

export function platformName(id) {
  return PLATFORM_MAP[id]?.name || id
}

export function platformColor(id) {
  return PLATFORM_MAP[id]?.color || '#9aa1ab'
}

export { splitTitle }
