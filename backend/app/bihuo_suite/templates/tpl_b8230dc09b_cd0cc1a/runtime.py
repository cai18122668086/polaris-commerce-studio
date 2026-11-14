"""Variable-source M7 native room/cue/headline application. No native image slot."""
from pathlib import Path
import hashlib,json,math,re,subprocess
from .renderer import encode
from .vendor.pilot import font
def digest(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def lexical(s):return ''.join(c for c in str(s) if c.isalnum())
def wrapped(text,path,size):
    rows=[];row=''
    for ch in text:
        if row and font(path,size).getlength(row+ch)>1000:rows.append(row);row=''
        row+=ch
    if row:rows.append(row)
    if len(rows)>3:raise ValueError('M7 cue exceeds three native reading lines; replan full semantic cue')
    return rows
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
    if tuple(size)!=(1080,1920):raise ValueError('M7 native1080x1920 required')
    source=Path(source_path).resolve()
    if not source.is_file():raise ValueError('Missing source video')
    probe_name=str(Path(ffmpeg).with_name('ffprobe.exe' if str(ffmpeg).endswith('.exe') else 'ffprobe')) if '/' in str(ffmpeg) or '\\' in str(ffmpeg) else 'ffprobe'
    probe=json.loads(subprocess.check_output([probe_name,'-v','error','-show_streams','-of','json',str(source)]));video=next(x for x in probe['streams'] if x['codec_type']=='video');a,b=map(int,video['avg_frame_rate'].split('/'));nfps=a/b;native_count=int(video.get('nb_frames') or round(float(video['duration'])*nfps));frames=round(native_count/nfps*25);duration=frames/25
    options=dict(creative_options or {});path=next((fonts[k] for k in ['body','caption_bold','main','caption'] if fonts.get(k)),str(Path(__file__).parent/'fonts/body.otf'))
    if not Path(path).is_file():raise ValueError('Missing host font')
    font_ref={'path':str(Path(path).resolve()),'sha256':digest(path)}
    tokens=resolved.get('tokens',[])
    if not tokens:raise ValueError('Actual transcript tokens required for native cue/headline clocks')
    by={x['id']:i for i,x in enumerate(tokens)};captions=resolved.get('captions',[])
    if not captions:raise ValueError('Complete semantic captions required')
    cues=[];row_tokens=[]
    for row in captions:
        start,end=map(float,row['time'])
        if not 0<=start<end<=duration+.12:raise ValueError('Cue outside actual source duration')
        if row.get('first_token_id') in by and row.get('last_token_id') in by:ts=tokens[by[row['first_token_id']]:by[row['last_token_id']]+1]
        else:ts=[t for t in tokens if t['start_ms']>=start*1000-.51 and t['end_ms']<=end*1000+.51]
        if not ts or lexical(''.join(t['text'] for t in ts))!=lexical(row['text']):raise ValueError('Cue text must match its actual FA token span')
        exact_start=ts[0]['start_ms'];exact_end=ts[-1]['end_ms'];text=str(row['text']).strip().rstrip('，。！？；：、,.!?;: ')
        if not text:continue
        first=math.ceil(exact_start/40-1e-8);end_frame=math.ceil(exact_end/40-1e-8);settle=min(first+7,max(first,end_frame-1))
        # Recipe policy uses semantic sentence closure, never an old cue number.
        split=bool(re.search(r'[。！？!?]\s*$',row['text'])) and row is not captions[-1]
        if row.get('split_exit') is not None:split=bool(row['split_exit'])
        exit_frame=max(settle,end_frame-3);gone=min(frames,max(exit_frame+3,exit_frame+(25 if split else 6)))
        if gone<=settle:gone=min(frames,settle+1)
        if gone<=settle:continue
        style=row.get('native_style') or ('gold' if len(text)<=6 else 'white')
        if style not in ['gold','white']:raise ValueError('Unknown native M7 cue style')
        spec={'schema':'motion.cue-split-input/1','text':text,'font':font_ref,'style':style,'font_size':113,'outline':4,'shadow':{'enabled':True,'x':2,'y':2,'blur':1},'layout':{'size':[1080,1920],'center_x':540,'caption_top':1557,'line_gap':140,'max_width':1000,'max_lines':3,'lines':wrapped(text,path,113)},'events':{'first':first,'settle':settle,'exit':exit_frame,'gone':gone,'split':exit_frame if split else None},'motion':{'entry_scale_from':.45,'split_distance':100,'split_travel_frames':11 if style=='white' else 13,'split_fade_fraction':.84}}
        cues.append({'component':spec,'fa_interval_ms':[exact_start,exact_end],'token_ids':[ts[0]['id'],ts[-1]['id']],'source_text':row['text'],'split_reason':'actual semantic terminal closure' if split else 'native whole-line exit','explicit_split_override':row.get('split_exit')})
        row_tokens.append(ts)
    opening_end=float(resolved.get('opening_end') or min(2.5,duration*.15));cut=next((math.ceil(c['fa_interval_ms'][0]/40) for c in cues if c['fa_interval_ms'][0]>opening_end*1000+1),frames)
    # Use actual highlighted tail words, retaining the source's graded-size glyph grammar.
    last=captions[-1];ranges=[];cursor=0
    for line in last.get('lines',[]):
        pos=last['text'].find(line.get('text',''),cursor)
        if pos>=0:ranges.extend((pos+a,pos+b) for a,b in line.get('emphasis_spans',[]));cursor=pos+len(line.get('text',''))
    parts=[lexical(last['text'][a:b]) for a,b in ranges[-2:]]
    if not any(parts):parts=[lexical(last['text'])]
    header_text=''.join(parts);header=None
    if options.get('header_enabled',True) and header_text:
        ts=row_tokens[-1];flat=[]
        for token in ts:
            for ch in lexical(token['text']):flat.append((ch,token['start_ms']/40,token['id']))
        selected=[];offset=0
        for part in parts:
            hay=''.join(x[0] for x in flat);pos=hay.find(part,offset)
            if pos<0:raise ValueError('Header words do not match actual cue tokens')
            selected.extend(flat[pos:pos+len(part)]);offset=pos+len(part)
        groups=['primary' if i<len(parts[0]) else 'secondary' for i in range(len(header_text))];raw_width=sum(font(path,220 if group=='primary' else 120).getlength(ch) for ch,group in zip(header_text,groups));scale=min(1,880/max(1,raw_width));sizes={'primary':round(220*scale),'secondary':round(120*scale)}
        if min(sizes.values())<40:raise ValueError('Tail highlighted phrase is too long for native glyph header')
        advances=[float(font(path,sizes[group]).getlength(ch)) for ch,group in zip(header_text,groups)];header={'schema':'motion.glyph-stagger-input/1','text':header_text,'font':font_ref,'glyph_start':[x[1] for x in selected],'size_group':groups,'font_sizes':sizes,'advances':advances,'anchor':{'cursor_x':(1080-sum(advances))/2,'baseline_y':348},'motion':{'entry_lead':1,'entry_tail':2,'angle_from':8,'angle_to':0,'scale_from':.6,'scale_to':1},'whole_exit':[max(0,frames-11),frames],'shadow':{'enabled':True,'x':2,'y':2,'blur':1},'size':[1080,1920]}
    title=str(resolved.get('title','')).strip();identity=options.get('identity') or options.get('name_card') or {}
    ignored=[{'asset_id':m.get('asset_id',m.get('id')),'native_slot':None,'reason':'M7 has no native external image/video slot'} for m in resolved.get('materials',[])]
    return {'schema':'bihuo.m7-production/1','source_path':str(source),'source_sha256':digest(source),'native_fps':nfps,'frames':frames,'duration':duration,'fps':25,'ffmpeg':str(ffmpeg),'size':[1080,1920],'font':font_ref,'captions':captions,'tokens':tokens,'cues':cues,'header':header,'opening_title':title,'opening_exit':[math.ceil(opening_end*25),min(frames,math.ceil(opening_end*25)+8)],'cut_frame':cut,'window_xywh':[97,480,886,884],'identity':{'enabled':identity.get('enabled',True),'name':str(identity.get('name','')).strip(),'description':str(identity.get('description','')).strip()},'native_image_slots':0,'ignored_materials':ignored,'outro':[max(cues[-1]['fa_interval_ms'][1]/1000,duration-.4),duration-.04],'subtitle_policy':'No separate native opening subtitle slot; full spoken captions retained','glyph_clock_policy':'Every glyph uses its actual token start; multi-character tokens share that measured start. Native1frame entry lead may sample10–30ms before FA; no artificial per-character FA subdivision.'}
def render_mp4(cfg,output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);(out/'render-input.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),'utf8');final=encode(cfg,out)
    receipt={'schema':'bihuo.render-receipt/1','final_sha256':digest(final),'final':str(final),'frames':cfg['frames'],'fps':25,'source_sha256':cfg['source_sha256'],'caption_count':len(cfg['cues']),'tokens':len(cfg['tokens']),'images':False,'native_image_slots':0,'ignored_materials':cfg['ignored_materials'],'header_glyphs':cfg['header']['glyph_start'] if cfg['header'] else [],'FA_unmodified':True}
    (out/'render-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8');return final
