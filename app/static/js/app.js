/**
 * 多平台用户数据监控面板
 * 策略：启动时全量预加载所有平台数据 → 缓存 → 切换视图零请求
 * 自动刷新默认关闭，手动开启后每 5 分钟全量拉取
 */
(function () {
	var REFRESH_SEC = 300; // 5 分钟
	var refreshTimer = null;
	var currentView = "netease";
	var targetUids = { netease: "", bilibili: "", douyin: "", qqmusic: "" };
	var timelineSource = "live";  // "live" 实时对比 | "stored" 持久化历史

	// 数据缓存
	var dataCache = { netease: null, bilibili: null, douyin: null, qqmusic: null, timeline: null };
	var lastFetchTime = { netease: null, bilibili: null, douyin: null, qqmusic: null, timeline: null };

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
				if (parsed.douyin) targetUids.douyin = parsed.douyin;
				if (parsed.qqmusic) targetUids.qqmusic = parsed.qqmusic;
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
		var dy = $("#douyin-uid"); if (dy) dy.value = targetUids.douyin || "";
		var qq = $("#qqmusic-uid"); if (qq) qq.value = targetUids.qqmusic || "";
	}

	// ==================== Init ====================
	async function init() {
		setupAutoRefresh();
		setupModal();

		// 1. 恢复 UID
		loadUidsFromStorage();

		// 2. 无 UID 时尝试从登录用户获取
		if (!targetUids.netease || !targetUids.bilibili || !targetUids.douyin || !targetUids.qqmusic) {
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
		if (targetUids.netease || targetUids.bilibili || targetUids.douyin || targetUids.qqmusic) {
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
						} else {
							dataCache.netease = { _errors: [d.message || "网易云请求失败"] };
						}
						lastFetchTime.netease = new Date();
					})
					.catch(function(e) {
						console.error("netease fetch error", e);
						dataCache.netease = { _errors: ["网易云网络请求失败，请检查网络或稍后重试"] };
						lastFetchTime.netease = new Date();
					})
			);
		}
		if (targetUids.bilibili) {
			platformPromises.push(
				fetch("/api/bilibili/all?uid=" + targetUids.bilibili)
					.then(function(r) { return r.json(); })
					.then(function(d) {
						if (d.code === 200) {
							dataCache.bilibili = d.data;
						} else {
							dataCache.bilibili = { _errors: [d.message || "B站请求失败，可能触发反爬虫机制"] };
						}
						lastFetchTime.bilibili = new Date();
					})
					.catch(function(e) {
						console.error("bilibili fetch error", e);
						dataCache.bilibili = { _errors: ["B站网络请求失败，请检查网络或稍后重试"] };
						lastFetchTime.bilibili = new Date();
					})
			);
		}

		if (targetUids.douyin) {
			platformPromises.push(
				fetch("/api/douyin/all?uid=" + targetUids.douyin)
					.then(function(r) { return r.json(); })
					.then(function(d) {
						if (d.code === 200) {
							dataCache.douyin = d.data;
						} else {
							dataCache.douyin = { _errors: [d.message || "抖音请求失败"] };
						}
						lastFetchTime.douyin = new Date();
					})
					.catch(function(e) {
						console.error("douyin fetch error", e);
						dataCache.douyin = { _errors: ["抖音网络请求失败，请检查网络或稍后重试"] };
						lastFetchTime.douyin = new Date();
					})
			);
		}

		if (targetUids.qqmusic) {
			platformPromises.push(
				fetch("/api/qqmusic/all?uid=" + targetUids.qqmusic)
					.then(function(r) { return r.json(); })
					.then(function(d) {
						if (d.code === 200) {
							dataCache.qqmusic = d.data;
						} else {
							dataCache.qqmusic = { _errors: [d.message || "QQ音乐请求失败"] };
						}
						lastFetchTime.qqmusic = new Date();
					})
					.catch(function(e) {
						console.error("qqmusic fetch error", e);
						dataCache.qqmusic = { _errors: ["QQ音乐网络请求失败，请检查网络或稍后重试"] };
						lastFetchTime.qqmusic = new Date();
					})
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
		if (targetUids.douyin) parts.push("douyin:" + targetUids.douyin);
		if (targetUids.qqmusic) parts.push("qqmusic:" + targetUids.qqmusic);
		if (!parts.length) return;
		try {
			var resp = await fetch("/api/timeline?uids=" + encodeURIComponent(parts.join(",")) + "&limit=40&source=" + timelineSource);
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
			if (!entries && (targetUids.netease || targetUids.bilibili || targetUids.douyin)) {
				// 缓存没数据，临时请求
				container.innerHTML = '<div class="loading"><div class="spinner"></div>加载时间线...</div>';
				fetchTimeline().then(function() { renderTimelineFromCache(); });
				return;
			}
			renderTimelineFromCache();
		} else if (view === "netease" || view === "bilibili" || view === "douyin" || view === "qqmusic") {
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
						} else {
							// API返回错误，构造带错误信息的缓存数据以便展示
							dataCache[view] = { _errors: [d.message || "请求失败，可能触发反爬虫机制"] };
						}
						renderPlatformFromCache(view);
					})
					.catch(function() {
						dataCache[view] = { _errors: ["网络请求失败，请检查网络连接或稍后重试"] };
						renderPlatformFromCache(view);
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
		// 检查是否有模块拉取失败的警告
		// 只有关键数据(profile)完全缺失时才显示红色错误横幅
		// 部分模块失败时显示温和提示
		var warningsHtml = "";
		if (cached._errors && cached._errors.length) {
			if (!cached.profile && !(cached.playlists && cached.playlists.length)) {
				// 关键数据缺失：显示红色警告
				warningsHtml = '<div class="error-banner" style="margin-bottom:12px;">';
				warningsHtml += '<div style="font-weight:700;margin-bottom:4px;">⚠️ 数据获取失败</div>';
				cached._errors.forEach(function(err) {
					var msg = (platform === "bilibili") ? (err + "（B站反爬虫机制可能已触发）") : (platform === "douyin") ? (err + "（抖音接口可能受限）") : err;
					warningsHtml += '<div style="font-size:12px;">' + escHtml(msg) + '</div>';
				});
				warningsHtml += '<div style="font-size:11px;margin-top:4px;opacity:0.7;">请稍后点击刷新重试</div>';
				warningsHtml += '</div>';
			} else {
				// 有数据但部分模块失败：显示温和提示
				var failedModules = cached._errors.map(function(e) { return e.split(":")[0]; }).join(", ");
				warningsHtml = '<div class="error-banner" style="margin-bottom:12px;background:rgba(255,193,7,0.08);border:1px solid rgba(255,193,7,0.3);color:#ffc107;">';
				warningsHtml += '⚠️ 部分模块加载失败（' + escHtml(failedModules) + '），已展示已有数据。';
				warningsHtml += ' <span style="font-size:11px;opacity:0.7;">可能是反爬虫限制，稍后会自动重试</span>';
				warningsHtml += '</div>';
			}
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
		container.innerHTML = warningsHtml + buildPlatformHTML(platform, profile, results);
	}

	function renderTimelineFromCache() {
		var container = $("#view-content");
		if (!container) return;
		var entries = dataCache.timeline;
		if (!entries || !entries.length) {
			// 显示更详细的空状态信息
			var emptyH = '<div class="empty-state" style="padding:32px;">';
			emptyH += '<div style="font-size:48px;margin-bottom:12px;">🕐</div>';
			emptyH += '<div style="font-size:16px;font-weight:600;margin-bottom:8px;">暂无活动数据</div>';
			emptyH += '<div style="font-size:12px;color:var(--text-muted);">';
			var configured = [];
			if (targetUids.netease) configured.push("网易云音乐");
			if (targetUids.bilibili) configured.push("哔哩哔哩");
				if (targetUids.douyin) configured.push("抖音");
			if (configured.length) {
				emptyH += '已配置平台: ' + configured.join(", ") + '<br>';
			}
			// 检查各平台是否有缓存数据
			var hasNeteaseData = dataCache.netease && (dataCache.netease.profile || (dataCache.netease.playlists && dataCache.netease.playlists.length));
			var hasBilibiliData = dataCache.bilibili && (dataCache.bilibili.profile || (dataCache.bilibili.playlists && dataCache.bilibili.playlists.length));
			if (hasNeteaseData || hasBilibiliData) {
				emptyH += '平台数据已获取，但时间线快照对比暂无变化。';
				emptyH += '<br>采集器运行后会自动生成时间线条目。';
			} else {
				emptyH += '请先确保平台数据能正常获取（点击 🔄 刷新）';
				if (dataCache.bilibili && dataCache.bilibili._errors) {
					emptyH += '<br><span style="color:var(--primary);">⚠ B站数据获取受阻，可能是反爬虫限制</span>';
				}
			}
			emptyH += '</div>';
			emptyH += '<button class="btn" style="margin-top:12px;" onclick="refreshCurrentView()">🔄 刷新所有数据</button>';
			emptyH += '</div>';
			container.innerHTML = emptyH;
			return;
		}

		var h = '<div class="section-title">🕐 多平台统一活动时间线 <span class="count">(' + entries.length + ' 条)</span>' +
			'<span style="margin-left:12px;font-size:11px;">' +
			'<button class="btn tl-src-btn" style="font-size:10px;padding:3px 8px;' + (timelineSource === 'live' ? 'background:var(--primary);color:#fff;' : '') + '" onclick="switchTimelineSource(\'live\')">实时</button>' +
			'<button class="btn tl-src-btn" style="font-size:10px;padding:3px 8px;margin-left:2px;' + (timelineSource === 'stored' ? 'background:var(--primary);color:#fff;' : '') + '" onclick="switchTimelineSource(\'stored\')">历史</button>' +
			'</span></div>';
		h += '<div class="card">';
		var currentDate = "";
		var icons = { netease: "🎵", bilibili: "📺", douyin: "🎶", qqmusic: "🎶" };

		for (var j = 0; j < entries.length; j++) {
			var e = entries[j];
			var dateStr = e.time_str ? e.time_str.split(" ")[0] : "";
			// 没有精确时间戳的条目归入特殊分组
			if (!dateStr) {
				if (e.time_suffix === "时间未知") dateStr = "时间未知";
				else if (e.time_suffix === "首次采集") dateStr = "首次采集";
				else if (e.time_suffix && e.time_suffix.indexOf("至少从") === 0) dateStr = "持续在听";
				else dateStr = "时间未知";
			}
			if (dateStr && dateStr !== currentDate) {
				currentDate = dateStr;
				if (dateStr === "时间未知") {
					h += '<div class="timeline-date" style="color:var(--text-muted);">❓ 时间未知</div>';
				} else if (dateStr === "首次采集") {
					h += '<div class="timeline-date" style="color:var(--text-secondary);">📌 首次采集</div>';
				} else if (dateStr === "持续在听") {
					h += '<div class="timeline-date" style="color:#8b9dc3;">⏳ 持续在听</div>';
				} else {
					h += '<div class="timeline-date">📅 ' + currentDate + '</div>';
				}
			}
			var icon = icons[e.platform] || "📌";
			var timePart = e.time_str ? e.time_str.split(" ")[1] || "" : "";
			var suffixHtml = "";
			if (e.time_suffix === "时间未知") {
				suffixHtml = '<span class="tl-time-unknown">⏳ 时间未知</span>';
			} else if (e.time_suffix === "首次采集") {
				suffixHtml = '<span class="tl-time-first">📌 首次采集</span>';
			} else if (e.time_suffix && e.time_suffix.indexOf("至少从") === 0) {
				suffixHtml = '<span class="tl-time-ongoing">' + escHtml(e.time_suffix) + '</span>';
			} else if (e.time_suffix) {
				suffixHtml = '<span class="tl-time-range">🕐 ' + escHtml(e.time_suffix) + '</span>';
			}

			var dotClass = 'tl-dot';
			if (e.time_suffix === '时间未知' || e.time_suffix === '首次采集') dotClass += ' tl-dot-unknown';
			else if (e.time_suffix && e.time_suffix.indexOf('至少从') === 0) dotClass += ' tl-dot-ongoing';
			h += '<div class="timeline-entry"><div class="' + dotClass + '"></div>';
			h += '<div class="tl-content"><div class="tl-meta">';
			h += '<span class="tl-platform">' + icon + ' ' + escHtml(e.platform_name) + '</span>';
			h += '<span class="tl-type">' + escHtml(e.event_type) + '</span><span class="tl-time">' + timePart + '</span></div>';
			h += '<div class="tl-summary">' + escHtml(e.summary) + '</div>';
			if (e.detail) h += '<div class="tl-detail">' + escHtml(e.detail) + '</div>';
			if (suffixHtml) h += '<div class="tl-suffix">' + suffixHtml + '</div>';
				// 历史模式下显示编辑/删除按钮
				if (e.id && timelineSource === 'stored') {
					h += '<div class="tl-actions" style="margin-top:6px;display:flex;gap:6px;">';
					h += '<button class="btn" style="font-size:10px;padding:2px 8px;" onclick="event.stopPropagation();editTimelineEntry(' + e.id + ')">✏️ 编辑</button>';
					h += '<button class="btn" style="font-size:10px;padding:2px 8px;color:var(--primary);" onclick="event.stopPropagation();deleteTimelineEntry(' + e.id + ')">🗑 删除</button>';
					h += '</div>';
				}
			h += '</div></div>';
		}
		h += '</div>';
		container.innerHTML = h;
			// 绑定时间线源切换按钮事件
			var srcBtns = container.querySelectorAll(".tl-src-btn");
			for (var si = 0; si < srcBtns.length; si++) {
				srcBtns[si].addEventListener("click", function() {
					var src = this.getAttribute("data-source");
					if (src) switchTimelineSource(src);
				});
			}
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

	// ==================== Timeline CRUD ====================
	window.switchTimelineSource = function(source) {
		timelineSource = source;
		dataCache.timeline = null;  // 清除缓存，强制重新拉取
		fetchTimeline().then(function() {
			renderFromCache('timeline');
		});
	};

	window.editTimelineEntry = function(entryId) {
		// 从已渲染的 DOM 中找到对应条目
		var newSummary = prompt('编辑摘要:', '');
		if (newSummary === null) return;  // 用户取消
		var newDetail = prompt('编辑详情（可留空）:', '');
		if (newDetail === null) return;

		fetch('/api/timeline/' + entryId, {
			method: 'PUT',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({summary: newSummary, detail: newDetail}),
		})
			.then(function(r) { return r.json(); })
			.then(function(d) {
				if (d.code === 200) {
					// 刷新当前时间线视图
					dataCache.timeline = null;
					fetchTimeline().then(function() { renderFromCache('timeline'); });
				} else {
					alert('编辑失败: ' + (d.message || '未知错误'));
				}
			})
			.catch(function() { alert('编辑请求失败，请检查网络'); });
	};

	window.deleteTimelineEntry = function(entryId) {
		if (!confirm('确定要删除这条时间线记录吗？此操作不可撤销。')) return;
		fetch('/api/timeline/' + entryId, { method: 'DELETE' })
			.then(function(r) { return r.json(); })
			.then(function(d) {
				if (d.code === 200) {
					dataCache.timeline = null;
					fetchTimeline().then(function() { renderFromCache('timeline'); });
				} else {
					alert('删除失败: ' + (d.message || '未知错误'));
				}
			})
			.catch(function() { alert('删除请求失败，请检查网络'); });
	};

	window.onUidChange = function(platform) {
		var input = document.getElementById(platform + "-uid");
		if (input) {
			var val = input.value.trim();
			if (val === targetUids[platform]) return;
			// 抖音特殊处理：中文或非数字非sec_uid格式的内容视为搜索关键词，不设为UID
			if (platform === "douyin" && val && !/^\d+$/.test(val) && !/^MS4wLjAB/.test(val)) {
				var results = document.getElementById(platform + "-results");
				if (results) results.style.display = "none";
				return;
			}
			// QQ音乐特殊处理：只有纯数字 QQ号 才能设为 UID（搜到的结果带 QQ号，点击后自动填入）
			if (platform === "qqmusic" && val && !/^\d+$/.test(val)) {
				var results = document.getElementById(platform + "-results");
				if (results) {
					results.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">💡 按 Enter 搜索昵称，或在结果中点击选择用户</span>';
					results.style.display = "block";
				}
				return;
			}
			targetUids[platform] = val;
			saveUidsToStorage();
			// 清除该平台缓存，触发重新拉取
			dataCache[platform] = null;
			if (val && currentView === platform) renderFromCache(platform);
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
		var contentLabel = platform === "netease" || platform === "qqmusic" ? "歌单" : platform === "douyin" ? "作品" : "投稿";
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
				// QQ音乐搜索无结果
				if (platform === "qqmusic" && keyword && !/^\d+$/.test(keyword)) {
					results.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">未找到该用户，试试输入对方的 <b>QQ号 (UIN)</b></span>';
				} else {
					results.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">无结果</span>';
				}
				return;
			}
			results.innerHTML = data.data.map(function(u) {
				var theUid = u.sec_uid || u.uid || u.userId || "";
				return '<div class="sr-item" data-uid="' + theUid + '">' + escHtml(u.nickname || "未知") + ' <span style="color:var(--text-muted);">' + (u.uid || "") + '</span></div>';
			}).join("");
			results.querySelectorAll(".sr-item").forEach(function(item) {
				// mousedown 在 blur/change 之前触发，提前设 input.value
				// 修复 change(onUidChange) 在 click 之前触发的时序问题
				item.addEventListener("mousedown", function() {
					input.value = item.dataset.uid;
					targetUids[platform] = item.dataset.uid;
				});
				item.addEventListener("click", function() {
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
		var btn = event && event.target;
		if (btn) { btn.disabled = true; btn.textContent = "⏳ 采集中..."; }

		// 收集当前配置的 targets
		var targets = {};
		if (targetUids.netease) targets.netease = targetUids.netease;
		if (targetUids.bilibili) targets.bilibili = targetUids.bilibili;
		if (targetUids.douyin) targets.douyin = targetUids.douyin;
		if (!Object.keys(targets).length) {
			var log = $("#collector-log");
			if (log) log.innerHTML += '<div style="color:var(--warning);">⚠ ' + new Date().toLocaleTimeString() + ' 请先配置 UID</div>';
			if (btn) { btn.disabled = false; btn.textContent = "📸 采集"; }
			return;
		}

		var logEl = $("#collector-log");
		var wasRunning = false;
		try {
			var statusResp = await fetch("/api/collector/status");
			var statusData = await statusResp.json();
			wasRunning = !!(statusData.code === 200 && statusData.data && statusData.data.running);
		} catch(e) {}

		var interval = parseInt($("#collector-interval").value) || 30;

		if (wasRunning) {
			// 采集器已在运行：直接调用 collect_once（同步阻塞，含多页翻页）
			try {
				var resp = await fetch("/api/collector/collect", { method: "POST" });
				var data = await resp.json();
				if (data.code === 200) {
					await fetchAllData();
					renderFromCache(currentView);
					if (logEl) logEl.innerHTML += '<div style="color:var(--success);">✓ ' + new Date().toLocaleTimeString() + ' 采集完成</div>';
				} else {
					if (logEl) logEl.innerHTML += '<div style="color:var(--primary);">✕ ' + new Date().toLocaleTimeString() + ' 采集失败: ' + (data.message || '') + '</div>';
				}
			} catch(e) {
				if (logEl) logEl.innerHTML += '<div style="color:var(--primary);">✕ ' + new Date().toLocaleTimeString() + ' 采集失败</div>';
			}
		} else {
			// 采集器未运行：启动采集器（后台线程立即执行首次 collect_once）
			try {
				var resp = await fetch("/api/collector/start", {
					method: "POST", headers: {"Content-Type": "application/json"},
					body: JSON.stringify({targets: targets, interval_minutes: interval}),
				});
				var data = await resp.json();
				if (data.code === 200) {
					// 后台线程已触发首次采集，稍等其完成
					await new Promise(function(r) { setTimeout(r, 2000); });
					await fetchAllData();
					renderFromCache(currentView);
					if (logEl) logEl.innerHTML += '<div style="color:var(--success);">✓ ' + new Date().toLocaleTimeString() + ' 采集完成</div>';
					// 手动单次采集后自动停止后台线程
					setTimeout(async function() {
						await fetch("/api/collector/stop", { method: "POST" });
						var badge = $("#collector-badge");
						if (badge) { badge.textContent = "采集器: 未启动"; badge.style.color = "var(--text-muted)"; }
					}, 500);
				} else {
					if (logEl) logEl.innerHTML += '<div style="color:var(--primary);">✕ ' + new Date().toLocaleTimeString() + ' 启动失败: ' + (data.message || '') + '</div>';
				}
			} catch(e) {
				if (logEl) logEl.innerHTML += '<div style="color:var(--primary);">✕ ' + new Date().toLocaleTimeString() + ' 启动失败</div>';
			}
		}
		if (btn) { btn.disabled = false; btn.textContent = "📸 采集"; }
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
		// 延迟 800ms 再监听 change，跳过浏览器自动恢复表单触发的 change 事件
		setTimeout(function() {
			$("#auto-refresh").addEventListener("change", function() { this.checked ? startAutoRefresh() : stopAutoRefresh(); });
		}, 800);
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
		if (lastFetchTime.douyin) parts.push("🎶 " + fmtTime(lastFetchTime.douyin));
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
