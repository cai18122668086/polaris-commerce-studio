"""Purple Neon full expression: agenda, tilted media, abilities and tool UI."""
from pathlib import Path
import copy,hashlib,importlib.util,json,math,sys
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageOps
HERE=Path(__file__).resolve().parent
def _load(name,file):
 key='_neon_production_'+name+'_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:8]
 spec=importlib.util.spec_from_file_location(key,HERE/file);module=importlib.util.module_from_spec(spec);sys.modules[key]=module;spec.loader.exec_module(module);return module
core=_load('core','core.py');F=_load('shapes','primitives.py');F.font=core.pilot.font;F.text_image=core.pilot.text_image;F.ease=core.pilot.ease;F.V=core.visual
STYLE=json.loads((HERE/'style.json').read_text('utf8'));W,H=1080,1920
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920)or not Path(source_path).is_file():raise ValueError('Actual1080portrait source/host font inputs required')
 duration=float(resolved['duration']);tokens=resolved.get('tokens',[]);index={v['id']:i for i,v in enumerate(tokens)};caps=[]
 for c in resolved.get('captions',[]):
  a,b=map(float,c.get('time',[c.get('start'),c.get('end')]))
  if not 0<=a<b<=duration+.05:raise ValueError('Actual caption clock outside source')
  lines=c.get('lines')or[dict(text=c['text'],emphasis_spans=[])];text=''.join(v['text']if isinstance(v,dict)else v for v in lines);ranges=[];offset=0
  for line in lines:
   if isinstance(line,dict):ranges.extend([[a+offset,b+offset]for a,b in line.get('emphasis_spans',[])]);offset+=len(line['text'])
   else:offset+=len(line)
  caps.append(dict(text=text,lines=copy.deepcopy(lines),frames=[math.ceil(a*25),math.ceil(b*25)],time=[a,b],emphasis_spans=ranges,emphasis_token_spans=copy.deepcopy(c.get('emphasis_token_spans',[]))))
 if not caps:raise ValueError('Complete actual FA captions required')
 f=core._style_fonts(fonts);f=dict(body=f['caption'],caption_body=f['caption'],accent=fonts.get('accent')or f['title'],pill=fonts.get('pill')or f['title'],name=fonts.get('name')or f['title'])
 for path in f.values():
  if not Path(path).is_file():raise ValueError('Actual role font missing')
 materials=[]
 for i,m in enumerate(resolved.get('materials',[])):
  span=m.get('spoken_span')or{};a=max(float(m['start']),float(span.get('start',m['start'])));b=min(float(m['end']),float(span.get('end',m['end'])),duration)
  if b<=a:continue
  if not Path(m['path']).is_file()or(m.get('sha256')and core._sha(m['path'])!=m['sha256']):raise ValueError('Actual matched asset missing/SHA mismatch')
  keywords=[c['text'][lo:hi]for c in caps if a-.05<=c['time'][0]<b for lo,hi in c['emphasis_spans']]
  materials.append(dict(asset_id=m['asset_id'],slot_id=f"{m['asset_id']}-{i}",path=m['path'],kind=m.get('kind','image'),start=a,end=b,spoken_span=span,footer=span.get('text')or m.get('spoken_text',''),conclusion=keywords[0]if keywords else''))
 options=creative_options or{};title=core._text(options.get('title'))or core._text(resolved.get('title'));subtitle=core._text(options.get('subtitle'))or core._text(resolved.get('subtitle'));opening_end=float(resolved.get('opening_end')or min(duration*.17,3));agenda=[]
 for i,text in enumerate([title,subtitle]):
  if not text:continue
  point=48 if i==0 else 40
  while point>24 and core.pilot.font(f['pill'],point).getlength(text)>740:point-=1
  if core.pilot.font(f['pill'],point).getlength(text)>740:raise ValueError('Agenda needs semantic shorter host phrase')
  agenda.append(dict(text=text,icon='robot'if i==0 else'laptop',first=round((.16+i*.55)*25),steady=round((.4+i*.55)*25),lime=i==1,center=[250 if i==0 else 650,245 if i==0 else 350],size=point,angle=6 if i==0 else -5))
 conclusion=resolved.get('conclusion')or{};first=conclusion.get('first')or{};second=conclusion.get('second')or{};tool_start=float(first.get('start',resolved.get('quote_start')or duration*.80))-.24;tool_text=core._text(second.get('text'));support=core._text(first.get('text'));button=core._text(first.get('text'));abilities=copy.deepcopy(resolved.get('features')or resolved.get('points')or[])
 if not abilities:
  last_material=max([m['end']for m in materials]+[opening_end,duration*.5])
  for c in caps:
   if not last_material<=c['time'][0]<tool_start:continue
   for span in c['emphasis_token_spans']:
    a=index.get(span['first_token_id']);b=index.get(span['last_token_id'])
    if a is None or b is None:continue
    ts=tokens[a:b+1];text=''.join(v['text']for v in ts).strip('，。！？,.!?')
    abilities.append(dict(text=text,start=ts[0]['start_ms']/1000,end=ts[-1]['end_ms']/1000))
 if len(abilities)>6:raise ValueError('Neon ability payload needs explicit pagination beyond6 readable rows')
 card=options.get('name_card')or options.get('identity')or{};identity=dict(enabled=bool(card.get('enabled',False)),name=core._text(card.get('name')),description=core._text(card.get('description')))
 cfg=dict(schema='bihuo.neon.production/1',template_id='fk-1102-brief-neon',source_path=str(source_path),source_sha256=core._sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(caps[-1]['time'][1]*25)),fps=25,size=list(size),ffmpeg=str(ffmpeg),fonts=f,captions=caps,materials=materials,agenda=agenda,agenda_exit=[round(opening_end*25),round((opening_end+.3)*25)],identity=identity,identity_clock=[2,10,max(12,round(opening_end*25))],warm0=False,abilities=abilities,tool=dict(start=tool_start,support=support,main=tool_text,button=button,support_at=float(first.get('start',tool_start+.16)),main_at=float(second.get('start',tool_start+.4)),button_at=float(second.get('start',tool_start+.4))+.44),tail_fade=[max(0,duration-.52),duration],reference_mode=False,limits=['New6row ability capacity uses explicit reflow; original reference3row profile is retained for source.','No uploaded image count requirement; meaningful tool-card words act independently of materials.','Exact author grow/glow curves and font identities remain candidate.'])
 return cfg
