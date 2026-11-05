import { ArrowRight, AudioLines, Sparkles, Video } from "lucide-react";
import styles from "./video-studio.module.css";

export function StudioIntro({ avatarCount, voiceCount, onCreate }: { avatarCount: number; voiceCount: number; onCreate: () => void }) {
  return <section className={styles.studioIntro} aria-label="视频创作空间介绍"><div><span className={styles.introEyebrow}><Sparkles size={13} />POLARIS VIDEO STUDIO</span><h1>让好内容，<br />拥有<mark>自己的声音。</mark></h1><p>从一段文案开始，选择形象、确定声音，<br />把产品故事变成一条生动的口播视频。</p><button type="button" className={styles.primaryButton} onClick={onCreate}>开始创作<ArrowRight size={17} /></button></div><div className={styles.introVisual} aria-hidden="true"><div className={styles.introOrbit} /><div className={styles.introVoice}><AudioLines size={38} /><span>声音，让故事被听见</span><b>{voiceCount} <small>个系统音色</small></b><div className={styles.introWave}>{Array.from({ length: 17 }, (_, i) => <i key={i} style={{ height: `${12 + ((i * 13 + 7) % 35)}px` }} />)}</div></div><span className={styles.introAvatar}><Video size={18} />{avatarCount} 个可用形象</span><span className={styles.introTag}>CREATE. SPEAK. CONNECT.</span></div></section>;
}
