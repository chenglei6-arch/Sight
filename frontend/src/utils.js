/**
 * 通用格式化工具
 */

/** 数字缩写：12345 -> 1.2万 */
export function fmtNum(n) {
  if (n == null || n === '' || isNaN(n)) return '0'
  n = Number(n)
  if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, '') + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, '') + '万'
  return String(n)
}

/**
 * 时长格式化。网易云歌曲 duration 为毫秒，QQ音乐为秒，
 * 以 1000 为分界自动判断，输出 mm:ss
 */
export function fmtDuration(v) {
  const n = Number(v) || 0
  if (n <= 0) return ''
  const sec = n >= 1000 ? Math.round(n / 1000) : Math.round(n)
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function pad(n) {
  return String(n).padStart(2, '0')
}

/**
 * 时间戳归一为毫秒。各平台粒度不一（B站/抖音是秒，网易云/微博是毫秒），
 * 以 1e11 为界：小于它只能是 1973~5138 年的秒级时间戳。
 */
function toMs(v) {
  const n = Number(v)
  if (!n || isNaN(n)) return 0
  return n < 1e11 ? n * 1000 : n
}

/** 毫秒时间戳 -> YYYY-MM-DD（非法返回 ''），兼容秒级输入 */
export function fmtDate(ms) {
  const ts = toMs(ms)
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 毫秒时间戳 -> HH:mm，兼容秒级输入 */
export function fmtTimeHM(ms) {
  const ts = toMs(ms)
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 时间戳 -> MM-DD HH:mm（当年省略年份，跨年补年份），兼容秒级输入 */
export function fmtEventTime(ms) {
  const ts = toMs(ms)
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const md = `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.getFullYear() === now.getFullYear() ? md : `${d.getFullYear()}-${md}`
}
