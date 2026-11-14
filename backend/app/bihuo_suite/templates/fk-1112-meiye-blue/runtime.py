"""Meiye: original-room white rim, selected complementary split, horizontal history."""
from pathlib import Path
import copy,hashlib,importlib.util,json,math,sys
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageOps
HERE=Path(__file__).resolve().parent
def _load(name,file):
 key='_meiye_production_'+name+'_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:8];s=importlib.util.spec_from_file_location(key,HERE/file);m=importlib.util.module_from_spec(s);sys.modules[key]=m;s.loader.exec_module(m);return m
core=_load('core','core.py');F=_load('shapes','primitives.py');F.font=core.pilot.font;F.visual=core.visual
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920)or not Path(source_path).is_file():raise ValueError('Meiye requires actual portrait video/native1080')
 duration=float(resolved['duration']);f=core._style_fonts(fonts);rows=[];materials=[]
 for i,c in enumerate(resolved.get('captions',[])):
  a,b=map(float,c.get('time',[c.get('start'),c.get('end')]))
  if not 0<=a<b<=duration+.05:raise ValueError('FA caption outside actual duration')
  rows.append(dict(id=f'FA{i+1:02}',text=c['text'],lines=copy.deepcopy(c.get('lines')or[dict(text=c['text'],emphasis_spans=[])]),time=[a,b],split_start=None,split_end=None,bold=False))
 if not rows:raise ValueError('Complete host FA captions required')
 for i,m in enumerate(resolved.get('materials',[])):
  span=m.get('spoken_span')or{};a=max(float(m['start']),float(span.get('start',m['start'])));b=min(float(m['end']),float(span.get('end',m['end'])),duration)
  if b<=a:continue
  if not Path(m['path']).is_file()or(m.get('sha256')and core._sha(m['path'])!=m['sha256']):raise ValueError('Actual matched resource missing/SHA mismatch')
  materials.append(dict(asset_id=m['asset_id'],slot_id=f"{m['asset_id']}-{i}",path=m['path'],kind=m.get('kind','image'),start=a,end=b,spoken_span=span,reference=False))
 opening_end=float(resolved.get('opening_end')or min(3,duration*.15));anchors=[opening_end]+[m['end']for m in materials]
 if resolved.get('quote_start')is not None:anchors.append(float(resolved['quote_start']))
 for anchor in anchors:
  cue=next((r for r in reversed(rows)if r['time'][1]<=anchor+.05),None)
  if cue and cue is not rows[-1]:cue['split_start']=cue['time'][1];cue['split_end']=min(duration,cue['time'][1]+.4)
 opt=creative_options or{};card=opt.get('name_card')or opt.get('identity')or{};identity=dict(enabled=bool(card.get('enabled',False)),name=core._text(card.get('name')),description=core._text(card.get('description')))
 return dict(schema='bihuo.meiye.production/1',template_id='fk-1112-meiye-blue',source_path=str(source_path),source_sha256=core._sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(rows[-1]['time'][1]*25)),fps=25,size=list(size),ffmpeg=str(ffmpeg),fonts=dict(title=f['title'],caption=f['caption']),title=core._text(opt.get('title'))or core._text(resolved.get('title')),subtitle=core._text(opt.get('subtitle'))or core._text(resolved.get('subtitle')),opening_end=opening_end,identity=identity,captions=rows,materials=materials,reference_mode=False,tail_fade=[max(0,duration-.52),duration],history_policy='First reading picture retires; gallery pictures retain up to2 actual preceding examples when later matched picture arrives, never extending spoken FA.',limits=['Selected complete cues split into complementary halves; visualoutro may continue after FA, FA time stays unchanged.','History activates only when enough actual later gallery resources exist; no empty cells or upload quotas.','Original UV/font/split residual/ease remain candidates.'])
@lru_cache(maxsize=1)
def gradient():return Image.open(HERE/'gradient.png').convert('RGBA')
def _active(cfg,t):return next((i for i,m in enumerate(cfg['materials'])if m['start']<=t<m['end']),None)
def _pose(cfg,n):
 t=n/25;initial=np.array([92,408,988,1196],float)
 if cfg.get('reference_mode'):
  q=F.out(157,176,n);box=initial*(1-q)+np.array([392,1166,688,1558])*q
  if n>=267:box=np.array([392,1166,688,1558])*(1-F.out(267,282,n))+np.array([282,1166,798,1558])*F.out(267,282,n)
  return [round(v)for v in box]
 for i,m in reversed(list(enumerate(cfg['materials']))):
  if m['start']-.16<=t<m['end']+.6:
   target=np.array([392,1166,688,1558]if i==0 else[282,1166,798,1558]);q=F.out(m['start']-.16,m['start']+.4,t)*(1-F.out(m['end'],m['end']+.6,t));return [round(v)for v in(initial*(1-q)+target*q)]
 return initial.round().astype(int).tolist()
def _person(cfg,n,box):
 raw=core.media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGB')
 if cfg.get('reference_mode'):
  frame=np.asarray(raw).copy();mask=np.zeros((1920,1080),np.uint8);mask[1510:1605,200:900]=255;frame=cv2.inpaint(frame,mask,3,cv2.INPAINT_TELEA);x,y,z,w=box;raw=Image.fromarray(frame).crop((x+4,y+4,z-4,w-4));return F.window(raw,box,source_plate=True)
 return F.window(raw,box,uv=1)
