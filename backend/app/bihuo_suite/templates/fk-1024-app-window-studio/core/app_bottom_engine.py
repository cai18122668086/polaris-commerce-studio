"""Bottom-presenter application-window trial; source-measured independent layers."""
from pathlib import Path
from PIL import Image,ImageDraw
from . import app_window_engine as common
from .vendor.apple_minimal import visual as approved_visual,media as approved_media
from .vendor.apple_minimal.pilot import font,ease

DEPENDENCIES=[Path(common.__file__)]
BLUE,GRAY,BLACK=common.BLUE,common.GRAY,common.BLACK
blank,fade,put,rect,scene_at,material_at=common.blank,common.fade,common.put,common.rect,common.scene_at,common.material_at

def has_content(scene):
    return bool(scene and (scene.get('gray') or scene.get('blue') or scene.get('quote') or scene.get('items')))

def presenter(frame,cfg,body):
    W,H=cfg['size'];x,y,w,h=[118,1085,360,360] if cfg['source_mode']=='reference-circle' else cfg.get('raw_crop',[0,420,1080,1080])
    sx=frame.width/1080;sy=frame.height/1920
    texture=frame.crop((round(x*sx),round(y*sy),round((x+w)*sx),round((y+h)*sy))).resize((W,H),Image.Resampling.LANCZOS)
    x,y,w,h=[118,1085,360,360] if body else [112,420,854,1024];radius=w/2 if body else 28
    key=dict(time=0,matrix=[[w/1080,0,x/2],[0,h/1920,y/2]],rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=radius/2,background_opacity=0)
    return approved_visual.render('V02',texture,0,dict(size=[W,H],fps=25,stage_color=[238,234,233],visual_keys=[key]))['presenter']

def shell(cfg,t,body):
    layer=common.shell(cfg,t,False)
    if body:rect(ImageDraw.Draw(layer),[112,354,966,1007],cfg['size'][0]/1080,(239,239,239,255),28)
    return layer

def chapter_exit(cfg,index,t):
    chapters=cfg.get('chapters',[])
    if index+1>=len(chapters):return 0
    at=chapters[index+1]['at'];return ease(at,at+cfg.get('handoff_exit_seconds',.44),t)

def icon(layer,cfg,kind,x,y,size,color):
    k=cfg['size'][0]/1080;d=ImageDraw.Draw(layer);x*=k;y*=k;s=size*k;w=max(1,round(2*k))
    if kind=='shield':
        d.line([(x+s*.5,y),(x+s*.92,y+s*.2),(x+s*.82,y+s*.73),(x+s*.5,y+s),(x+s*.18,y+s*.73),(x+s*.08,y+s*.2),(x+s*.5,y)],fill=color,width=w)
        d.line([(x+s*.28,y+s*.48),(x+s*.45,y+s*.65),(x+s*.72,y+s*.32)],fill=color,width=w)
    elif kind=='check':
        d.ellipse((x,y,x+s,y+s),outline=color,width=w);d.line([(x+s*.2,y+s*.5),(x+s*.42,y+s*.7),(x+s*.8,y+s*.28)],fill=color,width=w)
    else:common.icon(layer,cfg,kind,x/k,y/k,size,color)

def navigation(cfg,t):
    layer=blank(cfg);scene,index=scene_at(cfg,t)
    if scene is None:return layer
    k=cfg['size'][0]/1080;d=ImageDraw.Draw(layer);chapters=cfg.get('chapters',[])
    put(layer,cfg,cfg.get('nav_eyebrow',''),28,546,1148,GRAY,max_width=320)
    if scene.get('nav'):
        rect(d,[546,1214,606,1274],k,(244,244,242,255),30);icon(layer,cfg,'sun',563,1231,26,BLUE)
    for i,c in enumerate(chapters):
        if t<c['at']:continue
        end=chapters[i+1]['at'] if i+1<len(chapters) else cfg['duration']
        for key,size,y,color,span in [('nav',40,1228,BLACK,.28),('nav_support',32,1305,GRAY,.44)]:
            at=c.get(key+'_at',c['at']+.08 if i else .20);q=ease(at,at+span,t)
            if cfg.get('source_warm_frame') and t==0:q=1
            next_at=chapters[i+1].get(key+'_at',end+.08) if i+1<len(chapters) else cfg['duration']+1
            leave=ease(next_at,next_at+span,t);row=blank(cfg)
            put(row,cfg,c.get(key,''),size,620 if key=='nav' else 546,y,color,max_width=340 if key=='nav' else 420)
            layer.alpha_composite(fade(row,q*(1-leave),(1-q+leave)*5*k))
    n=len(chapters);gap=8;width=(420-gap*(n-1))/n
    if width<18:raise ValueError('Chapter count needs a separately validated navigation layout')
    for i in range(n):rect(d,[546+i*(width+gap),1363,546+i*(width+gap)+width,1370],k,BLUE if i==index else (178,198,232,255) if i<index else (229,230,226,255),4)
    put(layer,cfg,f'{index+1:02} / {n:02}',28,881,1148,GRAY,max_width=100)
    return layer

