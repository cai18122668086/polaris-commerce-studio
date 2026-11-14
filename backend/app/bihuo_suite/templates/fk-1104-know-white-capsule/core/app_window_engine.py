"""Native application-window layers with conditional body roles and word clocks.

Only the rounded affine presenter sampler, media sampler, font helpers and
semantic emphasis parser are imported from the pinned approved implementation.
"""
from __future__ import annotations
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor.apple_minimal import visual as approved_visual,media as approved_media
from .vendor.apple_minimal.pilot import font,text_image,ease

BLUE=(49,101,202,255);GRAY=(105,107,104,255);BLACK=(8,9,8,255)

def blank(cfg):return Image.new('RGBA',tuple(cfg['size']))
def fade(layer,q,blur=0):
    if blur:layer=layer.convert('RGBa').filter(ImageFilter.GaussianBlur(blur)).convert('RGBA')
    if q<1:
        layer=layer.copy();layer.putalpha(layer.getchannel('A').point([round(a*max(0,q)) for a in range(256)]))
    return layer

def put(layer,cfg,text,size,x,y,color=BLACK,align='left',max_width=None):
    if not text:return None
    k=cfg['size'][0]/1080;path=cfg['fonts']['body'] if size<=28 else cfg['fonts']['bold']
    face=font(path,size*k)
    nominal=size
    while max_width is not None and face.getlength(text)>max_width*k and size>nominal*.82:
        size-=1;face=font(path,size*k)
    if max_width is not None and face.getlength(text)>max_width*k:raise ValueError('App text exceeds declared role capacity; compile semantic line breaks or pages')
    tile=text_image(text,path,size*k,color)[0];box=tile.getchannel('A').getbbox();tile=tile.crop(box)
    left=x*k-tile.width/2 if align=='center' else x*k
    layer.alpha_composite(tile,(round(left),round(y*k)));return tile.getchannel('A').getbbox()

def rect(draw,box,k,fill,r=0,outline=None,width=1):
    box=tuple(v*k for v in box)
    if r:draw.rounded_rectangle(box,radius=r*k,fill=fill,outline=outline,width=max(1,round(width*k)))
    else:draw.rectangle(box,fill=fill,outline=outline,width=max(1,round(width*k)))

def icon(layer,cfg,kind,x,y,size,color=BLUE):
    k=cfg['size'][0]/1080;d=ImageDraw.Draw(layer);x*=k;y*=k;s=size*k;w=max(1,round(2*k))
    if kind=='arrow':d.line((x,y+s*.5,x+s,y+s*.5),fill=color,width=w);d.line((x+s*.66,y+s*.17,x+s,y+s*.5,x+s*.66,y+s*.83),fill=color,width=w)
    elif kind=='clock':d.ellipse((x,y,x+s,y+s),outline=color,width=w);d.line((x+s*.5,y+s*.2,x+s*.5,y+s*.5,x+s*.76,y+s*.64),fill=color,width=w)
    elif kind=='question':d.ellipse((x,y,x+s,y+s),outline=color,width=w);put(layer,cfg,'?',size*.8,(x+s*.5)/k,(y-s*.02)/k,color,'center')
    elif kind=='sun':
        for i in range(8):
            a=i*math.pi/4;d.line((x+s*.5+math.cos(a)*s*.25,y+s*.5+math.sin(a)*s*.25,x+s*.5+math.cos(a)*s*.46,y+s*.5+math.sin(a)*s*.46),fill=color,width=w)
    else:
        for i in range(3):
            yy=y+(i+.5)*s/3;d.ellipse((x,yy-1*k,x+2*k,yy+1*k),fill=color);d.line((x+6*k,yy,x+s,yy),fill=color,width=w)

def scene_at(cfg,t):
    chapters=cfg.get('chapters',[])
    if not chapters:return None,0
    index=max(0,next((i-1 for i,c in enumerate(chapters) if c['at']>t),len(chapters)-1))
    return chapters[index],index

def material_at(cfg,t):
    if cfg.get('material_mode','none')!='provided':return None
    return next((m for m in cfg.get('materials',[]) if m['start']<=t<m['end']),None)

def payload(scene):return bool(scene and (scene.get('gray') or scene.get('blue') or scene.get('contrast') or scene.get('items') or scene.get('quote')))