@lru_cache(maxsize=1)
def _grid_base():
 p=STYLE['grid'];yy=np.arange(H);colors=np.array([np.interp(yy,p['y'],[c[k]for c in p['colors']])for k in range(3)]).T;arr=np.repeat(colors[:,None,:],W,axis=1).astype(np.uint8);return arr
def grid(n):
 arr=_grid_base().copy();p=STYLE['grid'];xs=np.arange(p.get('phase_x',0)%60,W,60).round().astype(int);ys=np.arange((p.get('phase_y',34)+p.get('velocity_y',0)*n)%60,H,60).round().astype(int);xs=xs[xs<W];ys=ys[ys<H];arr[:,xs,:]=np.minimum(arr[:,xs,:].astype(int)+14,255);arr[ys,:,:]=np.minimum(arr[ys,:,:].astype(int)+14,255);return Image.fromarray(arr).convert('RGBA')
def _pose(cfg,n):
 t=n/25;full=np.array([0,0,1080,1920],float);small=np.array([725,148,1015,535],float);tool=cfg['tool'];has_tool=bool(tool['support']or tool['main']or tool['button'])
 if cfg.get('reference_mode'):
  if n<=277:
   q=cfg['reference_poses'][str(n)];return q['box'],q['radius']
  if n<334:return full.tolist(),20
  q=F.ease(334,350,n);box=full*(1-q)+np.array([348,1183,732,1567])*q;return box.tolist(),20+172*q
 if has_tool and t>=tool['start']:
  q=F.ease(tool['start'],tool['start']+.64,t);return(full*(1-q)+np.array([348,1183,732,1567])*q).tolist(),20+172*q
 for m in reversed(cfg['materials']):
  if m['start']-.16<=t<m['end']+.72:
   q=F.ease(m['start']-.16,m['start']+.88,t)*(1-F.ease(m['end'],m['end']+.72,t));return(full*(1-q)+small*q).tolist(),20+10*q
 return full.tolist(),20
