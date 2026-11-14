"""Navy news: true ticker, skew room window, current/history photos, arch closing."""
from pathlib import Path
import copy,hashlib,importlib.util,json,math,sys
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageOps
HERE=Path(__file__).resolve().parent
def _load(name,file):
 key='_navy_production_'+name+'_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:8];s=importlib.util.spec_from_file_location(key,HERE/file);m=importlib.util.module_from_spec(s);sys.modules[key]=m;s.loader.exec_module(m);return m
core=_load('core','core.py');F=_load('shapes','primitives.py');F.text_image=core.pilot.text_image;F.font=core.pilot.font;F.ease=core.pilot.ease;F.V=core.visual;F.T=F
OPEN=np.array([[74,382],[1007,382],[1007,1308],[74,1308]],float);SKEW=np.array([[433,1178],[688,1178],[647,1568],[392,1568]],float);ARCH=np.array([[250,1120],[831,1120],[831,1765],[250,1765]],float)
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920)or not Path(source_path).is_file():raise ValueError('Navy requires actual portrait video/native1080')
 duration=float(resolved['duration']);rows=[];materials=[];f=core._style_fonts(fonts)
 for c in resolved.get('captions',[]):
  a,b=map(float,c.get('time',[c.get('start'),c.get('end')]))
  if not 0<=a<b<=duration+.05:raise ValueError('Caption outside actual FA duration')
  lines=c.get('lines')or[dict(text=c['text'],emphasis_spans=[])];ranges=[];offset=0
  for line in lines:
   if isinstance(line,dict):ranges.extend([[a+offset,b+offset]for a,b in line.get('emphasis_spans',[])]);offset+=len(line['text'])
   else:offset+=len(line)
  rows.append(dict(text=c['text'],time=[a,b],frames=[math.ceil(a*25),math.ceil(b*25)],lines=copy.deepcopy(lines),emphasis_spans=ranges))
 if not rows:raise ValueError('Complete host FA caption rows required')
 for i,m in enumerate(resolved.get('materials',[])):
  span=m.get('spoken_span')or{};a=max(float(m['start']),float(span.get('start',m['start'])));b=min(float(m['end']),float(span.get('end',m['end'])),duration)
  if a>=b:continue
  if not Path(m['path']).is_file()or(m.get('sha256')and core._sha(m['path'])!=m['sha256']):raise ValueError('Actual matched resource missing/SHA mismatch')
  materials.append(dict(asset_id=m['asset_id'],slot_id=f"{m['asset_id']}-{i}",path=m['path'],kind=m.get('kind','image'),start=a,end=b,spoken_span=span,visual_retention=[]))
 for i,m in enumerate(materials[:-1]):m['visual_retention']=[dict(start=m['end'],end=materials[-1]['end'],role='previous teaching example; FA/spoken span unchanged')]
 opts=creative_options or{};title=core._text(opts.get('title'))or core._text(resolved.get('title'));features=resolved.get('features')or resolved.get('points')or[];items=[core._text(r['text'])for r in(resolved.get('points')or features)]
 if not items:items=[c['text'].strip('，。！？,.!?')for c in rows]
 closing_start=float(features[0]['start'])-.24 if features else float(resolved.get('quote_start')or duration*.78)-.24;button=core._text(features[-1]['text'])if features else core._text(((resolved.get('conclusion')or{}).get('first')or{}).get('text'));button_at=float(features[-1]['start'])if features else closing_start+.92;card=opts.get('name_card')or opts.get('identity')or{}
 return dict(schema='bihuo.navy.production/1',template_id='fk-1028-news-navy',source_path=str(source_path),source_sha256=core._sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(rows[-1]['time'][1]*25)),fps=25,size=list(size),ffmpeg=str(ffmpeg),mode='clean',fonts=dict(body=f['caption'],identity=fonts.get('identity')or f['caption'],ticker=fonts.get('ticker')or f['title'],live=fonts.get('live')or f['title']),captions=rows,materials=materials,ticker=dict(enabled=bool(items),items=items),ticker_size=30,ticker_entry_frame=5,scroll_delay_frames=0,body_size=66,body_shear=.12,identity=dict(enabled=bool(card.get('enabled',False)),name=core._text(card.get('name')),description=core._text(card.get('description'))),identity_end=float(resolved.get('opening_end')or 3),title=title,closing=dict(start=closing_start,button=button,button_at=button_at,pale_at=button_at+.48,enabled=bool(title or button)),tail_fade=[max(0,duration-.48),duration],reference_mode=False,limits=['Source ticker measured1104px is not universal; current font/text actual advances define each cycle.','Matched photo retains only previous-example visual history; original semantic and FA times remain unchanged.','Original room window, no isolated human/head matte.','Source fully occluded topic glyphs/author raw and exact arch/ease remain unknown.'])
