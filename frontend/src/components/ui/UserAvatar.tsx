import { useEffect, useState } from "react";
import styles from "./UserAvatar.module.css";
export default function UserAvatar({
  src = "",
  name = "?",
  size = 40,
  color = "#9aa1ab",
  className = "",
}: {
  src?: string;
  name?: string;
  size?: number;
  color?: string;
  className?: string;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  useEffect(() => setFailedSrc(null), [src]);
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      className={`${styles.avatar} ${className}`}
      style={{
        width: size,
        height: size,
        background: color + "1f",
        color,
        fontSize: Math.round(size * 0.42),
      }}
    >
      {src && failedSrc !== src ? (
        <img
          key={src}
          src={src}
          referrerPolicy="no-referrer"
          loading="lazy"
          alt=""
          onError={() => setFailedSrc(src)}
        />
      ) : (
        <span className={styles["avatar-initial"]}>{initial}</span>
      )}
    </span>
  );
}
