"""Bottom app full-suite adapter. Reuses the pinned live shared renderers read-only.
Only source-specific contrast roles, optional identity/support and measured tail are local.
"""
import sys,copy,json
sys.dont_write_bytecode=True
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageChops
H=Path(__file__).resolve().parent
from . import app_bottom_engine as BASE,app_window_engine as COMMON
from .vendor.apple_minimal.pilot import font,text_image,ease
blank=BASE.blank;composite=BASE.composite
TAIL=json.loads((H/'bottom-tail.json').read_text('utf-8'))['records']
TAIL={r['frame']:r for r in TAIL}

def payload(scene):
    if not scene:return False
    return bool(scene.get('gray') or scene.get('blue') or any((scene.get('quote') or {}).get(k) for k in ['first','second','support']) or any(e.get('text') for e in scene.get('items',[])) or any(any(e.get(k) for k in ['label','text','support']) for e in scene.get('contrast',[])))

def normalize(cfg):
    c=copy.deepcopy(cfg)
    for scene in c.get('chapters',[]):
        if not any((scene.get('quote') or {}).get(k) for k in ['first','second','support']):scene.pop('quote',None)
        scene['items']=[e for e in scene.get('items',[]) if e.get('text')]
        scene['contrast']=[e for e in scene.get('contrast',[]) if any(e.get(k) for k in ['label','text','support'])]
        if scene['contrast'] and not BASE.has_content(scene):scene['quote']={'_actual_contrast_payload':True}
    return c

def contrast(cfg,t,scene):
    roles={};entries=scene.get('contrast',[]);k=cfg['size'][0]/1080
    if len(entries)>2:raise ValueError('Source-measured contrast layout supports one/two actual cards')
    for i,e in enumerate(entries):
        x=148+418*i if len(entries)==2 else 358;top=638;blue=e.get('emphasis',False);color=(255,255,255,255) if blue else COMMON.GRAY
        q=ease(e['phase'][0],e['phase'][1],t);sigma=(1-q)*e.get('entry_blur',8)*k
        bg=blank(cfg);COMMON.rect(ImageDraw.Draw(bg),[x,top,x+364,top+220],k,COMMON.BLUE if blue else 'white',26);roles[f'contrast-{i}-card']=COMMON.fade(bg,q,sigma)
        fields=[('label',e.get('label',''),28,x+62,670),('text',e.get('text',''),52,x+30,724),('support',e.get('support',''),28,x+30,802)]
        occupied=0
        for key,text,size,left,y in fields:
            if not text:continue
            if e.get('compact_optional_roles',True) and key!='label':y=[670,724,802][occupied]
            row=blank(cfg);COMMON.put(row,cfg,text,size,left,y,color,max_width=302 if key!='label' else 270)
            if key=='label':
                kind=e.get('icon','clock' if not blue else 'bolt')
                if kind=='bolt':
                    d=ImageDraw.Draw(row);d.polygon([(round((x+a)*k),round(b*k)) for a,b in [(43,669),(34,681),(41,681),(36,692),(50,677),(43,677),(49,669)]],fill=color)
                else:BASE.icon(row,cfg,kind,x+32,671,18,color)
            at=e.get(key+'_phase',e['phase']);qfield=ease(at[0],at[1],t)
            roles[f'contrast-{i}-{key}']=COMMON.fade(row,qfield,(1-qfield)*e.get('entry_blur',8)*k);occupied+=1
    if len(entries)==2:
        a,b=scene['connector_phase'];q=ease(a,b,t);row=blank(cfg);d=ImageDraw.Draw(row);d.ellipse((510*k,718*k,570*k,778*k),fill='white');COMMON.icon(row,cfg,'arrow',526,734,28,COMMON.BLUE);roles['contrast-connector']=COMMON.fade(row,q,(1-q)*3*k)
    return roles

def quote_support(cfg,t):
    layer=blank(cfg)
    for i,scene in enumerate(cfg.get('chapters',[])):
        data=scene.get('quote') or {};text=data.get('support','')
        if not text or t<scene['at']:continue
        end=cfg['chapters'][i+1]['at'] if i+1<len(cfg['chapters']) else cfg['duration'];leave=ease(end,end+cfg.get('handoff_exit_seconds',.44),t)
        headlines=sum(bool(data.get(k)) for k in ['first','second']);y=814 if headlines==2 else 770 if headlines==1 else 692
        row=blank(cfg);COMMON.put(row,cfg,text,32,224,y,COMMON.GRAY,max_width=700);at=data.get('support_at',scene['at']);q=ease(at,at+data.get('support_reveal',.24),t);layer.alpha_composite(COMMON.fade(row,q*(1-leave),(1-q+leave)*7*cfg['size'][0]/1080))
    return layer

def identity(cfg):
    layer=blank(cfg);data=cfg.get('name_card',{});name=data.get('name','').strip();desc=data.get('description','').strip()
    if not data.get('enabled') or not(name or desc):return layer
    k=cfg['size'][0]/1080;x=118
    for value,size,fill,color in [(name,28,COMMON.BLUE,'white'),(desc,26,(242,242,240,255),COMMON.BLACK)]:
        if not value:continue
        width=font(cfg['fonts']['body'],size*k).getlength(value)/k+32
        if x+width>966:raise ValueError('Identity exceeds measured free caption gap; shorten field')
        COMMON.rect(ImageDraw.Draw(layer),[x,1460,x+width,1502],k,fill,21);COMMON.put(layer,cfg,value,size,x+16,1467,color);x+=width+10
    return layer