def _gallery(cfg,n):
 t=n/25;roles={};mats=cfg['materials'];last_end=max([m['end']for m in mats]+[0]);gallery=[(i,m)for i,m in enumerate(mats)if i>0]
 for i,m in enumerate(mats):
  later=next((r for j,r in enumerate(mats)if j>i),None);q=F.out(m['start'],m['start']+.4,t);alpha=q;box=[54,126,1022,1118]if i==0 else[44,96,1036,1122]
  if i==0:
   if not m['start']<=t<m['end']:continue
   alpha*=1-F.clamp((t-(m['end']-.48))/.48)
  else:
   past=[(j,r)for j,r in gallery if j<i and r['start']<=t];history=[]
   if later and t>=later['start']:
    newest=max(j for j,r in gallery if r['start']<=t);previous=[(j,r)for j,r in gallery if j<newest][-2:]
    if i not in[j for j,_ in previous]or t>=last_end:continue
    slot=[j for j,_ in previous].index(i);target=[44+506*slot,698,532+506*slot,1124];origin=[44,96,1036,1122]if i==1 else[44,96,1036,682];z=F.out(later['start'],later['start']+.56,t);box=F.boxmix(origin,target,z);alpha=1
   elif m['start']<=t<m['end']:
    if past:box=[44,96,1036,682]
    alpha*=1-F.clamp((t-(m['end']-.4))/.4)if not later else 1
   else:continue
  x,y,z,w=box;entry=dict(id=m['slot_id'],path=m['path'],type=m['kind'],start_frame=0,source_in=0,speed=1,end_policy='hold',fit='contain',rect=[x/2,y/2,z/2,w/2],radius=8 if i==0 else 18,entry_frames=0,audio='muted');im=next(iter(core.media.render('V03',None,n,dict(size=[1080,1920],fps=25,media_entries=[entry])).values()));roles['material-'+m['slot_id']]=F.op(im,alpha)
 return roles
def _caption(cfg,n):
 roles={k:F.blank()for k in['caption-upper','caption-lower','caption-reading']};t=n/25
 for cue in cfg['captions']:
  a,b=cue['time'];split=cue.get('split_start');end=cue.get('split_end')or b;tail=split is not None and split<=t<end
  if not(a<=t<b or tail):continue
  q=min(1,max(0,(t-a+.04)/.16));distance=0;split_now=tail
  if tail:
   dt=(t-split)*25+1;distance=min(86,round(.6*dt*dt));q=max(.018,(1-F.clamp((t-split)/max(.04,end-split)))**1.5)
  elif not cue.get('reference',False):q*=min(1,max(0,(b-t)/.08))
  lines=cue['lines'];top=1519 if cfg.get('reference_mode')else 1630;body=F.blank()
  for j,line in enumerate(lines):
   text=line['text']if isinstance(line,dict)else line;spans=line.get('emphasis_spans',[])if isinstance(line,dict)else[];size=68 if cue.get('bold')else 64
   path=cfg['fonts']['title']if cue.get('bold')else cfg['fonts']['caption'];line_top=top-(len(lines)-1)*38+j*76
   if core.pilot.font(path,size).getlength(text)>1000:raise ValueError('Meiye caption requires host semantic line break')
   line_layer=F.blank();F.place_text(line_layer,text,path,size,line_top,spans=spans,stroke=2,alpha=q)
   if split_now:
    upper,lower=F.split_rgba(line_layer,line_top+32,0,distance);roles['caption-upper'].alpha_composite(upper);roles['caption-lower'].alpha_composite(lower)
   else:roles['caption-reading'].alpha_composite(line_layer)
 return roles
def _headings(cfg,n):
 out={k:F.blank()for k in['title-main','title-support','identity']};t=n/25;q=F.clamp((t+.04)/.4)*(1-F.clamp((t-(cfg['opening_end']-.2))/.2))
 for role,text,size,top,spans in[('title-main',cfg['title'],108,176,[]),('title-support',cfg['subtitle'],58,308,[(0,len(cfg['subtitle']))])]:
  if not text or q<=0:continue
  while size>32 and core.pilot.font(cfg['fonts']['title'],size).getlength(text)>1000:size-=1
  F.place_text(out[role],text,cfg['fonts']['title'],size,top,spans=spans,stroke=0,slant=.13,alpha=q)
 card=cfg['identity'];d=ImageDraw.Draw(out['identity'])
 if card['enabled']and q>0:
  for text,y,point,bg,fg in[(card['name'],1222,56,(255,217,0,255),(5,4,8,255)),(card['description'],1306,34,(9,8,14,175),(255,255,255,255))]:
   if not text:continue
   tile=core.pilot.text_image(text,cfg['fonts']['title'],point,fg)[0];ink=tile.getchannel('A').getbbox();tile=tile.crop(ink);width=tile.width+24
   if width>980:raise ValueError('Identity requires shorter explicit text')
   d.rectangle((44,y,44+width,y+tile.height+24),fill=bg);out['identity'].alpha_composite(tile,(56,y+12))
  out['identity']=F.op(out['identity'],q)
 return out
def render_layers(cfg,n):
 box=_pose(cfg,n);roles=dict(background=gradient().copy(),**_gallery(cfg,n),presenter=_person(cfg,n,box),**_headings(cfg,n),**_caption(cfg,n));roles['whole_scene_black']=Image.new('RGBA',(1080,1920),(0,0,0,round(255*core.pilot.ease(*cfg['tail_fade'],n/25))));return roles,dict(frame=n,presenter_box=box,active_asset_ids=[m['asset_id']for m in cfg['materials']if m['start']<=n/25<m['end']],history_excludes_first_reading=True,available_materials=len(cfg['materials']))
def composite(roles):
 out=F.blank()
 for im in roles.values():out.alpha_composite(im)
 return out.convert('RGB')
core.render_layers=render_layers;core.composite=composite
def render_mp4(cfg,output_dir):return core.render_mp4(cfg,output_dir)
