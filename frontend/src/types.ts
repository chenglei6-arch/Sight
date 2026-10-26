export type PlatformId =
  "netease" | "bilibili" | "douyin" | "qqmusic" | "weibo" | "genshin" | "xhs";
export type ViewId = PlatformId | "timeline" | "graph";
export type Numeric = number | string;
export interface Stat {
  label: string;
  value: string;
}
export interface ProfileExtra extends Record<string, unknown> {
  followeds?: Numeric;
  follows?: Numeric;
  listenSongs?: Numeric;
  createdPlaylistCount?: Numeric;
  eventCount?: Numeric;
  official?: string;
  follower_count?: Numeric;
  following_count?: Numeric;
  video_count?: Numeric;
  likes?: Numeric;
  unique_id?: string;
  aweme_count?: Numeric;
  total_favorited?: Numeric;
  source?: string;
  fan_count?: Numeric;
  mFansNum?: Numeric;
  follow_count?: Numeric;
  mFollowNum?: Numeric;
  fans_count?: Numeric;
  weibo_count?: Numeric;
  server_name?: string;
  world_level?: Numeric;
  achievements?: Numeric;
  abyss_floor?: Numeric;
  abyss_room?: Numeric;
  characters_count?: Numeric;
  red_id?: string;
  fans?: Numeric;
  interaction?: Numeric;
  notes_count?: Numeric;
}
export interface Profile {
  platform: PlatformId;
  uid: string;
  nickname: string;
  avatar_url?: string;
  background_url?: string;
  signature?: string;
  gender?: number;
  birthday?: string;
  location?: string;
  join_time?: Numeric;
  level: number;
  is_vip?: boolean;
  vip_label?: string;
  extra?: ProfileExtra;
}
export interface User {
  uid: string;
  nickname?: string;
  avatarUrl?: string;
  avatar_url?: string;
  signature?: string;
  sec_uid?: string;
  uin?: string;
  desc?: string;
}
export interface ContentExtra extends Record<string, unknown> {
  bvid?: string;
  danmaku_count?: Numeric;
  length?: string;
  digg_count?: Numeric;
  comment_count?: Numeric;
  duration?: Numeric;
  source?: string;
  reposts_count?: Numeric;
  comments_count?: Numeric;
  attitudes_count?: Numeric;
  is_retweet?: boolean;
  level?: Numeric;
  element?: string;
  constellation?: Numeric;
  weapon_name?: string;
  weapon_level?: Numeric;
}
export interface ContentItem {
  item_id: string;
  title?: string;
  cover_url?: string;
  count?: number;
  view_count?: number;
  creator?: string;
  description?: string;
  is_owner?: boolean;
  create_time?: Numeric;
  url?: string;
  extra?: ContentExtra;
}
export interface MediaEntry {
  entry_id?: string;
  title: string;
  artist_or_uploader?: string;
  album_or_category?: string;
  cover_url?: string;
  duration?: Numeric;
  play_count?: Numeric;
}
export interface ContentDetail {
  title?: string;
  count?: number;
  viewCount?: number;
  subscribedCount?: number;
  description?: string;
  items?: Array<{
    id?: string;
    title?: string;
    artist?: string;
    singer?: string;
    album?: string;
    duration?: Numeric;
  }>;
}
export interface ActivityEvent {
  event_id?: string;
  event_type?: string;
  content?: string;
  timestamp?: Numeric;
  media_title?: string;
  media_artist?: string;
  url?: string;
  extra?: { pics?: string[] } & Record<string, unknown>;
}
export interface PlatformPayload {
  profile: Profile | null;
  playlists: ContentItem[];
  records: { allTime?: MediaEntry[]; weekly?: MediaEntry[] } | null;
  events: ActivityEvent[];
  follows: User[];
  followers: User[];
  _errors?: string[];
}
export interface PlatformData extends Omit<PlatformPayload, "_errors"> {
  loading: boolean;
  loaded: boolean;
  fetchedAt: Date | null;
  error: string;
  errors: string[];
}
export interface PlatformMeta {
  id: PlatformId;
  name: string;
  has_credential: boolean;
  is_alive: boolean;
  login_user?: { uid: string; nickname?: string } | null;
}
export interface PlatformConfig {
  id: PlatformId;
  name: string;
  color: string;
  searchPlaceholder: string;
  uidHint: string;
  contentLabel: string;
  contentKind: "playlist" | "video" | "work" | "post" | "character" | "note";
  hasDetail: boolean;
  hasRecords: boolean;
  hasEvents: boolean;
  hasSocial: boolean;
  hasQrLogin?: boolean;
  looksLikeUid: (value: string) => boolean;
  resultUid: (user: User) => string;
  itemLink: (item: Pick<ContentItem, "item_id" | "extra">) => string;
  vipLabel?: (profile: Profile) => string;
  metaLine: (profile: Profile) => string[];
  stats: (profile: Profile) => Stat[];
}
export interface TimelineEntry {
  id?: number;
  platform: PlatformId;
  platform_name?: string;
  summary: string;
  detail?: string;
  timestamp?: Numeric;
  created_at?: string;
  time_str?: string;
  time_suffix?: string;
  event_type?: string;
  content_type?: string;
  type?: string;
}
export interface TimelineState {
  loading: boolean;
  loaded: boolean;
  error: string;
  source: "live" | "stored";
  entries: TimelineEntry[];
  fetchedAt: Date | null;
}
export interface CredentialStatus {
  has_credential: boolean;
  cookie_keys: string[];
}
export interface Account extends CredentialStatus {
  id: string;
  name: string;
  enabled: boolean;
  primary: boolean;
}
export interface AccountsResponse {
  accounts: Account[];
  pool_size: number;
}
export interface AccountTest {
  ok: boolean;
  login_user?: { uid?: string; nickname?: string };
  warning?: string;
  error?: string;
  latency_ms: number;
}
export interface QrStatus {
  status: string;
  qr_code?: string;
  error?: string;
  follow_data?: { count?: number; follows?: User[]; all_text_lines?: string[] };
}
export interface CacheStats {
  adapters_dropped?: number;
  cleared?: Record<string, number>;
  search_cache_cleared?: number;
}
export interface GraphNode extends Record<string, unknown> {
  id: string;
  platform: PlatformId | "keyword";
  uid: string;
  nickname: string;
  avatarUrl?: string;
  sec_uid?: string;
  signature?: string;
  fans?: Numeric;
  verified?: boolean;
  x?: number;
  y?: number;
}
export interface GraphEdge extends Record<string, unknown> {
  source: string;
  target: string;
  relation: string;
}
export interface ExpandProgress {
  followsLoaded: number;
  followsMore: boolean;
  followsTotal: number | null;
  followersLoaded: number;
  followersMore: boolean;
  followersTotal: number | null;
}
export interface GraphData extends Record<string, unknown> {
  keyword: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  platforms: string[];
  searched?: string[];
  errors?: Record<string, string>;
  cached?: string[];
  keywords?: Partial<Record<PlatformId, string>>;
  expanded_keys?: string[];
  interchecked_ids?: string[];
  hidden_ids?: string[];
  expand_prog?: Record<string, ExpandProgress>;
}
export interface SavedGraphMeta {
  id: number;
  name: string;
  keyword: string;
  node_count: number;
  edge_count: number;
  updated_at: string;
}
export interface SavedGraph extends SavedGraphMeta {
  data: GraphData;
}
export interface PausedQueue {
  platform: string;
  reason: string;
}
export interface ExpandItem {
  platform: string;
  uid: string;
  nickname?: string;
  follows_limit: number;
  followers_limit: number;
  follows_skip?: number;
  followers_skip?: number;
  known_ids?: string[];
  intercheck_skip?: string[];
  intercheck_extra?: string[];
  intercheck_limit?: number;
  intercheck_follow_limit?: number;
}
export interface EnqueueStats {
  queued: number;
  duplicates: number;
  rejected: number;
  paused?: PausedQueue[];
  task_ids?: number[];
  error?: string;
}
export interface ExpandPayload {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  errors?: Record<string, string>;
  intercheck?: {
    edges?: GraphEdge[];
    targets?: string[];
    checked?: number;
    total?: number;
  };
  counts?: {
    follows?: number;
    followers?: number;
    follows_offset?: number;
    followers_offset?: number;
    follows_more?: boolean;
    followers_more?: boolean;
    follows_total?: number;
    followers_total?: number;
  };
}
export interface ExpandTask {
  id: number;
  platform: string;
  uid: string;
  nickname?: string;
  status: string;
  error?: string;
  dirs?: { follows?: boolean; followers?: boolean };
  result?: ExpandPayload | null;
  accounts?: string[];
  account_map?: {
    follows?: string[];
    followers?: string[];
    intercheck?: string[];
  };
}
export interface QueueStatus {
  platform: string;
  pending: number;
  running: number;
  paused: boolean;
  pause_reason?: string;
  tasks?: ExpandTask[];
  running_tasks?: ExpandTask[];
  pending_tasks?: ExpandTask[];
  pool_size?: number;
  accounts_in_use?: number;
  accounts?: number;
  interval?: number;
}
export interface QueueResults {
  results: ExpandTask[];
  cursor: number;
  pending: number;
  paused: PausedQueue[];
}
export interface LogEntry {
  seq: number;
  boot: string;
  ts: string;
  text: string;
  source?: string;
  level?: string;
}
export interface LogResponse {
  entries: LogEntry[];
  last_seq?: number;
}