def _state(cfg,n):
 t=n/25;closing=cfg['closing'];qarch=core.pilot.ease(closing['start']+.12,closing['start']+.6,t)if closing['enabled']else 0
 if not cfg.get('reference_mode')and closing['enabled']:qarch=core.pilot.ease(closing['start']-.64,closing['start'],t)
 if cfg.get('reference_mode'):
  if n<114:poly=OPEN.copy();q=0
  elif n<=140:poly=np.array(cfg['reference_poses'][str(n)]['polygon']);q=core.pilot.ease(114,140,n)
  elif n<150:poly=np.array([[432,1178],[688,1178],[647,1570],[391,1570]])*(1-core.pilot.ease(140,150,n))+SKEW*core.pilot.ease(140,150,n);q=1
  else:poly=SKEW.copy();q=1
 else:
  first=min([m['start']for m in cfg['materials']]+[cfg['duration']+1]);end=max([m['end']for m in cfg['materials']]+[0]);q=core.pilot.ease(first-.76,first+.28,t)*(1-core.pilot.ease(end,end+.6,t))if cfg['materials']else 0;poly=OPEN*(1-q)+SKEW*q
 if qarch>0:poly=poly*(1-qarch)+ARCH*qarch
 return poly,q,qarch
@lru_cache(maxsize=8)
def _bg(active,closing):
 yy=np.arange(1920)[:,None,None]/1919;top=np.array([5,12,27])*(1-active)+np.array([18,40,84])*active;bottom=np.array([2,6,16])*(1-active)+np.array([7,14,36])*active;top=top*(1-closing)+np.array([5,12,27])*closing;bottom=bottom*(1-closing)+np.array([2,6,16])*closing;arr=np.broadcast_to(top*(1-yy)+bottom*yy,(1920,1080,3)).copy();arr[:,::60]+=np.array([14,18,25]);arr[::60]+=np.array([14,18,25]);return Image.fromarray(np.uint8(np.clip(arr,0,255))).convert('RGBA')
