/**
 * 后端 API 封装。
 * 统一响应格式：{ code: 200, data } 或 { code: -1, message }
 */
async function request(path, { params = {}, method = 'GET', body = null } = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')
  const url = `/api${path}${query ? `?${query}` : ''}`

  const res = await fetch(url, {
    method,
    headers: body !== null ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== null ? JSON.stringify(body) : undefined,
  })

  let payload
  try {
    payload = await res.json()
  } catch {
    throw new Error(`服务响应异常 (${res.status})`)
  }
  if (payload.code !== 200) {
    throw new Error(payload.message || `请求失败 (${res.status})`)
  }
  return payload.data
}

export const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body, params) => request(path, { params, method: 'POST', body: body ?? {} }),
  put: (path, body) => request(path, { method: 'PUT', body: body ?? {} }),
  del: (path) => request(path, { method: 'DELETE' }),
}