def presenter(frame,cfg,has_body):
    W,H=cfg['size'];mode=cfg.get('source_mode')
    if mode=='reference-circle':x,y,w,h=[606,372,360,360]
    else:x,y,w,h=cfg.get('raw_crop',[0,420,1080,1080])
    sx=frame.width/1080;sy=frame.height/1920;texture=frame.crop((round(x*sx),round(y*sy),round((x+w)*sx),round((y+h)*sy))).resize((W,H),Image.Resampling.LANCZOS)
    box=[606,372,360,360] if has_body else [112,420,854,1024]
    xx,yy,ww,hh=box;rad=ww/2 if has_body else 28
    key=dict(time=0,matrix=[[ww/1080,0,xx/2],[0,hh/1920,yy/2]],rect=[xx/2,yy/2,(xx+ww)/2,(yy+hh)/2],radius=rad/2,background_opacity=0)
    return approved_visual.render('V02',texture,0,dict(size=[W,H],fps=25,stage_color=[238,234,233],visual_keys=[key]))['presenter']

def shell(cfg,t,has_body):
    k=cfg['size'][0]/1080;layer=Image.new('RGBA',tuple(cfg['size']),(238,234,233,255));d=ImageDraw.Draw(layer)
    rect(d,[64,241,1013,1680],k,'white',36);rect(d,[112,332,966,334],k,(226,227,224,255))
    rect(d,[112,279,160,319],k,BLUE,9);d.ellipse((126*k,290*k,146*k,310*k),outline='white',width=max(1,round(2*k)));d.polygon([(133*k,295*k),(133*k,305*k),(141*k,300*k)],fill='white')
    title=cfg.get('header_title','');support=cfg.get('header_support','');put(layer,cfg,title,32,174,285,max_width=570)
    title_w=font(cfg['fonts']['bold'],32*k).getlength(title)/k if title else 0
    put(layer,cfg,support,20,174+title_w+(16 if title and support else 0),294,GRAY,max_width=max(100,740-title_w))
    d.ellipse((942*k,287*k,966*k,311*k),fill=BLUE)
    if has_body:rect(d,[112,764,966,1445],k,(239,239,239,255),28)
    rect(d,[112,1636,966,1640],k,(227,228,225,255));progress=min(1,max(0,t/cfg['duration']))
    rect(d,[112,1636,112+854*progress,1640],k,BLUE)
    return layer

def navigation(cfg,t):
    layer=blank(cfg);scene,index=scene_at(cfg,t)
    if scene is None:return layer
    k=cfg['size'][0]/1080;d=ImageDraw.Draw(layer);tag=cfg.get('category','');base_y=503 if tag else 450
    if tag:
        q=1 if cfg.get('source_warm_frame') and t==0 else ease(.20,.48,t)
        row=blank(cfg);rd=ImageDraw.Draw(row);width=min(430,font(cfg['fonts']['body'],26*k).getlength(tag)/k+74)
        rect(rd,[112,421,112+width,473],k,(242,242,240,255),26);icon(row,cfg,'list',138,436,20);put(row,cfg,tag,26,170,433,max_width=350);layer.alpha_composite(fade(row,q,(1-q)*3*k))
    row=blank(cfg);rd=ImageDraw.Draw(row);dtime=t-scene['at'];enter=1 if index>0 or cfg.get('source_warm_frame') and t==0 else ease(.36,.68,dtime)
    rd.ellipse((112*k,(base_y-8)*k,180*k,(base_y+60)*k),fill=(241,241,239,255));icon(row,cfg,['question','arrow','sun'][min(index,2)],135,base_y+13,24);put(row,cfg,scene.get('nav',''),54,197,base_y,max_width=380)
    layer.alpha_composite(fade(row,enter,(1-enter)*5*k))
    if scene.get('nav_support'):
        support=blank(cfg);put(support,cfg,scene['nav_support'],32,112,base_y+89,GRAY,max_width=460)
        sq=ease(.48,.88,dtime) if index==0 else ease(0,.16,dtime)
        if cfg.get('source_warm_frame') and t==0:sq=.4
        layer.alpha_composite(fade(support,sq,(1-sq)*7*k))
    n=len(cfg['chapters']);gap=8;width=(340-gap*(n-1))/n
    if width<15:raise ValueError('Chapter progress needs an alternate layout for this count')
    for i in range(n):rect(d,[112+i*(width+gap),647,112+i*(width+gap)+width,655],k,BLUE if i==index else (178,198,232,255) if i<index else (229,230,226,255),4)
    put(layer,cfg,f'{index+1:02} / {n:02}',24,468,642,GRAY,max_width=130)
    return layer

