import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints:["features/video-studio/generation-details.ts"], bundle:true, write:false, format:"esm", platform:"node", logLevel:"silent" });
const { durationLabel, generationTimings, stageLabel } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const timing = (stage, seconds, outcome="advanced") => ({stage,duration_seconds:seconds,outcome,started_at:"2026-11-06T09:42:00Z",finished_at:seconds === null ? null : "2026-11-06T09:43:00Z"});

test("timings retain repeated attempts and distinguish waiting, failure, and missing records", () => {
  const history = [timing("tts_submitting",9.5),timing("preparing_forward_template",1.2,"failed"),timing("preparing_forward_template",34.2),timing("forward_template_prepared",0),timing("lipsync_generating",930.7,"awaiting_resume")];
  const original = structuredClone(history);
  const result = generationTimings({kind:"lipsync",stage_history:history});
  result.groups.forEach((group,index)=>assert.ok(Math.abs(group.seconds-[9.5,35.4,930.7,0][index])<0.00001));
  assert.equal(result.groups[1].interrupted,true);
  assert.equal(result.groups[2].waiting,true);
  assert.equal(result.groups[3].recorded,false);
  assert.equal(result.groups[3].pending,false);
  assert.deepEqual(history,original);
  assert.ok(Math.abs(result.total-975.6)<0.00001);
});

test("an unfinished stage is in progress, while absent timing is never invented", () => {
  const {groups} = generationTimings({kind:"h3_template",stage_history:[timing("h3_generating",null)]});
  assert.equal(groups[1].pending,true);
  assert.equal(groups[1].recorded,false);
  assert.equal(groups[0].pending,false);
  assert.equal(durationLabel(null),"等待记录");
  assert.equal(durationLabel(Number.NaN),"等待记录");
  assert.equal(durationLabel(0.004),"不足 0.1 秒");
  assert.equal(durationLabel(930.7),"15 分 30 秒");
  assert.equal(stageLabel("forward_template_prepared"),"动作匹配完成");
  assert.equal(stageLabel("future_provider_internal_stage"),"其他处理");
});

const uiCompiled = await build({
  stdin:{contents:`
    import { createElement } from "react";
    import { renderToStaticMarkup } from "react-dom/server";
    import { GenerationDetails } from "./components/video-studio/generation-details";
    import { GenerationConfirmation } from "./components/video-studio/generation-confirmation";
    import { TextDocument } from "./components/video-studio/studio-content";
    export const renderDetails = job => renderToStaticMarkup(createElement(GenerationDetails,{job}));
    export const renderText = text => renderToStaticMarkup(createElement(TextDocument,{text}));
    export const renderConfirmation = draft => renderToStaticMarkup(createElement(GenerationConfirmation,{draft,avatar:{name:"出镜形象",cover_url:""},error:"",busy:false,saving:false,onClose(){},onConfirm(){},onCopy(){}}));
  `,resolveDir:process.cwd(),loader:"ts"},
  bundle:true,write:false,outfile:"details-test.mjs",format:"esm",platform:"node",loader:{".css":"empty",".module.css":"empty"},logLevel:"silent",
  banner:{js:'import { createRequire } from "node:module"; const require = createRequire(process.cwd() + "/package.json");'},
  define:{"process.env.NODE_ENV":'"production"'},
});
const {renderDetails,renderText,renderConfirmation} = await import(`data:text/javascript;base64,${Buffer.from(uiCompiled.outputFiles[0].text).toString("base64")}`);
const longText = "核对后的完整稿件，不增删任何内容。\n".repeat(40);
const draft = {name:"产品讲述",drive:"text",text:longText,voiceId:"mm-internal-voice-id",speed:1.2,emotion:"愉快",language:"Japanese",avatarId:"avatar",quality:"1080P"};

test("long text is compact initially and retains every original character for full reading", () => {
  const html = renderText(longText);
  assert.ok(html.includes(longText));
  assert.match(html,/data-expanded="false"/);
  assert.match(html,/aria-expanded="false"/);
  assert.match(html,/aria-controls=/);
  assert.match(html,/展开全文/);
});

test("job details show named settings and grouped timing without leaking internal names", () => {
  const html = renderDetails({kind:"lipsync",snapshot:{draft},tts:{voice_name:"冷淡学长"},stage_history:[timing("forward_template_prepared",0),timing("lipsync_generating",900,"awaiting_resume")]});
  assert.match(html,/冷淡学长/); assert.match(html,/日语/); assert.match(html,/1.2×/);
  assert.match(html,/配音准备/); assert.match(html,/动作匹配/); assert.match(html,/视频生成/); assert.match(html,/成片保存/);
  assert.doesNotMatch(html,/mm-internal-voice-id|forward_template_prepared/);
  assert.doesNotMatch(html,/<details[^>]* open/);
});

test("audio driven jobs and confirmation do not show stale text or unused TTS settings", () => {
  const audioDraft = {...draft,drive:"audio"};
  const jobHtml = renderDetails({kind:"lipsync",snapshot:{draft:audioDraft},audio_duration_seconds:80.15});
  assert.match(jobHtml,/上传音频/); assert.doesNotMatch(jobHtml,/配音确认稿|表达情绪|日语/);
  const confirmation = renderConfirmation(audioDraft);
  assert.match(confirmation,/上传音频/); assert.doesNotMatch(confirmation,/配音确认稿|表达情绪|日语/);
});
