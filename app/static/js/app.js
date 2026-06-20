/**
 * 多平台用户数据监控面板
 * 策略：启动时全量预加载所有平台数据 → 缓存 → 切换视图零请求
 * 自动刷新默认关闭，手动开启后每 5 分钟全量拉取
 */
(function () {
	var REFRESH_SEC = 300; // 5 分钟
	var refreshTimer = null;
	var currentView = "netease";
	var targetUids = { netease: "", bilibili: "" };

	// 数据缓存
	var dataCache = { netease: null, bilibili: null, timeline: null };
	var lastFetchTime = { netease: null, bilibili: null, timeline: null };

	var $ = function(s) { return document.querySelector(s); };
	var $$ = function(s) { return document.querySelectorAll(s); };

	var STORAGE_KEY = "monitor_uids";

	function loadUidsFromStorage() {
		try {
			var stored = localStorage.getItem(STORAGE_KEY);
			if (stored) {
				var parsed = JSON.parse(stored);
				if (parsed.netease) targetUids.netease = parsed.netease;
				if (parsed.bilibili) targetUids.bilibili = parsed.bilibili;
			}
		} catch(e) {}
	}

	function saveUidsToStorage() {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(targetUids));
		} catch(e) {}
	}

	function syncInputsFromUids() {
		var ne = $("#netease-uid"); if (ne) ne.value = targetUids.netease || "";
		var bl = $("#bilibili-uid"); if (bl) bl.value = targetUids.bilibili || "";
	}

	// ==================== Init ====================
	async function init() {
		setupAutoRefresh();
		setupModal();

		// 1. 恢复 UID
		loadUidsFromStorage();

		// 2. 无 UID 时尝试从登录用户获取
		if (!targetUids.netease || !targetUids.bilibili) {
			try {
				var resp = await fetch("/api/platforms");
				var data = await resp.json();
				if (data.code === 200 && data.data) {
					data.data.forEach(function(p) {
						if (!targetUids[p.id] && p.login_user && p.login_user.uid) {
							targetUids[p.id] = p.login_user.uid;
						}
					});
				}
			} catch(e) {}
		}
		syncInputsFromUids();
		saveUidsToStorage();

		// 3. 启动时全量预加载所有平台数据
		if (targetUids.netease || targetUids.bilibili) {
			await fetchAllData();
		}

		// 4. 渲染当前视图（从缓存）
		renderFromCache(currentView);

		// 5. 检查采集器状态
		checkCollectorStatus();

		// 6. 自动刷新默认关闭
		updateRefreshInfo();
	}

	// ==================== 全量数据拉取 ====================
	async function fetchAllData() {
		// 先拉平台数据（并行），平台 /all 会写快照到 DB
		var platformPromises = [];
		if (targetUids.netease) {
			platformPromises.push(
				fetch("/api/netease/all?uid=" + targetUids.netease)
					.then(function(r) { return r.json(); })
					.then(function(d) {
						if (d.code === 200) {
							dataCache.netease = d.data;
							lastFetchTime.netease = new Date();
						}
					})
					.catch(function(e) { console.error("netease fetch error", e); })
			);
		}
		if (targetUids.bilibili) {
			platformPromises.push(
				fetch("/api/bilibili/all?uid=" + targetUids.bilibili)
					.then(function(r) { return r.json(); })
					.then(function(d) {
						if (d.code === 200) {
							dataCache.bilibili = d.data;
							lastFetchTime.bilibili = new Date();
						}
					})
					.catch(function(e) { console.error("bilibili fetch error", e); })
			);
		}

		// 等平台数据都写入 DB 后再拉时间线
		await Promise.all(platformPromises);

		// 时间线依赖平台 /all 写入的 DB 快照，必须在平台数据之后请求
		await fetchTimeline().catch(function(e) { console.error("timeline fetch error", e); });

		updateRefreshInfo();
	}

	async function fetchTimeline() {
		var parts = [];
		if (targetUids.netease) parts.push("netease:" + targetUids.netease);
		if (targetUids.bilibili) parts.push("bilibili:" + targetUids.bilibili);
		if (!parts.length) return;
		try {
			var resp = await fetch("/api/timeline?uids=" + encodeURIComponent(parts.join(",")) + "&limit=40");
			var result = await resp.json();
			if (result.code === 200) {
				dataCache.timeline = result.data || [];
				lastFetchTime.timeline = new Date();
			}
		} catch(e) {}
	}

	// ==================== 从缓存渲染 ====================
	function renderFromCache(view) {
		var container = $("#view-content");
		if (!container) return;

		if (view === "timeline") {
			var entries = dataCache.timeline;
			if (!entries && targetUids.netease) {
				// 缓存没数据，临时请求
				container.innerHTML = '<div class="loading"><div class="spinner"></div>加载时间线...</div>';
				fetchTimeline().then(function() { renderTimelineFromCache(); });
				return;
			}
			renderTimelineFromCache();
		} else if (view === "netease" || view === "bilibili") {
			var cached = dataCache[view];
			if (!cached) {
				var uid = targetUids[view];
				if (!uid) {
					container.innerHTML = '<div class="empty-state">请在左侧输入 ' + view + ' 用户 UID 或昵称后点击 🔍 搜索</div>';
					return;
				}
				container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中（B站较慢，约需10秒）...</div>';
				fetch("/api/" + view + "/all?uid=" + uid)
					.then(function(r) { return r.json(); })
					.then(function(d) {
						if (d.code === 200) {
							dataCache[view] = d.data;
							lastFetchTime[view] = new Date();
						}
						renderPlatformFromCache(view);
					})
					.catch(function() {
						container.innerHTML = '<div class="error-banner">数据加载失败</div>';
					});
				return;
			}
			renderPlatformFromCache(view);
		}
	}

	function renderPlatformFromCache(platform) {
		var container = $("#view-content");
		if (!container) return;
		var cached = dataCache[platform];
		if (!cached) {
			container.innerHTML = '<div class="empty-state">暂无 ' + platform + ' 数据</div>';
			return;
		}
		var profile = cached.profile;
		var results = {
			profile: { code: profile ? 200 : -1, data: profile },
			playlists: { code: 200, data: cached.playlists || [] },
			records: { code: 200, data: cached.records || {allTime:[],weekly:[]} },
			events: { code: 200, data: cached.events || [] },
			follows: { code: 200, data: cached.follows || [] },
			followers: { code: 200, data: cached.followers || [] }
		};
		if (profile) { updateMiniProfile(platform, profile); updatePlatformStatus(platform, true); }
		else { updatePlatformStatus(platform, false); }
		container.innerHTML = buildPlatformHTML(platform, profile, results);
	}

	function renderTimelineFromCache() {
		var container = $("#view-content");
		if (!container) return;
		var entries = dataCache.timeline;
		if (!entries || !entries.length) {
			container.innerHTML = '<div class="empty-state">暂无活动数据</div>';
			return;
		}

		var h = '<div class="section-title">🕐 多平台统一活动时间线 <span class="count">(' + entries.length + ' 条)</span></div>';
		h += '<div class="card">';
		var currentDate = "";
		var icons = { netease: "🎵", bilibili: "📺" };

		for (var j = 0; j < entries.length; j++) {
			var e = entries[j];
			var dateStr = e.time_str ? e.time_str.split(" ")[0] : "";
			if (!dateStr && e.time_suffix === "时间未知") dateStr = "时间未知";
			if (dateStr && dateStr !== currentDate) {
				currentDate = dateStr;
				if (dateStr === "时间未知") {
					h += '<div class="timeline-date" style="color:var(--text-muted);">❓ 时间未知</div>';
				} else {
					h += '<div class="timeline-date">📅 ' + currentDate + '</div>';
				}
			}
			var icon = icons[e.platform] || "📌";
			var timePart = e.time_str ? e.time_str.split(" ")[1] || "" : "";
			var suffixHtml = "";
			if (e.time_suffix === "时间未知") suffixHtml = '<span class="tl-time-unknown">⏳ 时间未知</span>';
			else if (e.time_suffix) suffixHtml = '<span class="tl-time-range">🕐 ' + escHtml(e.time_suffix) + '</span>';

			h += '<div class="timeline-entry"><div class="tl-dot' + (e.time_suffix==='时间未知'?' tl-dot-unknown':'') + '"></div>';
			h += '<div class="tl-content"><div class="tl-meta">';
			h += '<span class="tl-platform">' + icon + ' ' + escHtml(e.platform_name) + '</span>';
			h += '<span class="tl-type">' + escHtml(e.event_type) + '</span><span class="tl-time">' + timePart + '</span></div>';
			h += '<div class="tl-summary">' + escHtml(e.summary) + '</div>';
			if (e.detail) h += '<div class="tl-detail">' + escHtml(e.detail) + '</div>';
			if (suffixHtml) h += '<div class="tl-suffix">' + suffixHtml + '</div>';
			h += '</div></div>';
		}
		h += '</div>';
		container.innerHTML = h;
	}

	// ==================== View Switching ====================
	window.switchView = function(view) {
		currentView = view;
		$$(".nav-card").forEach(function(card) { card.classList.remove("active"); });
		var navCard = $("#nav-" + view);
		if (navCard) navCard.classList.add("active");
		renderFromCache(view);
	};

	window.refreshCurrentView = function() {
		// 手动刷新：全量拉取
		fetchAllData().then(function() {
			renderFromCache(currentView);
		});
	};

	window.onUidChange = function(platform) {
		var input = document.getElementById(platform + "-uid");
		if (input) {
			targetUids[platform] = input.value.trim();
			saveUidsToStorage();
			// 清除该平台缓存，触发重新拉取
			dataCache[platform] = null;
			if (currentView === platform) renderFromCache(platform);
		}
	};

	// ==================== Platform HTML (pure render, no fetch) ====================
	function buildPlatformHTML(platform, profile, results) {
		var h = "";

		if (profile) {
			var extra = profile.extra || {};
			var followers = extra.followeds || extra.follower_count || 0;
			var following = extra.follows || extra.following_count || 0;
			var vip = profile.is_vip ? ' <span style="background:var(--primary);color:#fff;font-size:10px;padding:2px 6px;border-radius:4px;">VIP</span>' : "";
			var loc = profile.location || "";
			var sig = profile.signature || "";

			h += '<div class="card" style="display:flex;align-items:center;gap:14px;padding:16px;margin-bottom:16px;">';
			h += '<img src="' + escHtml(profile.avatar_url || "") + '?param=100y100" style="width:64px;height:64px;border-radius:50%;background:#1a2744;object-fit:cover;" loading="lazy">';
			h += '<div style="flex:1;">';
			h += '<div style="font-size:18px;font-weight:700;color:#fff;">' + escHtml(profile.nickname) + vip + '</div>';
			h += '<div style="font-size:11px;color:var(--text-muted);">UID: ' + profile.uid + ' · Lv.' + (profile.level || 0) + (loc ? ' · ' + loc : '') + '</div>';
			h += '<div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">👥 ' + fmtNum(followers) + ' 粉丝 · 👤 ' + fmtNum(following) + ' 关注</div>';
			if (sig) h += '<div style="font-size:12px;color:var(--text-muted);margin-top:2px;font-style:italic;">"' + escHtml(sig) + '"</div>';
			h += '</div></div>';
		}

		var playlistData = (results.playlists.code === 200) ? results.playlists.data : [];
		var contentLabel = platform === "netease" ? "歌单" : "投稿";
		h += '<div class="section-title">📋 ' + contentLabel + ' <span class="count">(' + (playlistData.length || 0) + ')</span></div>';
		if (playlistData.length) {
			h += '<div class="card-grid" style="margin-bottom:16px;">';
			playlistData.forEach(function(pl) {
				var title = pl.title || pl.name || "";
				var cover = pl.cover_url || pl.coverImgUrl || "";
				var count = pl.count || pl.trackCount || 0;
				var views = pl.view_count || pl.playCount || 0;
				var creator = pl.creator || "";
				var isOwner = pl.is_owner !== false;
				var label = isOwner ? "✏️ 创建" : "📌 收藏";
				h += '<div class="card playlist-card" onclick="openPlaylistModal(\'' + platform + '\',\'' + (pl.item_id || pl.id) + '\')">';
				h += '<img class="pl-cover" src="' + escHtml(cover) + '?param=160y160" alt="" loading="lazy">';
				h += '<div class="pl-info"><div class="pl-name">' + escHtml(title) + '</div>';
				h += '<div class="pl-meta">📦 ' + count + ' 项 · ▶ ' + fmtNum(views) + '</div>';
				h += '<div class="pl-creator">' + label + ' · ' + escHtml(creator) + '</div></div></div>';
			});
			h += '</div>';
		} else {
			h += '<div class="empty-state" style="margin-bottom:16px;">暂无' + contentLabel + '</div>';
		}

		var recordData = (results.records.code === 200) ? results.records.data : null;
		if (platform === "netease" && recordData) {
			h += '<div class="section-title">🏆 听歌排行 · 所有时间</div>';
			h += renderSongListHTML(recordData.allTime || []);
			h += '<div class="section-title" style="margin-top:14px;">📅 最近一周</div>';
			h += renderSongListHTML(recordData.weekly || []);
		} else if (platform === "bilibili") {
			h += '<div class="section-title">📊 播放数据</div>';
			h += '<div class="empty-state" style="margin-bottom:16px;">B站不提供公开播放历史。视频投稿见上方列表。</div>';
		}

		var eventData = (results.events.code === 200) ? results.events.data : [];
		h += '<div class="section-title" style="margin-top:14px;">💬 最近动态 <span class="count">(' + (eventData.length || 0) + ')</span></div>';
		if (eventData.length) {
			h += '<div class="card" style="margin-bottom:16px;">';
			eventData.slice(0, 10).forEach(function(ev) {
				var timeStr = "";
				var ts = ev.timestamp || ev.eventTime || 0;
				if (ts && ts > 0) timeStr = new Date(ts).toLocaleString("zh-CN");
				var content = (ev.content || "") + (ev.media_title ? " 《" + ev.media_title + "》" : "");
				h += '<div class="event-card"><div class="ev-header"><span class="ev-time">' + timeStr + '</span><span class="ev-type">' + escHtml(ev.event_type || "") + '</span></div>';
				h += '<div class="ev-content">' + escHtml(content || "(无内容)") + '</div></div>';
			});
			h += '</div>';
		} else {
			h += '<div class="empty-state" style="margin-bottom:16px;">暂无动态</div>';
		}

		var followsData = (results.follows.code === 200) ? results.follows.data : [];
		var followersData = (results.followers.code === 200) ? results.followers.data : [];
		h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">';
		h += '<div><div class="section-title">👤 关注 (' + (followsData.length || 0) + ')</div>';
		h += buildSocialList(followsData);
		h += '</div><div><div class="section-title">👥 粉丝 (' + (followersData.length || 0) + ')</div>';
		h += buildSocialList(followersData);
		h += '</div></div>';

		return h;
	}

	function buildSocialList(list) {
		if (!list || !list.length) return '<div class="empty-state">无</div>';
		var h = '<div class="card">';
		list.slice(0, 15).forEach(function(u) {
			var av = u.avatarUrl || u.avatar_url || "";
			var sig = u.signature || "";
			h += '<div class="follow-card"><img src="' + escHtml(av) + '?param=60y60" loading="lazy">';
			h += '<div class="f-info"><div class="f-name">' + escHtml(u.nickname) + '</div>';
			if (sig) h += '<div class="f-sig">' + escHtml(sig) + '</div>';
			h += '</div></div>';
		});
		h += '</div>';
		return h;
	}

	function renderSongListHTML(songs) {
		if (!songs || !songs.length) return '<div class="empty-state">暂无</div>';
		var h = '<div class="card" style="margin-bottom:14px;">';
		songs.slice(0, 20).forEach(function(s, i) {
			var name = s.title || s.name || "";
			var artist = s.artist_or_uploader || s.artists || "";
			var album = s.album_or_category || s.album || "";
			var cover = s.cover_url || s.coverUrl || "";
			var count = s.play_count || s.playCount || 0;
			h += '<div class="song-row"><span class="rank ' + (i<3?'top3':'') + '">' + (i+1) + '</span>';
			if (cover) h += '<img class="song-cover" src="' + escHtml(cover) + '?param=60y60" loading="lazy">';
			h += '<div class="song-info"><div class="song-name">' + escHtml(name) + '</div><div class="song-artist">' + escHtml(artist) + (album?' · '+escHtml(album):'') + '</div></div>';
			h += '<div class="song-count">' + count + ' 次</div></div>';
		});
		h += '</div>';
		return h;
	}

	// ==================== Search ====================
	window.searchAndSet = async function(platform) {
		var input = document.getElementById(platform + "-uid");
		var keyword = input.value.trim();
		if (!keyword) return;
		var results = document.getElementById(platform + "-results");
		results.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">搜索中...</span>';
		results.style.display = "block";
		try {
			var resp = await fetch("/api/" + platform + "/search?keyword=" + encodeURIComponent(keyword));
			var data = await resp.json();
			if (data.code !== 200 || !data.data || !data.data.length) {
				results.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">无结果</span>';
				return;
			}
			results.innerHTML = data.data.map(function(u) {
				var theUid = u.uid || u.userId || "";
				return '<div class="sr-item" data-uid="' + theUid + '">' + escHtml(u.nickname) + ' <span style="color:var(--text-muted);">' + theUid + '</span></div>';
			}).join("");
			results.querySelectorAll(".sr-item").forEach(function(item) {
				item.addEventListener("click", function() {
					targetUids[platform] = item.dataset.uid;
					input.value = item.dataset.uid;
					saveUidsToStorage();
					results.style.display = "none";
					// 清除缓存，触发全量重新拉取
					dataCache[platform] = null;
					fetchAllData().then(function() {
						renderFromCache(platform);
					});
					switchView(platform);
				});
			});
		} catch(e) {
			results.innerHTML = '<span style="font-size:11px;color:var(--primary);">搜索失败</span>';
		}
	};

	document.addEventListener("click", function(e) {
		if (!e.target.closest(".pc-input-row") && !e.target.closest(".pc-search-results")) {
			$$(".pc-search-results").forEach(function(r) { r.style.display = "none"; });
		}
	});

	// ==================== Playlist Modal ====================
	window.openPlaylistModal = async function(platform, id) {
		openModal('<div class="loading"><div class="spinner"></div>加载详情...</div>');
		try {
			var resp = await fetch("/api/" + platform + "/playlist/" + id);
			var data = await resp.json();
			if (data.code !== 200) { openModal('<button class="close-btn" onclick="closeModal()">✕</button><div class="error-banner">加载失败</div>'); return; }
			var pl = data.data;
			var h = '<button class="close-btn" onclick="closeModal()">✕</button><h3>' + escHtml(pl.title) + '</h3>';
			h += '<p style="color:var(--text-secondary);margin-bottom:12px;">📦 ' + (pl.count || 0) + ' 项 · ▶ ' + fmtNum(pl.viewCount || 0) + ' 次</p>';
			if (pl.items && pl.items.length) {
				pl.items.forEach(function(s, i) {
					h += '<div class="song-row"><span class="rank">' + (i+1) + '</span>';
					h += '<div class="song-info"><div class="song-name">' + escHtml(s.title) + '</div><div class="song-artist">' + escHtml(s.artist||'') + (s.album?' · '+escHtml(s.album):'') + '</div></div></div>';
				});
			} else { h += '<div class="empty-state">暂无内容</div>'; }
			openModal(h);
		} catch(e) {}
	};

	// ==================== Mini Profile ====================
	function updateMiniProfile(platform, profile) {
		var mini = document.getElementById(platform + "-mini");
		if (mini && profile) {
			mini.innerHTML = '<img src="' + escHtml(profile.avatar_url||"") + '?param=40y40" style="width:22px;height:22px;border-radius:50%;vertical-align:middle;object-fit:cover;" loading="lazy"> <span style="font-weight:600;">' + escHtml(profile.nickname) + '</span>';
		}
	}

	function updatePlatformStatus(platform, alive) {
		var el = document.getElementById(platform + "-status");
		if (el) el.style.color = alive ? "var(--success)" : "var(--primary)";
	}

	// ==================== Collector ====================
	async function checkCollectorStatus() {
		try {
			var resp = await fetch("/api/collector/status");
			var data = await resp.json();
			if (data.code === 200 && data.data) {
				var s = data.data;
				var badge = $("#collector-badge");
				if (badge) {
					badge.textContent = s.running ? "采集器: 运行中 (" + s.interval_minutes + "分)" : "采集器: 未启动";
					badge.style.color = s.running ? "var(--success)" : "var(--text-muted)";
				}
				if (s.running && s.targets) {
					for (var p in s.targets) { if (s.targets[p] && !targetUids[p]) targetUids[p] = s.targets[p]; }
				}
			}
		} catch(e) {}
	}

	window.startCollector = async function() {
		var interval = parseInt($("#collector-interval").value) || 30;
		var targets = {};
		for (var p in targetUids) { if (targetUids[p]) targets[p] = targetUids[p]; }
		if (!Object.keys(targets).length) { alert("请先配置 UID"); return; }
		try {
			var resp = await fetch("/api/collector/start", {
				method: "POST", headers: {"Content-Type":"application/json"},
				body: JSON.stringify({targets:targets, interval_minutes:interval}),
			});
			if ((await resp.json()).code === 200) {
				var badge = $("#collector-badge");
				if (badge) { badge.textContent = "采集器: 运行中 (" + interval + "分)"; badge.style.color = "var(--success)"; }
				var log = $("#collector-log");
				if (log) log.innerHTML += '<div style="color:var(--success);">✓ ' + new Date().toLocaleTimeString() + ' 已启动</div>';
			}
		} catch(e) {}
	};

	window.stopCollector = async function() {
		try { await fetch("/api/collector/stop", { method: "POST" }); } catch(e) {}
		var badge = $("#collector-badge");
		if (badge) { badge.textContent = "采集器: 已停止"; badge.style.color = "var(--text-muted)"; }
	};

	window.collectOnce = async function() {
		try {
			var resp = await fetch("/api/collector/collect", { method: "POST" });
			var log = $("#collector-log");
			if (log) log.innerHTML += '<div style="color:var(--success);">✓ ' + new Date().toLocaleTimeString() + ' 采集完成</div>';
			// 采集完后刷新缓存
			await fetchAllData();
			renderFromCache(currentView);
		} catch(e) {}
	};

	// ==================== Modal & Auto Refresh ====================
	function setupModal() {
		$("#modal-overlay").addEventListener("click", function(e) { if (e.target === $("#modal-overlay")) closeModal(); });
	}
	function openModal(html) { $("#modal-content").innerHTML = html; $("#modal-overlay").classList.add("active"); }
	window.closeModal = function() { $("#modal-overlay").classList.remove("active"); };

	function setupAutoRefresh() {
		// 防御浏览器自动恢复表单状态：强制初始为未勾选
		var toggle = $("#auto-refresh");
		if (toggle) {
			toggle.checked = false;
			// 延迟再清一次，防御浏览器异步恢复
			setTimeout(function() { toggle.checked = false; }, 100);
		}
		$("#auto-refresh").addEventListener("change", function() { this.checked ? startAutoRefresh() : stopAutoRefresh(); });
	}
	function startAutoRefresh() {
		stopAutoRefresh();
		refreshTimer = setInterval(function() {
			fetchAllData().then(function() {
				renderFromCache(currentView);
			});
		}, REFRESH_SEC * 1000);
		updateRefreshInfo();
	}
	function stopAutoRefresh() {
		clearInterval(refreshTimer);
		refreshTimer = null;
		updateRefreshInfo();
	}

	function updateRefreshInfo() {
		var info = $("#refresh-info");
		if (!info) return;
		if (refreshTimer) {
			info.textContent = "每 " + (REFRESH_SEC / 60) + " 分刷新";
			return;
		}
		// 显示各平台最近拉取时间
		var parts = [];
		if (lastFetchTime.netease) parts.push("🎵 " + fmtTime(lastFetchTime.netease));
		if (lastFetchTime.bilibili) parts.push("📺 " + fmtTime(lastFetchTime.bilibili));
		if (parts.length) {
			info.textContent = "上次更新: " + parts.join(" · ");
		} else {
			info.textContent = "等待首次加载";
		}
	}

	function fmtTime(d) {
		return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
	}

	// ==================== Helpers ====================
	function fmtNum(n) {
		if (n == null) return "0"; n = parseInt(n);
		if (n >= 100000000) return (n/100000000).toFixed(1) + "亿";
		if (n >= 10000) return (n/10000).toFixed(1) + "万";
		return n.toLocaleString();
	}
	function escHtml(s) {
		if (!s) return ""; var d = document.createElement("div"); d.textContent = s; return d.innerHTML;
	}

	window.refreshAll = function() {
		fetchAllData().then(function() { renderFromCache(currentView); });
	};
	window.refreshCurrentView = function() {
		fetchAllData().then(function() { renderFromCache(currentView); });
	};

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else { init(); }
})();