def _presenter(cfg,n,box,radius):
 raw=core.media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGB');x,y,z,w=box;bw=max(1,round(z-x));bh=max(1,round(w-y))
 if cfg.get('reference_mode'):
  recovery=Path(cfg['reference_recovery']);candidates=[recovery/f'agenda-revised-textures/f{n:04}.png',recovery/f'revised-textures/f{n:04}.png',recovery/f'textures/f{n:04}.png']
  if n<=277 and any(p.exists()for p in candidates):texture=Image.open(next(p for p in candidates if p.exists())).convert('RGB')
  else:
   frame=np.asarray(raw).copy()
   if n<334:
    mask=np.zeros((1920,1080),np.uint8);mask[160:550,20:750]=255;frame=cv2.inpaint(frame,mask,3,cv2.INPAINT_TELEA)
    mask[:]=0;mask[1580:1710,80:1000]=255;frame=cv2.inpaint(frame,mask,3,cv2.INPAINT_TELEA)
   texture=Image.fromarray(frame).crop((round(x)+4,round(y)+4,round(z)-4,round(w)-4)).resize((W,H),Image.Resampling.LANCZOS)
 else:texture=ImageOps.fit(raw,(bw,bh),method=Image.Resampling.LANCZOS,centering=(.5,.5)).resize((W,H),Image.Resampling.LANCZOS)
 key=dict(time=0,matrix=[[(z-x)/W,0,x/2],[0,(w-y)/H,y/2]],rect=[v/2 for v in box],radius=radius/2,background_opacity=0);person=core.visual.render('V02',texture,0,dict(size=[W,H],fps=25,visual_keys=[key]))['presenter'];stroke=F.blank();ImageDraw.Draw(stroke).rounded_rectangle(tuple(box),radius=radius,outline=F.CYAN,width=4);alpha=1 if box[0]>1 else 0;stroke=F.op(stroke,alpha);glow=Image.new('RGBA',(W,H),F.CYAN[:3]+(0,));glow.putalpha(stroke.getchannel('A').filter(ImageFilter.GaussianBlur(12)));return person,stroke,glow
