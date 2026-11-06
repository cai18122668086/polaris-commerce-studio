"use client";

import { AudioLines, Check, Clock3, FileText } from "lucide-react";
import { useId } from "react";
import type { GenerationJob } from "@/features/video-studio/library";
import { durationLabel, generationTimings, stageLabel } from "@/features/video-studio/generation-details";
import { Disclosure, MetadataGrid, TextDocument } from "./studio-content";
import styles from "./generation-details.module.css";

const languages: Record<string,string> = {"auto": "自动识别文案语言", "Chinese": "普通话", "Chinese,Yue": "粤语", "English": "英语", "Arabic": "阿拉伯语", "Russian": "俄语", "Spanish": "西班牙语", "French": "法语", "Portuguese": "葡萄牙语", "German": "德语", "Turkish": "土耳其语", "Dutch": "荷兰语", "Ukrainian": "乌克兰语", "Vietnamese": "越南语", "Indonesian": "印尼语", "Japanese": "日语", "Italian": "意大利语", "Korean": "韩语", "Thai": "泰语", "Polish": "波兰语", "Romanian": "罗马尼亚语", "Greek": "希腊语", "Czech": "捷克语", "Finnish": "芬兰语", "Hindi": "印地语", "Bulgarian": "保加利亚语", "Danish": "丹麦语", "Hebrew": "希伯来语", "Malay": "马来语", "Persian": "波斯语", "Slovak": "斯洛伐克语", "Swedish": "瑞典语", "Croatian": "克罗地亚语", "Filipino": "菲律宾语", "Hungarian": "匈牙利语", "Norwegian": "挪威语", "Slovenian": "斯洛文尼亚语", "Catalan": "加泰罗尼亚语", "Nynorsk": "新挪威语", "Tamil": "泰米尔语", "Afrikaans": "南非荷兰语"};
export const languageLabel = (code: string) => languages[code] || "跟随所选声音";

export function GenerationDetails({ job, onCopy }: { job: GenerationJob; onCopy?: (text: string) => void }) {
  const draft = job.snapshot?.draft;
  const groupId = useId();
  const { groups, total } = generationTimings(job);
  return <div className={styles.details}>
    {draft && <Disclosure group={groupId} title={draft.drive === "audio" ? "音频与设置" : "文案与配音"} description={draft.drive === "audio" ? "本次使用上传音频" : "本次生成使用的确认版本"} icon={<AudioLines size={17} />} meta={draft.drive === "text" ? `${draft.text.length} 字` : "音频驱动"}>
      {draft.drive === "text" ? <><MetadataGrid items={[
        {label:"配音声音",value:job.tts?.voice_name || "已选声音"},
        {label:"语速",value:`${draft.speed.toFixed(1)}×`},
        {label:"表达情绪",value:draft.emotion},
        {label:"配音语言",value:languageLabel(draft.language)},
      ]} /><TextDocument text={draft.text} title="配音确认稿" onCopy={onCopy} /></> : <MetadataGrid items={[{label:"驱动方式",value:"上传音频"},{label:"音频时长",value:job.audio_duration_seconds ? durationLabel(job.audio_duration_seconds) : "暂无时长记录"}]} />}
    </Disclosure>}
    {!!job.stage_history?.length && <Disclosure group={groupId} title="处理耗时" description="阶段用时汇总，包含历史尝试" icon={<Clock3 size={17} />} meta={durationLabel(total)}>
      <div className={styles.timingGroups}>{groups.map((group,index) => <div key={group.label} className={styles.timingGroup} data-state={group.pending ? "active" : group.interrupted ? "interrupted" : "done"}>
        <span className={styles.stageNumber}>{index + 1}</span><div><b>{group.label}</b><small>{group.pending ? "处理中" : group.waiting ? "等待继续查询" : group.interrupted ? "含中断记录" : group.recorded ? "已记录" : "暂无记录"}</small></div><strong>{group.pending ? "进行中" : group.recorded ? durationLabel(group.seconds) : "—"}</strong>
      </div>)}</div>
      <Disclosure title="查看步骤明细" description="包含历史尝试与中断记录" icon={<FileText size={15} />}>
        <ol className={styles.timingTrace}>{(job.stage_history || []).filter(stage => stage.duration_seconds === null || stage.duration_seconds >= 0.1 || stage.outcome && !["advanced","completed"].includes(stage.outcome)).map((stage,index) => <li key={`${stage.started_at}:${index}`}><span>{stage.outcome === "completed" ? <Check size={13} /> : <span className={styles.traceDot} />}{stageLabel(stage.stage)}{stage.outcome === "failed" || stage.outcome === "unknown" ? <em>中断</em> : stage.outcome === "awaiting_resume" ? <em>待查询</em> : null}</span><time>{stage.duration_seconds === null ? stage.finished_at ? "未记录" : "进行中" : durationLabel(stage.duration_seconds)}</time></li>)}</ol>
      </Disclosure>
    </Disclosure>}
  </div>;
}