def title_roles(cfg,t,scene,leave):
    layer=blank(cfg);k=cfg['size'][0]/1080
    for role,size,y,color in [('gray',28,scene.get('gray_y',941),GRAY),('blue',48,scene.get('blue_y',984),BLUE)]:
        row=blank(cfg);at=scene.get(role+'_at',scene.get('heading_at',scene['at']+.08));enter=ease(at,at+scene.get(role+'_reveal',.24),t)
        if cfg.get('source_warm_frame') and t==0:enter=1
        put(row,cfg,scene.get(role,''),size,148,y,color,max_width=770);layer.alpha_composite(fade(row,enter*(1-leave),(1-enter+leave)*5*k))
    return layer

def contrast(cfg,t,scene):
    layer=blank(cfg);k=cfg['size'][0]/1080;entries=[entry for entry in scene.get('contrast',[]) if entry.get('text')]
    if not entries:return layer
    if len(entries)>2:raise ValueError('Contrast recipe supports one or two content cards')
    for i,entry in enumerate(entries):
        x=148+418*i if len(entries)==2 else 358;row=blank(cfg);d=ImageDraw.Draw(row);is_blue=entry.get('emphasis',False)
        rect(d,[x,1081,x+364,1265],k,BLUE if is_blue else 'white',26)
        ink=(255,255,255,255) if is_blue else GRAY
        icon(row,cfg,'clock' if not is_blue else 'sun',x+32,1114,18,ink);put(row,cfg,entry.get('label',''),28,x+62,1114,ink,max_width=270)
        put(row,cfg,entry['text'],52,x+30,1168,(255,255,255,255) if is_blue else GRAY,max_width=304)
        q=ease(entry['at'],entry['at']+entry.get('reveal',.28),t);layer.alpha_composite(fade(row,q,(1-q)*8*k))
    if len(entries)==2:
        at=scene.get('connector_at',entries[-1]['at']+.32);q=ease(at,at+.16,t);arrow=blank(cfg);ad=ImageDraw.Draw(arrow);ad.ellipse((518*k,1152*k,562*k,1196*k),fill='white');icon(arrow,cfg,'arrow',532,1166,16);layer.alpha_composite(fade(arrow,q,(1-q)*2*k))
    return layer

def step_nodes(cfg,t,scene):
    layer=blank(cfg);k=cfg['size'][0]/1080;items=scene.get('items',[])
    if not items:return layer
    if len(items)>3:raise ValueError('More than three steps requires a separately validated pagination recipe')
    current=max([-1]+[i for i,item in enumerate(items) if item['at']<=t]);has_material=material_at(cfg,t) is not None
    n=len(items);gap=50 if n>1 else 0;node_width=min(300,(782-gap*(n-1))/n);total=n*node_width+(n-1)*gap;left=(1080-total)/2
    for i,item in enumerate(items):
        row=blank(cfg);d=ImageDraw.Draw(row);active=i==current;q=ease(item.get('enter_at',item['at']-.08),item.get('clear_at',item['at']+.24),t)
        x=148 if has_material else left+i*(node_width+gap);y=1080+i*94 if has_material else 1069;w=300 if has_material else node_width;h=84 if has_material else 210
        rect(d,[x,y,x+w,y+h],k,(217,224,241,255) if active else 'white',24 if not has_material else 14)
        if has_material:
            put(row,cfg,f'{i+1:02}',20,x+18,y+12,BLUE if active else GRAY)
            put(row,cfg,item['text'],28,x+65,y+29,BLUE if active else BLACK,max_width=w-80)
        else:
            put(row,cfg,f'{i+1:02}',28,x+w/2,y+25,BLUE if active else GRAY,'center')
            if active:d.ellipse(((x+w/2-30)*k,(y+64)*k,(x+w/2+30)*k,(y+124)*k),fill=BLUE)
            icon(row,cfg,'clock' if i==2 else 'list',x+w/2-11,y+83,22,(255,255,255,255) if active else BLUE)
            put(row,cfg,item['text'],36,x+w/2,y+148,BLUE if active else BLACK,'center',max_width=w-30)
        layer.alpha_composite(fade(row,q,(1-q)*7*k))
        if i and q>0 and not has_material:
            arrow=blank(cfg);icon(arrow,cfg,'arrow',x-gap*.74,y+96,22,GRAY);layer.alpha_composite(fade(arrow,q))
    return layer