def quote_layers(cfg,t,scene):
    roles={name:blank(cfg) for name in ['mark','first','second']};data=scene.get('quote') or {};k=cfg['size'][0]/1080
    for key,text,size,x,y,color in [('mark','“' if data.get('first') else '',76,148,648,BLUE),('first',data.get('first',''),50,224,656,BLACK),('second',data.get('second',''),54,224,728,BLUE)]:
        if not text:continue
        both=bool(data.get('first') and data.get('second'))
        if not both:y=684 if key=='mark' else 692
        at=data.get(key+'_at',scene['at']);span=data.get(key+'_reveal',.32);q=ease(at,at+data.get(key+'_opacity',.20),t)
        blur_at=data.get(key+'_blur_at',at);clear=ease(blur_at,blur_at+span,t)
        if cfg.get('source_warm_frame') and t==0 and key in ['mark','first']:q=clear=1
        if key=='mark':
            d=ImageDraw.Draw(roles[key])
            for left in [x,x+26]:d.polygon([(round((left+7)*k),round(y*k)),(round((left+21)*k),round(y*k)),(round((left+13)*k),round((y+16)*k)),(round((left+20)*k),round((y+16)*k)),(round((left+20)*k),round((y+38)*k)),(round(left*k),round((y+38)*k)),(round(left*k),round((y+20)*k))],fill=BLUE)
        else:put(roles[key],cfg,text,size,x,y,color,max_width=700)
        roles[key]=fade(roles[key],q,(1-clear)*7*k)
    return roles

def items(cfg,t,scene):
    layer=blank(cfg);entries=scene.get('items',[]);k=cfg['size'][0]/1080
    if len(entries)>3:raise ValueError('More than three vertical rows needs a separately validated pagination recipe')
    current=max([-1]+[i for i,e in enumerate(entries) if e['at']<=t]);image=material_at(cfg,t) is not None
    for i,entry in enumerate(entries):
        y=623+95*i;row=blank(cfg);d=ImageDraw.Draw(row);active=current==i
        rect(d,[147,y,203,y+56],k,BLUE if active else 'white',28)
        icon(row,cfg,entry.get('icon',['sun','shield','check'][i]),165,y+18,20,'white' if active else BLUE)
        put(row,cfg,entry['text'],30 if image else 36,224,y+12,BLACK,max_width=275 if image else 700)
        q=ease(entry.get('enter_at',entry['at']-.08),entry.get('clear_at',entry['at']+.32),t)
        layer.alpha_composite(fade(row,q,(1-q)*7*k))
    return layer

def body(cfg,t):
    layer=blank(cfg);chapters=cfg.get('chapters',[]);k=cfg['size'][0]/1080
    for i,scene in enumerate(chapters):
        if t<scene['at'] or not has_content(scene):continue
        leave=chapter_exit(cfg,i,t)
        if leave>=1:continue
        end=chapters[i+1]['at'] if i+1<len(chapters) else cfg['duration'];decor=blank(cfg);d=ImageDraw.Draw(decor)
        if t<end:
            rect(d,[147,385,203,417],k,'white',16);put(decor,cfg,f'{i+1:02}',28,175,390,BLUE,'center');put(decor,cfg,scene.get('label',''),32,213,391,BLACK,max_width=620)
        rect(d,[148,933,930,935],k,(232,232,229,255));d.ellipse((148*k,960*k,158*k,970*k),fill=BLUE);put(decor,cfg,scene.get('label',''),28,168,953,GRAY,max_width=350)
        next_label=chapters[i+1].get('label','') if i+1<len(chapters) else ''
        if next_label:put(decor,cfg,'下一幕 · '+next_label+' →',28,675 if len(next_label)<=4 else 565,953,GRAY,max_width=350)
        layer.alpha_composite(fade(decor,1-leave,leave*3*k))
        for role,size,y,color in [('gray',28,scene.get('gray_y',491),GRAY),('blue',48,scene.get('blue_y',535),BLUE)]:
            row=blank(cfg);at=scene.get(role+'_at',scene['at']+.04);span=scene.get(role+'_reveal',.28);q=ease(at,at+span,t)
            if cfg.get('source_warm_frame') and t==0:q=1
            put(row,cfg,scene.get(role,''),size,148,y,color,max_width=780);layer.alpha_composite(fade(row,q*(1-leave),(1-q+leave)*5*k))
        for row in [*quote_layers(cfg,t,scene).values(),items(cfg,t,scene)]:layer.alpha_composite(fade(row,1-leave,leave*5*k))
    return layer

def materials(cfg,t):
    layer=blank(cfg);entry=material_at(cfg,t)
    if entry is None:return layer
    row=dict(id=entry['id'],path=entry['path'],type=entry.get('type','image'),start_frame=round(entry['start']*25),rect=[265,310,465,445],fit='contain',anchor=[.5,.5],radius=10,entry_frames=8,entry_blur=4,source_in=0,speed=1,end_policy='hold',audio='muted')
    for image in approved_media.render('V03',None,round(t*25),dict(size=cfg['size'],fps=25,media_entries=[row])).values():layer.alpha_composite(image)
    return fade(layer,1-ease(entry['end']-.16,entry['end'],t))

def caption(cfg,t):
    if cfg.get('source_warm_frame') and t==0 and cfg.get('captions'):
        warm=dict(cfg,captions=[dict(cfg['captions'][0],time=[0,.04])]);return common.caption(warm,t)
    if cfg['source_mode']=='reference-circle':
        cue=next((c for c in cfg.get('captions',[]) if c['time'][0]<=t<c['time'][1]),None)
        if cue is None:return blank(cfg)
        a,b=cue['time'];row=common.caption(dict(cfg,source_warm_frame=True,captions=[dict(cue,time=[0,b-a])]),0)
        opacity=ease(a,a+min(.12,(b-a)*.3),t)*(1-ease(b-.08,b,t));clear=ease(a,a+min(.24,(b-a)*.4),t)
        return fade(row,opacity,(1-clear)*4*cfg['size'][0]/1080)
    return common.caption(cfg,t)

def render_layers(frame,t,cfg):
    scene,_=scene_at(cfg,t);active=has_content(scene)
    return dict(background=shell(cfg,t,active),presenter=presenter(frame,cfg,active),navigation=navigation(cfg,t) if active else blank(cfg),information=body(cfg,t),material=materials(cfg,t),identity=blank(cfg),caption=caption(cfg,t))

composite=common.composite
