import { classNames } from "../../classes";
import Icon from "../ui/Icon";
import styles from "../ViewGraph.module.css";
import type { GraphScope } from "./scope";
const cx = classNames(styles);
export function GraphStatus({ scope }: { scope: GraphScope }) {
  const { taskText, stripItems, openCookieConfig, dismissStatus } = scope;

  return (
    <>
      {taskText || stripItems.length ? (
        <div className={cx("vg-status card")}>
          {taskText ? (
            <div className={cx("vg-status-task")}>
              <span className={cx("spinner spinner-sm")}></span>
              {taskText}
            </div>
          ) : null}
          {stripItems.length ? (
            <div className={cx("vg-status-msgs")}>
              {stripItems.map((it) => (
                <span
                  key={it.key}
                  title={it.platform ? "点击配置该平台 Cookie / 登录" : ""}
                  className={cx("vg-status-item", [
                    it.kind,
                    { clickable: it.platform },
                  ])}
                  onClick={() => {
                    it.platform && openCookieConfig(it.platform);
                  }}
                >
                  <span
                    style={{ background: it.color }}
                    className={cx("vg-chip-dot")}
                  ></span>
                  {it.text}{" "}
                  {it.platform ? (
                    <span
                      className={cx("vg-status-action")}
                      onClick={(event) => {
                        event.stopPropagation();
                        openCookieConfig(it.platform);
                      }}
                    >
                      {"配置 Cookie"}
                    </span>
                  ) : null}
                  <button
                    title="隐藏该提示"
                    className={cx("vg-status-x")}
                    onClick={(event) => {
                      event.stopPropagation();
                      dismissStatus(it.key);
                    }}
                  >
                    <Icon name="x" size={9}></Icon>
                  </button>
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