def quote(cfg,t,scene):
    layer=blank(cfg);k=cfg['size'][0]/1080;data=scene.get('quote') or {}
    if not data:return layer
    rows=[('first',data.get('first',''),50,224,1047,BLACK),('second',data.get('second',''),54,224,1117,BLUE),('support',data.get('support',''),32,237,1202,GRAY)]
    active=[row for row in rows if row[1]]
    for index,(key,text,size,x,y,color) in enumerate(active):
        if not text:continue
        if data.get('compact_optional_roles',False) and len(active)!=3:y=[1047,1117,1202][index]
        row=blank(cfg);put(row,cfg,text,size,x,y,color,max_width=720);at=data.get(key+'_at',scene['at']+.16);q=ease(at,at+data.get(key+'_reveal',.24),t);layer.alpha_composite(fade(row,q,(1-q)*7*k))
        if index==0 and key!='support':
            mark=blank(cfg);put(mark,cfg,'“',76,148,1037,BLUE);layer.alpha_composite(fade(mark,q))
    return layer

def body(cfg,t):
    layer=blank(cfg);chapters=cfg.get('chapters',[]);k=cfg['size'][0]/1080
    for i,scene in enumerate(chapters):
        if t<scene['at'] or not payload(scene):continue
        end=chapters[i+1]['at'] if i+1<len(chapters) else cfg['duration']
        leave=ease(end,end+.32,t)
        if leave>=1:continue
        decoration=blank(cfg);d=ImageDraw.Draw(decoration);rect(d,[148,796,198,827],k,'white',15);put(decoration,cfg,f'{i+1:02}',24,173,800,BLUE,'center');put(decoration,cfg,scene.get('label',''),28,208,801,max_width=500)
        put(decoration,cfg,f'{i+1:02}',146,765,775,(231,231,226,255),max_width=200)
        rect(d,[148,1370,930,1372],k,(232,232,229,255));d.ellipse((148*k,1397*k,158*k,1407*k),fill=BLUE);put(decoration,cfg,scene.get('label',''),28,168,1391,GRAY,max_width=350)
        following=chapters[i+1].get('label','') if i+1<len(chapters) else ''
        if following:put(decoration,cfg,'下一章 · '+following+' →',28,675 if len(following)<=4 else 565,1391,GRAY,max_width=350)
        if t<end:layer.alpha_composite(decoration)
        layer.alpha_composite(title_roles(cfg,t,scene,leave))
        for component in [contrast,step_nodes,quote]:layer.alpha_composite(fade(component(cfg,t,scene),1-leave,leave*4*k))
    return layer

def materials(cfg,t):
    layer=blank(cfg);entry=material_at(cfg,t)
    if entry is None:return layer
    row=dict(id=entry['id'],path=entry['path'],type=entry.get('type','image'),start_frame=round(entry['start']*25),rect=[250,540,465,660],fit='contain',anchor=[.5,.5],radius=12,entry_frames=8,entry_blur=4,source_in=0,speed=1,end_policy='hold',audio='muted')
    for image in approved_media.render('V03',None,round(t*25),dict(size=cfg['size'],fps=25,media_entries=[row])).values():layer.alpha_composite(image)
    return fade(layer,1-ease(entry['end']-.16,entry['end'],t))

def caption(cfg,t):
    layer=blank(cfg);k=cfg['size'][0]/1080;cue=next((cue for cue in cfg.get('captions',[]) if cue['time'][0]<=t<cue['time'][1]),None)
    if cue is None:return layer
    lines=cue.get('lines',[dict(text=cue['text'],emphasis_spans=[])])
    for j,line in enumerate(lines):
        parts=approved_visual.caption_parts(line);width=sum(font(cfg['fonts']['bold'],(54 if mark else 48)*k).getlength(text) for text,mark in parts)
        if width>950*k:raise ValueError('Caption needs semantic wrapping for application-window reading width')
        x=(1080-width/k)/2;y=1540+j*62-(len(lines)-1)*31
        for text,mark in parts:
            size=54 if mark else 48;put(layer,cfg,text,size,x,y-(6 if mark else 0),BLUE if mark else (25,34,50,255));x+=font(cfg['fonts']['bold'],size*k).getlength(text)/k
    a,b=cue['time'];q=ease(a,a+min(.24,(b-a)*.35),t)*(1-ease(b-.08,b,t))
    if cfg.get('source_warm_frame') and t==0:q=1
    return fade(layer,q,(1-q)*4*k)

def render_layers(frame,t,cfg):
    scene,_=scene_at(cfg,t);has_body=payload(scene)
    return dict(background=shell(cfg,t,has_body),presenter=presenter(frame,cfg,has_body),navigation=navigation(cfg,t) if has_body else blank(cfg),information=body(cfg,t),material=materials(cfg,t),identity=blank(cfg),caption=caption(cfg,t))

def composite(layers):
    result=next(iter(layers.values())).copy()
    for image in list(layers.values())[1:]:result.alpha_composite(image)
    return result.convert('RGB')