def tail_parameters(cfg,n):
    if cfg['source_mode']=='reference-circle':phase=float(n)
    else:
        a,b=cfg['information_outro']
        if n<=a:return None
        phase=512+10*max(0,min(1,(n-a)/(b-a)))
    if phase<512:return None
    lo=min(525,int(np.floor(phase)));hi=min(525,int(np.ceil(phase)));q=phase-lo;aa=TAIL[lo];bb=TAIL[hi]
    alpha=max(0,min(1,(1-q)*aa['intrinsic_alpha']+q*bb['intrinsic_alpha']));sigma=(1-q)*aa['blur_sigma_native']+q*bb['blur_sigma_native']
    # Weak late source fitting does not establish a new authored skew; keep the last reliable pose.
    ma=np.asarray(TAIL[min(lo,520)]['native_affine']);mb=np.asarray(TAIL[min(hi,520)]['native_affine']);return (1-q)*ma+q*mb,alpha,sigma,phase

def information_exit(image,cfg,params):
    if params is None:return image
    mat,q,sigma,_=params
    if q<=0:return blank(cfg)
    inverse=np.linalg.inv(np.vstack([mat,[0,0,1]]))[:2].reshape(-1);k=cfg['size'][0]/1080
    # Native geometry is rendered1080 for current media; rebasing other sizes is explicit.
    inverse=np.array(inverse);inverse[2]*=k;inverse[5]*=k
    out=image.convert('RGBa').transform(tuple(cfg['size']),Image.Transform.AFFINE,inverse,Image.Resampling.BICUBIC).convert('RGBA');out=COMMON.fade(out,q,sigma*k)
    mask=Image.new('L',tuple(cfg['size']));COMMON.rect(ImageDraw.Draw(mask),[112,354,966,1007],k,255,28);out.putalpha(ImageChops.multiply(out.getchannel('A'),mask));return out

def render_layers(frame,t,cfg):
    cfg=normalize(cfg);n=round(t*25);source=cfg['source_mode']=='reference-circle';gain=TAIL[n]['global_gain'] if source and n in TAIL else (max(0,min(1,(cfg['global_fade'][1]-n)/(cfg['global_fade'][1]-cfg['global_fade'][0]))) if not source and n>cfg['global_fade'][0] else 1)
    receipt=None
    if source:
        raw=np.asarray(frame.convert('RGB'));receipt=dict(native_source_rgb_sha256=__import__('hashlib').sha256(raw.tobytes()).hexdigest(),source_frame=n,source_pts=t,global_gain=gain,source_circle_xywh=[118,1085,360,360],source_cleanup=False)
        if 0<gain<1:frame=Image.fromarray(np.uint8(np.clip(np.round(raw.astype(float)/gain),0,255)));receipt['inverse_global_gain_applied_to_source_circle']=True
    roles=BASE.render_layers(frame,t,cfg);scene,index=BASE.scene_at(cfg,t);active=payload(scene) or BASE.material_at(cfg,t) is not None
    if active!=BASE.has_content(scene):
        roles['background']=BASE.shell(cfg,t,active);roles['presenter']=BASE.presenter(frame,cfg,active);roles['navigation']=BASE.navigation(cfg,t) if active else blank(cfg)
    # Keep source chapter badge static while the rest of its final information block exits.
    information=roles.pop('information');chapter=information.copy();moving=information.copy();k=cfg['size'][0]/1080;chapter.paste((0,0,0,0),(0,round(440*k),cfg['size'][0],cfg['size'][1]));moving.paste((0,0,0,0),(0,0,cfg['size'][0],round(440*k)))
    params=tail_parameters(cfg,n);rebuilt={name:roles[name] for name in ['background','presenter','navigation']};rebuilt['information-chapter']=chapter;rebuilt['information-body']=information_exit(moving,cfg,params)
    for c in cfg.get('chapters',[]):
        if t<c['at']:continue
        idx=cfg['chapters'].index(c);leave=BASE.chapter_exit(cfg,idx,t)
        for name,im in contrast(cfg,t,c).items():rebuilt[name]=information_exit(COMMON.fade(im,1-leave,leave*5*k),cfg,params)
    rebuilt['quote-support']=quote_support(cfg,t);rebuilt['material']=roles['material'];rebuilt['identity']=identity(cfg)
    if source and cfg.get('last_caption_scene_fade_only') and t>=cfg['captions'][-1]['time'][0]:
        cc=copy.deepcopy(cfg);cc['captions'][-1]['time'][1]=cfg['duration']+.20;rebuilt['caption']=BASE.caption(cc,t)
    else:rebuilt['caption']=roles['caption']
    if gain<1:
        for name,im in rebuilt.items():
            a=np.asarray(im).copy();a[:,:,:3]=np.uint8(np.round(a[:,:,:3]*gain));rebuilt[name]=Image.fromarray(a)
    return rebuilt,dict(source_recovery=receipt,source_global_gain=gain,information_exit_phase=params[3] if params else None,information_exit_alpha=params[1] if params else None,information_exit_blur=params[2] if params else None,active_body=active,chapter_index=index,active_material_id=(BASE.material_at(cfg,t) or {}).get('id'),clean_raw_zero_cleanup=not source)
