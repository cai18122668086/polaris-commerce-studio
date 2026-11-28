import { ArrowRight, AudioLines, Video } from "lucide-react";
import styles from "./video-studio.module.css";

/** 头图里的数字必须是真实数量（C9）：形象/声音还在加载或读取失败时传 null，不显示数字，也不显示 0。 */
export function StudioIntro({ avatarCount, voiceCount, onCreate }: { avatarCount: number | null; voiceCount: number | null; onCreate: () => void }) {
  return <section className={styles.studioIntro} aria-label="视频创作空间介绍"><div><h1>一条好文案，<br />变成<mark>一批能发的视频。</mark></h1><p>文案、口播、剪辑、成片四步走完，<br />封面、标题、正文一起备好，复制就能去发布。</p><button type="button" className={styles.primaryButton} onClick={onCreate}>从文案开始<ArrowRight size={17} /></button></div><div className={styles.introVisual} aria-hidden="true"><div className={styles.introOrbit} /><div className={styles.introVoice}><AudioLines size={38} /><span>声音，让故事被听见</span>{voiceCount !== null && <b>{voiceCount} <small>个系统音色</small></b>}<div className={styles.introWave}>{Array.from({ length: 17 }, (_, i) => <i key={i} style={{ height: `${12 + ((i * 13 + 7) % 35)}px` }} />)}</div></div>{avatarCount !== null && <span className={styles.introAvatar}><Video size={18} />{avatarCount} 个可用形象</span>}<span className={styles.introTag}>文案 · 口播 · 剪辑 · 成片</span></div></section>;
}
