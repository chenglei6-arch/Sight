import { Fragment, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { classNames } from "../classes";
import { PLATFORMS, PLATFORM_MAP } from "../platforms";
import { loadPlatformsMeta, openQrLogin } from "../store";
import type {
  Account,
  AccountTest,
  AccountsResponse,
  CredentialStatus,
} from "../types";
import styles from "./CookieModal.module.css";
import Icon from "./ui/Icon";
import Modal from "./ui/Modal";
const cx = classNames(styles);

export default function CookieModal({
  open = false,
  platform = "",
  onClose,
  onSaved,
}: {
  open?: boolean;
  platform?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [selPlatform, setSelPlatform] = useState(platform || PLATFORMS[0].id);
  const [status, setStatus] = useState<CredentialStatus | null>(null),
    [accounts, setAccounts] = useState<AccountsResponse | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false),
    [saving, setSaving] = useState(false),
    [cookieText, setCookieText] = useState(""),
    [message, setMessage] = useState(""),
    [messageIsError, setMessageIsError] = useState(false);
  const [extraName, setExtraName] = useState(""),
    [extraCookie, setExtraCookie] = useState(""),
    [addingAccount, setAddingAccount] = useState(false);
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({}),
    [rowTesting, setRowTesting] = useState<Record<string, boolean>>({}),
    [testResults, setTestResults] = useState<
      Record<string, { ok: boolean; text: string }>
    >({});
  const epoch = useRef(0),
    active = useRef(false);
  active.current = open;
  const selected = useRef(selPlatform);
  selected.current = selPlatform;
  const platformName = PLATFORM_MAP[selPlatform]?.name || selPlatform,
    canQrLogin = selPlatform === "qqmusic";
  const extraAccounts = (accounts?.accounts || []).filter((a) => !a.primary),
    n = accounts?.pool_size || 0;
  const parallelHint =
    n >= 2
      ? `当前 ${n} 个账号并行查询，批量展开速度约 ×${n}`
      : "添加附加账号后，图谱展开等批量查询将并行进行，速度按账号数提升";
  const HOWTO: Record<string, string> = {
    douyin:
      "浏览器登录 douyin.com → F12 打开开发者工具 → Network(网络) → 刷新页面 → 点击任意 douyin.com 请求 → Request Headers(请求标头) 里复制完整 Cookie 值粘贴到下方",
    xhs: "浏览器登录 xiaohongshu.com → F12 → Network → 刷新 → 复制任意请求的 Cookie 请求头",
  };
  const howto =
    HOWTO[selPlatform] ||
    "浏览器登录该平台网页版 → F12 打开开发者工具 → Network(网络) → 刷新页面 → 复制任意请求的 Cookie 请求头，粘贴到下方";
  const emit = (event: "close" | "saved") =>
    event === "close" ? onClose() : onSaved();
  const isCurrent = (version: number) =>
    active.current && epoch.current === version;
  useEffect(() => {
    if (open) setSelPlatform(platform || PLATFORMS[0].id);
  }, [open, platform]);
  async function loadAll(version = epoch.current, signal?: AbortSignal) {
    const pid = selected.current;
    setLoadingStatus(true);
    try {
      const [s, a] = await Promise.all([
        api.get<CredentialStatus>(`/credentials/${pid}`, undefined, signal),
        api.get<AccountsResponse>(`/accounts/${pid}`, undefined, signal),
      ]);
      if (!isCurrent(version)) return;
      setStatus(s);
      setAccounts(a);
    } catch (e) {
      if (!isCurrent(version) || signal?.aborted) return;
      setStatus(null);
      setAccounts(null);
      setMessage("加载凭证状态失败：" + errorMessage(e));
      setMessageIsError(true);
    } finally {
      if (isCurrent(version) && !signal?.aborted) setLoadingStatus(false);
    }
  }
  useEffect(() => {
    const version = ++epoch.current;
    if (!open) return;
    const controller = new AbortController();
    setCookieText("");
    setExtraName("");
    setExtraCookie("");
    setMessage("");
    setMessageIsError(false);
    setRowBusy({});
    setRowTesting({});
    setTestResults({});
    setAccounts(null);
    setStatus(null);
    setSaving(false);
    setAddingAccount(false);
    void loadAll(version, controller.signal);
    return () => {
      epoch.current++;
      controller.abort();
    };
  }, [open, selPlatform]);
  async function afterChange(version: number) {
    await loadPlatformsMeta();
    if (!isCurrent(version)) return;
    await loadAll(version);
    if (isCurrent(version)) onSaved();
  }
  async function save() {
    const raw = cookieText.trim(),
      version = epoch.current;
    if (!raw || saving) return;
    setSaving(true);
    setMessage("");
    try {
      await api.post(`/credentials/${selPlatform}`, { cookie: raw });
      if (!isCurrent(version)) return;
      setCookieText("");
      setMessage("主账号已保存");
      setMessageIsError(false);
      await afterChange(version);
    } catch (e) {
      if (isCurrent(version)) {
        setMessage("保存失败：" + errorMessage(e));
        setMessageIsError(true);
      }
    } finally {
      if (isCurrent(version)) setSaving(false);
    }
  }
  async function addAccount() {
    const raw = extraCookie.trim(),
      version = epoch.current;
    if (!raw || addingAccount) return;
    setAddingAccount(true);
    setMessage("");
    try {
      await api.post(`/accounts/${selPlatform}`, {
        cookie: raw,
        name: extraName.trim(),
      });
      if (!isCurrent(version)) return;
      setExtraName("");
      setExtraCookie("");
      setMessage("附加账号已添加");
      setMessageIsError(false);
      await afterChange(version);
    } catch (e) {
      if (isCurrent(version)) {
        setMessage("添加失败：" + errorMessage(e));
        setMessageIsError(true);
      }
    } finally {
      if (isCurrent(version)) setAddingAccount(false);
    }
  }
  async function accountAction(a: Account, remove = false) {
    if (rowBusy[a.id]) return;
    if (remove && !confirm(`确定删除附加账号「${a.name}」？`)) return;
    const version = epoch.current;
    setRowBusy((s) => ({ ...s, [a.id]: true }));
    try {
      if (remove) await api.del(`/accounts/${selPlatform}/${a.id}`);
      else
        await api.post(`/accounts/${selPlatform}/${a.id}`, {
          enabled: !a.enabled,
        });
      await afterChange(version);
    } catch (e) {
      if (isCurrent(version)) {
        setMessage((remove ? "删除失败：" : "操作失败：") + errorMessage(e));
        setMessageIsError(true);
      }
    } finally {
      if (isCurrent(version)) setRowBusy((s) => ({ ...s, [a.id]: false }));
    }
  }
  const toggleAccount = (a: Account) => accountAction(a),
    delAccount = (a: Account) => accountAction(a, true);
  async function testAccount(a: Pick<Account, "id">) {
    const id = a.id,
      version = epoch.current;
    if (rowTesting[id]) return;
    setRowTesting((s) => ({ ...s, [id]: true }));
    try {
      const r = await api.post<AccountTest>(
        `/accounts/${selPlatform}/${id}/test`,
      );
      if (!isCurrent(version)) return;
      const who = r.login_user?.nickname || r.login_user?.uid || "";
      let text = r.ok
        ? `可用${who ? `（登录：${who}）` : ""} · ${r.latency_ms}ms`
        : "不可用" + (r.error ? `：${r.error}` : "");
      if (r.ok && r.warning) text += `，注意：${r.warning}`;
      setTestResults((s) => ({ ...s, [id]: { ok: !!r.ok, text } }));
    } catch (e) {
      if (isCurrent(version))
        setTestResults((s) => ({
          ...s,
          [id]: { ok: false, text: "测试失败：" + errorMessage(e) },
        }));
    } finally {
      if (isCurrent(version)) setRowTesting((s) => ({ ...s, [id]: false }));
    }
  }
  function qrLogin() {
    onClose();
    openQrLogin();
  }

  return (
    <>
      <Modal
        open={open}
        title={`配置 ${platformName} 账号`}
        width={640}
        onClose={() => {
          emit("close");
        }}
      >
        <div className={cx("ck-platform-row")}>
          <span className={cx("ck-platform-label")}>{"平台"}</span>
          <select
            value={selPlatform}
            className={cx("ck-platform-select")}
            onChange={(event) => {
              setSelPlatform(event.currentTarget.value);
            }}
          >
            {PLATFORMS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className={cx("ck-section-title")}>
          <Icon name="user" size={13}></Icon>
          {" 主账号 "}
          <span className={cx("ck-section-note")}>
            {"历史记录等私有数据固定使用主账号"}
          </span>
        </div>
        <div className={cx("ck-status")}>
          {loadingStatus ? (
            <Fragment>
              <span className={cx("spinner spinner-sm")}></span>
              {"读取凭证状态…"}
            </Fragment>
          ) : status?.has_credential ? (
            <Fragment>
              <Icon name="check" size={13} className={cx("ck-ok")}></Icon>
              {" 已配置 Cookie（"}
              {status.cookie_keys.length}
              {" 个字段，保存于 credentials/accounts.json） "}
              <button
                disabled={rowTesting["primary"]}
                className={cx("btn btn-sm ck-status-btn")}
                onClick={() => {
                  testAccount({ id: "primary" });
                }}
              >
                {rowTesting["primary"] ? (
                  <span className={cx("spinner spinner-sm")}></span>
                ) : null}
                {rowTesting["primary"] ? "测试中" : "测试可用性"}
              </button>
            </Fragment>
          ) : (
            <Fragment>
              <Icon name="alert" size={13} className={cx("ck-miss")}></Icon>
              {" 未配置 Cookie —— 搜索/资料接口大概率失败 "}
            </Fragment>
          )}
        </div>
        {testResults["primary"] ? (
          <p
            className={cx("ck-test-result", {
              "ck-test-err": !testResults["primary"].ok,
            })}
          >
            {testResults["primary"].text}
          </p>
        ) : null}
        <p className={cx("ck-howto")}>{howto}</p>
        <textarea
          value={cookieText}
          rows={5}
          spellCheck={false}
          placeholder="把复制的 Cookie 粘贴到这里（格式：k=v; k2=v2; ...）"
          className={cx("ck-input")}
          onChange={(event) => {
            setCookieText(event.currentTarget.value);
          }}
        ></textarea>
        {message ? (
          <p className={cx("ck-msg", { "ck-msg-err": messageIsError })}>
            {message}
          </p>
        ) : null}
        <div className={cx("ck-actions")}>
          {canQrLogin ? (
            <button
              disabled={saving}
              className={cx("btn")}
              onClick={() => {
                qrLogin();
              }}
            >
              <Icon name="scan" size={13}></Icon>
              {" 扫码登录 "}
            </button>
          ) : null}
          <span className={cx("ck-spacer")}></span>
          <button
            className={cx("btn")}
            onClick={() => {
              emit("close");
            }}
          >
            {"取消"}
          </button>
          <button
            disabled={saving || !cookieText.trim()}
            className={cx("btn btn-primary")}
            onClick={() => {
              save();
            }}
          >
            {saving ? <span className={cx("spinner spinner-sm")}></span> : null}
            {saving ? "保存中" : "保存为主账号"}
          </button>
        </div>
        <div className={cx("ck-divider")}></div>
        <div className={cx("ck-section-title")}>
          <Icon name="users" size={13}></Icon>
          {" 附加账号 "}
          <span className={cx("ck-section-note")}>{parallelHint}</span>
        </div>
        {extraAccounts.length ? (
          <div className={cx("ck-accounts")}>
            {extraAccounts.map((a) => (
              <div
                key={a.id}
                className={cx("ck-acc-row", { "ck-acc-disabled": !a.enabled })}
              >
                <div className={cx("ck-acc-main")}>
                  <div className={cx("ck-acc-name")}>
                    {a.name}{" "}
                    {!a.enabled ? (
                      <span className={cx("ck-badge ck-badge-off")}>
                        {"已停用"}
                      </span>
                    ) : null}
                  </div>
                  <div className={cx("ck-acc-meta")}>
                    {a.has_credential
                      ? `Cookie ${a.cookie_keys.length} 个字段`
                      : "未配置 Cookie"}
                  </div>
                  {testResults[a.id] ? (
                    <div
                      className={cx("ck-acc-test", {
                        "ck-test-err": !testResults[a.id].ok,
                      })}
                    >
                      {testResults[a.id].text}
                    </div>
                  ) : null}
                </div>
                <div className={cx("ck-acc-ops")}>
                  <button
                    disabled={rowTesting[a.id]}
                    className={cx("btn btn-sm")}
                    onClick={() => {
                      testAccount(a);
                    }}
                  >
                    {rowTesting[a.id] ? (
                      <span className={cx("spinner spinner-sm")}></span>
                    ) : null}
                    {rowTesting[a.id] ? "测试中" : "测试"}
                  </button>
                  <button
                    disabled={rowBusy[a.id]}
                    className={cx("btn btn-sm")}
                    onClick={() => {
                      toggleAccount(a);
                    }}
                  >
                    {a.enabled ? "停用" : "启用"}
                  </button>
                  <button
                    disabled={rowBusy[a.id]}
                    className={cx("btn btn-sm ck-del")}
                    onClick={() => {
                      delAccount(a);
                    }}
                  >
                    <Icon name="trash" size={12}></Icon>
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className={cx("ck-empty")}>
            {"还没有附加账号，粘贴另一个账号的 Cookie 添加即可开始并行查询"}
          </p>
        )}
        <div className={cx("ck-add")}>
          <div className={cx("ck-add-row")}>
            <input
              value={extraName}
              placeholder="备注名（可选，如：小号1）"
              className={cx("ck-name-input")}
              onChange={(event) => {
                setExtraName(event.currentTarget.value);
              }}
            ></input>
          </div>
          <textarea
            value={extraCookie}
            rows={3}
            spellCheck={false}
            placeholder="粘贴另一个账号的 Cookie，添加后与主账号并行查询"
            className={cx("ck-input")}
            onChange={(event) => {
              setExtraCookie(event.currentTarget.value);
            }}
          ></textarea>
          <div className={cx("ck-add-actions")}>
            <span className={cx("ck-add-tip")}>
              {
                "附加账号仅用于公开数据加速（搜索/关注/粉丝/互查），不会影响主账号的历史记录"
              }
            </span>
            <button
              disabled={addingAccount || !extraCookie.trim()}
              className={cx("btn btn-primary")}
              onClick={() => {
                addAccount();
              }}
            >
              {addingAccount ? (
                <span className={cx("spinner spinner-sm")}></span>
              ) : null}
              {" 添加账号 "}
            </button>
          </div>
        </div>
        {canQrLogin ? (
          <p className={cx("ck-tip")}>
            {"QQ音乐支持扫码登录；其他平台请粘贴 Cookie"}
          </p>
        ) : null}
      </Modal>
    </>
  );
}