def _material(cfg,n):
 out=F.blank();support=F.blank();con=F.blank();t=n/25
 for m in cfg['materials']:
  if not m['start']<=t<m['end']:continue
  q=F.ease(m['start']-.04,m['start']+.24,t);fade=1-F.ease(m['end']-.24,m['end'],t);panel=Image.new('RGBA',(790,638));ImageDraw.Draw(panel).rounded_rectangle((0,0,789,637),radius=35,fill='white');entry=dict(id=m['slot_id'],path=m['path'],type=m['kind'],start_frame=math.ceil(m['start']*25),source_in=0,speed=1,end_policy='hold',fit='contain',rect=[0,0,375,270],radius=0,entry_frames=0,audio='muted');im=next(iter(core.media.render('V03',None,n,dict(size=[W,H],fps=25,media_entries=[entry])).values())).crop((0,0,750,540));panel.alpha_composite(im,(20,20));foot=Image.new('RGBA',(790,638));F.put(foot,m['footer'],cfg['fonts']['body'],26,(105,105,105,255),(29,588));F.place(out,panel,(446-80*(1-q),650),.9+.1*q,q*fade,3,blur=(1-fade)*6);F.place(support,foot,(446-80*(1-q),650),.9+.1*q,q*fade,3,blur=(1-fade)*6)
  text=m['conclusion']
  if text:
   tile=F.tile(text,cfg['fonts']['pill'],34,(0,0,0,255));pill=Image.new('RGBA',(tile.width+112,82));ImageDraw.Draw(pill).rounded_rectangle((0,0,pill.width-1,81),radius=41,fill=F.LIME);pill.alpha_composite(F.icon('gear',31),(29,25));pill.alpha_composite(tile,(77,(82-tile.height)//2));g=F.ease(m['start']+.64,m['start']+.88,t);F.place(con,pill,(269,861),g,g*fade)
 return out,support,con
def _abilities(cfg,n):
 out=F.blank();t=n/25;end=cfg['tool']['start'];rows=cfg['abilities'];gap=min(96,440/max(1,len(rows)))
 for i,row in enumerate(rows):
  q=F.ease(float(row['start'])-.04,float(row['start'])+.2,t)*(1-F.ease(end-.24,end,t))
  if q<=0:continue
  text=core._text(row['text']);point=34
  while point>22 and core.pilot.font(cfg['fonts']['pill'],point).getlength(text)>740:point-=1
  tile=F.tile(text,cfg['fonts']['pill'],point,(106,47,233,255));pill=Image.new('RGBA',(tile.width+98,76));ImageDraw.Draw(pill).rounded_rectangle((0,0,pill.width-1,75),radius=38,fill='white');pill.alpha_composite(F.icon('check',27,(106,47,233,255)),(27,24));pill.alpha_composite(tile,(72,(76-tile.height)//2));F.place(out,pill,(100+pill.width/2,208+i*gap),q,q)
 return out
def _tool(cfg,n):
 out={k:F.blank()for k in['tool_card','tool_icon','tool_support','tool_main','tool_button']};d=cfg['tool'];t=n/25
 if not(d['support']or d['main']or d['button']):return out
 q=F.ease(d['start'],d['start']+.16,t)
 if q<=0:return out
 ImageDraw.Draw(out['tool_card']).rounded_rectangle((207,495,873,791),radius=32,fill='white');out['tool_card']=F.op(out['tool_card'],q)
 icon=Image.new('RGBA',(100,100));draw=ImageDraw.Draw(icon);s=F.ease(d['start'],d['start']+.4,t);draw.arc((8,8,92,92),-90,-90+360*s,fill=(51,95,242,255),width=5)
 if s>.5:icon.alpha_composite(F.icon('gear',48,(51,95,242,255)),(26,26))
 F.place(out['tool_icon'],icon,(540,560),s,s)
 for role,text,point,y,at in[('tool_support',d['support'],20,623,d['support_at']),('tool_main',d['main'],36,666,d['main_at'])]:
  p=F.ease(at,at+.16,t);tile=F.tile(text,cfg['fonts']['pill'],point,(0,0,0,255))if text else Image.new('RGBA',(1,1))
  while tile.width>580 and point>20:point-=1;tile=F.tile(text,cfg['fonts']['pill'],point,(0,0,0,255))
  F.place(out[role],tile,(540,y),.8+.2*p,p)
 p=F.ease(d['button_at'],d['button_at']+.2,t)
 if d['button']and p>0:
  tile=F.tile(d['button'],cfg['fonts']['pill'],24,(0,0,0,255));button=Image.new('RGBA',(max(270,tile.width+70),62));ImageDraw.Draw(button).rounded_rectangle((0,0,button.width-1,61),radius=31,fill=F.LIME);button.alpha_composite(tile,((button.width-tile.width)//2,(62-tile.height)//2));F.place(out['tool_button'],button,(540,742),p,p)
 return out
def _captions(cfg,n):
 cue=next((c for c in cfg['captions']if c['frames'][0]<=n<c['frames'][1]),None)
 if not cue or len(cue.get('lines',[]))<=1:return F.caption(cfg,n)[0]
 result={k:F.blank()for k in['caption_body','caption_emphasis','caption_shadow','caption_glow']};lines=cue['lines']
 for i,line in enumerate(lines):
  text=line['text']if isinstance(line,dict)else line;spans=line.get('emphasis_spans',[])if isinstance(line,dict)else[];c=dict(text=text,frames=cue['frames'],emphasis_spans=spans);local=dict(cfg,captions=[c],warm0=False);roles,_=F.caption(local,n)
  for name,im in roles.items():result[name].alpha_composite(im,(0,round(-(len(lines)-1)*40+i*80)))
 return result
def render_layers(cfg,n):
 box,rad=_pose(cfg,n);person,stroke,glow=_presenter(cfg,n,box,rad);mat,support,con=_material(cfg,n);agenda,_=F.agenda(cfg,n);identity,_=F.identity(cfg,n);captions=_captions(cfg,n);roles=dict(background=grid(n),material=mat,material_support=support,person_glow=glow,presenter=person,person_stroke=stroke,agenda=agenda,identity=identity,conclusion=con,abilities=_abilities(cfg,n),**_tool(cfg,n),**captions);black=Image.new('RGBA',(W,H),(0,0,0,round(255*F.ease(*cfg['tail_fade'],n/25))));roles['whole_scene_black']=black;return roles,dict(frame=n,presenter_box=box,active_asset_ids=[m['asset_id']for m in cfg['materials']if m['start']<=n/25<m['end']],meaningful_tool=bool(cfg['tool']['main']or cfg['tool']['support']))
def composite(roles):return core.composite(roles)
def _compose(roles):
 out=F.blank()
 for role in roles.values():out.alpha_composite(role)
 return out.convert('RGB')
core.render_layers=render_layers;core.composite=_compose
def render_mp4(cfg,output_dir):return core.render_mp4(cfg,output_dir)
