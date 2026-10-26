import { Fragment, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { classNames } from "../classes";
import type { QrStatus } from "../types";
import styles from "./QrLoginModal.module.css";
import Icon from "./ui/Icon";
import Modal from "./ui/Modal";
import UserAvatar from "./ui/UserAvatar";
const cx = classNames(styles);

let qrOperations: Promise<unknown> = Promise.resolve();
function enqueueQr(operation: () => Promise<unknown>) {
  const next = qrOperations.then(operation, operation);
  qrOperations = next.catch(() => {});
  return next;
}
export default function QrLoginModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState("idle"),
    [qrImage, setQrImage] = useState(""),
    [statusText, setStatusText] = useState(""),
    [errorMsg, setErrorMsg] = useState(""),
    [followData, setFollowData] = useState<QrStatus["follow_data"] | null>(
      null,
    );
  const generation = useRef(0),
    alive = useRef(false),
    timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined),
    poll = useRef<AbortController | null>(null);
  const phaseNote =
    (
      {
        starting: "正在生成二维码…",
        logged_in: "扫码成功，正在获取关注列表…",
        fetching: "正在获取关注列表…",
      } as Record<string, string>
    )[phase] || "";
  const stopPolling = () => {
    clearTimeout(timer.current);
    poll.current?.abort();
  };
  function start() {
    stopPolling();
    const version = ++generation.current;
    setPhase("starting");
    setQrImage("");
    setErrorMsg("");
    setFollowData(null);
    void enqueueQr(async () => {
      if (!alive.current || generation.current !== version) return;
      await api.post("/qqmusic/qr-login/start");
      if (alive.current && generation.current === version)
        void pollStatus(version);
    }).catch((e) => {
      if (alive.current && generation.current === version) {
        setPhase("error");
        setErrorMsg(errorMessage(e));
      }
    });
  }
  async function pollStatus(version: number) {
    if (!alive.current || generation.current !== version) return;
    const controller = new AbortController();
    poll.current = controller;
    let terminal = false;
    try {
      const s = await api.get<QrStatus>(
        "/qqmusic/qr-login/status",
        undefined,
        controller.signal,
      );
      if (controller.signal.aborted || generation.current !== version) return;
      setStatusText(s.status || "");
      if (
        ["qr_ready", "logged_in", "fetching", "done", "error"].includes(
          s.status,
        )
      )
        setPhase(s.status);
      if (s.qr_code) setQrImage(s.qr_code);
      if (s.status === "done") {
        setFollowData(s.follow_data || null);
        terminal = true;
      }
      if (s.status === "error") {
        setErrorMsg(s.error || "未知错误");
        terminal = true;
      }
    } catch {
      /* Retry transient status failures. */
    } finally {
      if (
        alive.current &&
        generation.current === version &&
        !controller.signal.aborted &&
        !terminal
      )
        timer.current = setTimeout(() => void pollStatus(version), 2000);
    }
  }
  useEffect(() => {
    alive.current = open;
    if (!open) return;
    const setup = ++generation.current;
    queueMicrotask(() => {
      if (alive.current && generation.current === setup) start();
    });
    return () => {
      alive.current = false;
      ++generation.current;
      stopPolling();
      void enqueueQr(() => api.post("/qqmusic/qr-login/stop")).catch(() => {});
    };
  }, [open]);
  function cancel() {
    alive.current = false;
    ++generation.current;
    stopPolling();
    onClose();
  }

  return (
    <>
      <Modal
        open={open}
        title="QQ音乐扫码登录"
        width={480}
        onClose={() => {
          cancel();
        }}
      >
        {phase === "starting" || (phase === "qr_ready" && !qrImage) ? (
          <div className={cx("qr-center")}>
            <span className={cx("spinner")}></span>
            <div className={cx("qr-note")}>{phaseNote}</div>
          </div>
        ) : phase === "qr_ready" ||
          phase === "logged_in" ||
          phase === "fetching" ? (
          <div className={cx("qr-center")}>
            {qrImage ? (
              <img
                src={"data:image/png;base64," + qrImage}
                alt="QQ登录二维码"
                className={cx("qr-img")}
              ></img>
            ) : null}
            <div className={cx("qr-note")}>
              {phase === "qr_ready" ? (
                <Fragment>{"请用手机 QQ 扫一扫登录"}</Fragment>
              ) : (
                <Fragment>
                  <span
                    style={{ display: "inline-block", verticalAlign: "-2px" }}
                    className={cx("spinner spinner-sm")}
                  ></span>
                  {" 登录成功，"}
                  {phaseNote}
                </Fragment>
              )}
            </div>
            <button
              style={{ marginTop: "12px" }}
              className={cx("btn btn-sm")}
              onClick={() => {
                start();
              }}
            >
              <Icon name="refresh" size={12}></Icon>
              {" 刷新二维码 "}
            </button>
          </div>
        ) : phase === "done" ? (
          <div className={cx("qr-done")}>
            <div className={cx("done-head")}>
              <span className={cx("done-icon")}>
                <Icon name="check" size={16}></Icon>
              </span>
              <div>
                <div className={cx("done-title")}>{"登录成功"}</div>
                <div className={cx("done-sub")}>
                  {followData
                    ? `已获取 ${followData.count ?? (followData.follows || []).length} 个关注`
                    : "未获取到关注数据"}
                </div>
              </div>
            </div>
            {followData && (followData.follows || []).length ? (
              <Fragment>
                <div className={cx("follow-list")}>
                  {(followData.follows || []).map((u, i) => (
                    <div key={i} className={cx("follow-row")}>
                      <UserAvatar
                        src={u.avatarUrl || u.avatar_url}
                        name={u.nickname}
                        size={32}
                        color="#31c27c"
                      ></UserAvatar>
                      <span className={cx("follow-main")}>
                        <span className={cx("follow-name")}>
                          {u.nickname || "未知"}
                        </span>
                        {u.signature || u.desc ? (
                          <span className={cx("follow-sig")}>
                            {u.signature || u.desc}
                          </span>
                        ) : null}
                      </span>
                    </div>
                  ))}
                </div>
              </Fragment>
            ) : (
              <Fragment>
                <div style={{ marginTop: "14px" }} className={cx("qr-note")}>
                  {" 未能从页面提取到关注列表（可能为空或不可见） "}
                </div>
                {followData?.all_text_lines?.length ? (
                  <details style={{ marginTop: "8px" }}>
                    <summary className={cx("raw-toggle")}>
                      {"查看页面原始文本"}
                    </summary>
                    <pre className={cx("raw-pre")}>
                      {followData.all_text_lines!.join("\n")}
                    </pre>
                  </details>
                ) : null}
              </Fragment>
            )}
          </div>
        ) : phase === "error" ? (
          <div className={cx("qr-center")}>
            <span className={cx("err-icon")}>
              <Icon name="alert" size={30}></Icon>
            </span>
            <div className={cx("qr-note qr-err")}>
              {"登录失败："}
              {errorMsg}
            </div>
            <div className={cx("qr-btns")}>
              <button
                className={cx("btn btn-sm btn-primary")}
                onClick={() => {
                  start();
                }}
              >
                {"重试"}
              </button>
              <button
                className={cx("btn btn-sm")}
                onClick={() => {
                  cancel();
                }}
              >
                {"关闭"}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