def _archmask(poly):
 x,y=poly[0];z,w=poly[2];bw=max(1,round(z-x));bh=max(1,round(w-y));m=Image.new('L',(bw,bh));d=ImageDraw.Draw(m);r=min(bw//2,bh);d.ellipse((0,0,bw-1,bw-1),fill=255);d.rounded_rectangle((0,r,bw-1,bh-1),radius=20,fill=255);d.rectangle((0,r,bw-1,max(r,bh-21)),fill=255);mask=Image.new('L',(1080,1920));mask.paste(m,(round(x),round(y)));return mask
def _person(cfg,n,poly,q,qarch):
 raw=core.media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGB');x,y=poly[0];width=poly[1,0]-x;height=poly[3,1]-y;shear=poly[3,0]-x;bw=max(1,round(width));bh=max(1,round(height));mask=F.quadmask(poly,30*(1-q)+16*q)
 if qarch>0:mask=Image.blend(mask,_archmask(poly),qarch)
 if cfg.get('reference_mode'):
  if 114<=n<=140 and cfg.get('reference_texture_stream'):texture=core.media._sample(dict(path=cfg['reference_texture_stream'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n-114,25).convert('RGB')
  else:
   a=np.asarray(raw).copy()
   if qarch>0:
    repair=np.zeros((1920,1080),np.uint8);repair[1560:1730,100:980]=255;a=cv2.inpaint(a,repair,3,cv2.INPAINT_TELEA)
   target=np.float32([[0,0],[bw,0],[bw,bh],[0,bh]]);source=np.float32(poly);matrix=cv2.getPerspectiveTransform(source,target);texture=Image.fromarray(cv2.warpPerspective(a,matrix,(bw,bh),borderMode=cv2.BORDER_REPLICATE)).resize((1080,1920),Image.Resampling.LANCZOS)
 else:
  ratio=max(.2,width/max(height,1));h=min(raw.height,raw.height*1080/1920);w=h*ratio;xx=(raw.width-w)/2;yy=raw.height*400/1920;texture=raw.crop((round(xx),round(yy),round(xx+w),round(yy+h))).resize((1080,1920),Image.Resampling.LANCZOS)
 key=dict(time=0,matrix=[[width/1080,shear/1920,x/2],[0,height/1920,y/2]],rect=[float(poly[:,0].min()/2),float(poly[:,1].min()/2),float(poly[:,0].max()/2),float(poly[:,1].max()/2)],radius=0,background_opacity=0);person=core.visual.render('V02',texture,0,dict(size=[1080,1920],fps=25,visual_keys=[key]))['presenter'];person.putalpha(mask.filter(ImageFilter.MinFilter(7)));border=Image.new('RGBA',(1080,1920),(250,250,249,0));border.putalpha(mask);back=Image.new('RGBA',(1080,1920),(239,113,48,0));shift=Image.new('L',(1080,1920));shift.paste(mask,(16,16));back.putalpha(shift.point(lambda z:round(z*.82)));glow=Image.new('RGBA',(1080,1920),(255,118,35,0));glow.putalpha(mask.filter(ImageFilter.GaussianBlur(25)).point(lambda z:round(z*1.3*(1-q))));return dict(backing=back,glow=glow,border=border,presenter=person)
def _photo(m,n,box,opacity):
 x,y,z,w=box;bw=max(1,round(z-x));bh=max(1,round(w-y));raw=core.media._sample(dict(path=m['path'],type=m['kind'],start_frame=math.ceil(m['start']*25),source_in=0,speed=1,end_policy='hold'),n,25).convert('RGBA');fill=core.media._fit(raw,bw,bh,dict(fit='cover')).filter(ImageFilter.GaussianBlur(18));fill.alpha_composite(core.media._fit(raw,bw,bh,dict(fit='contain')));mask=Image.new('L',(bw,bh));ImageDraw.Draw(mask).rounded_rectangle((0,0,bw-1,bh-1),radius=30,fill=255);fill.putalpha(mask);out=F.blank();out.alpha_composite(fill,(round(x),round(y)));return F.opacity(out,opacity)
def _gallery(cfg,n):
 t=n/25;mats=cfg['materials'];roles={};lastend=max([m['end']for m in mats]+[0]);current=next((i for i,m in reversed(list(enumerate(mats)))if m['start']<=t<lastend),None)
 if current is None:return roles
 for i,m in enumerate(mats):
  if i>current or i<current-2:continue
  if i==current:box=[47,312,1034,1135]if i==0 else[47,312,1034,790];q=core.pilot.ease(m['start']-.04,m['start']+.32,t);q*=1-core.pilot.ease(lastend-.44,lastend,t)
  else:
   nextm=mats[i+1];slot=i-max(0,current-2);target=[47,810,523,1140]if slot==0 else[545,810,1034,1140];origin=[47,312,1034,1135]if i==0 else[47,312,1034,790];p=core.pilot.ease(nextm['start'],nextm['start']+.44,t);box=(np.array(origin)*(1-p)+np.array(target)*p).tolist();q=1-core.pilot.ease(lastend-.44,lastend,t)
  roles['material-'+m['slot_id']]=_photo(m,n,box,q)
 return roles
def _closing(cfg,n):
 out={k:F.blank()for k in['closing_card','closing_label','closing_button']};c=cfg['closing'];t=n/25
 if not c['enabled']:return out
 q=core.pilot.ease(c['start'],c['start']+.28,t)
 if q<=0:return out
 ImageDraw.Draw(out['closing_card']).rounded_rectangle((72,461,1008,823),radius=36,fill='white');title=cfg['title'];point=48
 while point>24 and core.pilot.font(cfg['fonts']['body'],point).getlength(title)>820:point-=1
 if title:
  tile=F.tile(title,cfg['fonts']['body'],point,(10,31,53,255));out['closing_label'].alpha_composite(tile,(round(540-tile.width/2),558))
 bq=core.pilot.ease(c['button_at'],c['button_at']+.32,t);state=core.pilot.ease(c['pale_at'],c['pale_at']+.16,t)
 if c['button']and bq>0:
  tile=F.tile(c['button'],cfg['fonts']['body'],32,(10,31,53,255));width=max(260,tile.width+64);button=Image.new('RGBA',(width,84));color=tuple(round(a+(b-a)*state)for a,b in zip((239,113,48,255),(241,232,216,255)));ImageDraw.Draw(button).rounded_rectangle((0,0,width-1,83),radius=20,fill=color);button.alpha_composite(tile,((width-tile.width)//2,(84-tile.height)//2));out['closing_button'].alpha_composite(F.opacity(button,bq),(round(540-width/2),686))
 return {k:F.opacity(v,q)for k,v in out.items()}
def _captions(cfg,n):
 row=next((c for c in cfg['captions']if c['frames'][0]<=n<c['frames'][1]),None)
 if not row or len(row.get('lines',[]))<=1:return F.captions(cfg,n)[0]
 out={k:F.blank()for k in['caption_body','caption_emphasis','caption_outline','caption_shadow']}
 for i,line in enumerate(row['lines']):
  c=dict(row,text=line['text'],emphasis_spans=line.get('emphasis_spans',[]));local=dict(cfg,captions=[c]);roles,_=F.captions(local,n)
  for k,v in roles.items():out[k].alpha_composite(v,(0,round(-(len(row['lines'])-1)*44+i*88)))
 return out
def render_layers(cfg,n):
 poly,q,qarch=_state(cfg,n);photos=_gallery(cfg,n);person=_person(cfg,n,poly,q,qarch);closer=_closing(cfg,n);caps=_captions(cfg,n);ticker,_=F.ticker(cfg,n);identity,_=F.identity(cfg,n);roles=dict(background=_bg(round(q,2),round(qarch,2)).copy(),**photos,**closer,**person,identity=identity,caption_shadow=caps['caption_shadow'],caption_outline=caps['caption_outline'],caption_body=caps['caption_body'],caption_emphasis=caps['caption_emphasis'],**ticker);roles['whole_scene_black']=Image.new('RGBA',(1080,1920),(0,0,0,round(255*core.pilot.ease(*cfg['tail_fade'],n/25))));return roles,dict(frame=n,polygon=poly.tolist(),arch=qarch,active_asset_ids=[m['asset_id']for m in cfg['materials']if m['start']<=n/25<m['end']],visual_history_ids=[m['asset_id']for m in cfg['materials']if m['end']<=n/25 and m['visual_retention']],ticker_cycle_is_actual_text_width=True)
def composite(roles):
 out=F.blank()
 for im in roles.values():out.alpha_composite(im)
 return out.convert('RGB')
core.render_layers=render_layers;core.composite=composite
def render_mp4(cfg,output_dir):return core.render_mp4(cfg,output_dir)
