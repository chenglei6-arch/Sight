import { useEffect, useRef, useState } from "react";
import { errorMessage } from "../api";
import { classNames } from "../classes";
import { saveTimelineEntry, setEditEntry, useAppStore } from "../store";
import styles from "./EditEntryModal.module.css";
import Modal from "./ui/Modal";
const cx = classNames(styles);

export default function EditEntryModal() {
  const entry = useAppStore((s) => s.editEntry),
    state = { editEntry: entry };
  const [summary, setSummary] = useState(""),
    [detail, setDetail] = useState(""),
    [saving, setSaving] = useState(false),
    [error, setError] = useState("");
  const current = useRef(entry);
  current.current = entry;
  const open = !!entry;
  useEffect(() => {
    setSummary(entry?.summary || "");
    setDetail(entry?.detail || "");
    setError("");
    setSaving(false);
  }, [entry]);
  async function save() {
    if (!entry) return;
    const target = entry;
    setSaving(true);
    setError("");
    try {
      await saveTimelineEntry(target.id, summary, detail);
      if (current.current === target) setEditEntry(null);
    } catch (e) {
      if (current.current === target) setError(errorMessage(e));
    } finally {
      if (current.current === target) setSaving(false);
    }
  }

  return (
    <>
      <Modal
        open={open}
        title="编辑时间线条目"
        width={460}
        onClose={() => {
          setEditEntry(null);
        }}
      >
        {state.editEntry ? (
          <div>
            <label className={cx("f-label")}>{"摘要"}</label>
            <textarea
              value={summary}
              rows={2}
              className={cx("input f-textarea")}
              onChange={(event) => {
                setSummary(event.currentTarget.value);
              }}
            ></textarea>
            <label className={cx("f-label")}>{"详情（可留空）"}</label>
            <textarea
              value={detail}
              rows={3}
              className={cx("input f-textarea")}
              onChange={(event) => {
                setDetail(event.currentTarget.value);
              }}
            ></textarea>
            {error ? <div className={cx("f-error")}>{error}</div> : null}
            <div className={cx("f-btns")}>
              <button
                className={cx("btn")}
                onClick={() => {
                  setEditEntry(null);
                }}
              >
                {"取消"}
              </button>
              <button
                disabled={saving || !summary.trim()}
                className={cx("btn btn-primary")}
                onClick={() => {
                  save();
                }}
              >
                {saving ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
