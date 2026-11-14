"""Capsule differential components over the pinned approved affine/mask sampler.

All positions use measured1080x1920 coordinates. Text, optional slots and clocks
are input data; no reference pixels are used for new-person compositions.
"""
from __future__ import annotations
import math
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor.apple_minimal import visual as approved_visual
from .vendor.apple_minimal import media as approved_media
from .vendor.apple_minimal.pilot import font,text_image,ease
from .input_policy import resolve

def alpha(im:Image.Image,q:float,blur:float=0)->Image.Image:
    if blur:im=im.convert('RGBa').filter(ImageFilter.GaussianBlur(blur)).convert('RGBA')
    if q<1:
        im=im.copy();im.putalpha(im.getchannel('A').point([round(a*max(0,q)) for a in range(256)]))
    return im

def pose(cfg:dict,t:float)->dict:
    motion=cfg['motion'];a,b=motion['times']
    q=0 if t<=a else 1 if t>=b else .5-.5*math.cos(math.pi*(t-a)/(b-a))
    if not (cfg.get('items') or cfg.get('title') or (cfg.get('conclusion') or {}).get('text')):q=0 # No information payload means no empty card or reserved space.
    x,y,w,h=[a*(1-q)+b*q for a,b in zip(motion['from'],motion['to'])]
    radius=motion['radius'][0]*(1-q)+motion['radius'][1]*q
    return dict(x=x,y=y,w=w,h=h,radius=radius,progress=q)

def blank(cfg):return Image.new('RGBA',tuple(cfg['size']))

def active_material(cfg,t):
    if cfg.get('material_mode','none')!='provided':return None
    return next((m for m in cfg.get('materials',[]) if m['start']<=t<m['end']),None)

def material(cfg,t):
    layer=blank(cfg);entry=active_material(cfg,t)
    if entry is None:return layer
    row=dict(id=entry['id'],path=entry['path'],type=entry.get('type','image'),start_frame=round(entry['start']*25),rect=[325,220,480,365],fit=entry.get('fit','contain'),anchor=[.5,.5],radius=12,entry_frames=8,entry_blur=4,source_in=0,speed=1,end_policy='hold',audio='muted')
    roles=approved_media.render('V03',None,round(t*25),dict(size=cfg['size'],fps=25,media_entries=[row]))
    for im in roles.values():layer.alpha_composite(im)
    return alpha(layer,1-ease(entry['end']-.16,entry['end'],t))

def crop_texture(frame:Image.Image,cfg:dict,t:float)->Image.Image:
    if cfg.get('source_mode')=='reference-window':
        observed=cfg['reference_window_keys'];values=np.array([k['time'] for k in observed]);i=int(np.searchsorted(values,t,side='right'))
        if i==0:box=observed[0]['box']
        elif i>=len(observed):box=observed[-1]['box']
        else:
            a,b=observed[i-1],observed[i];q=(t-a['time'])/(b['time']-a['time']);box=[x*(1-q)+y*q for x,y in zip(a['box'],b['box'])]
        x,y,w,h=box;crop=frame.crop((round(x)+2,round(y)+2,round(x+w)-2,round(y+h)-2))
    else:
        x,y,w,h=cfg['raw_crop'];sx=frame.width/1080;sy=frame.height/1920;crop=frame.crop((round(x*sx),round(y*sy),round((x+w)*sx),round((y+h)*sy)))
    return crop.resize(tuple(cfg['size']),Image.Resampling.LANCZOS)

def text_at(layer,text,path,size,x,y,color,align='left',stroke=0):
    if not text:return None
    im=text_image(text,path,size,color,stroke=stroke,stroke_fill=(255,255,255,255))[0];box=im.getchannel('A').getbbox();im=im.crop(box)
    if align=='center':x-=im.width/2
    layer.alpha_composite(im,(round(x),round(y)));return [round(x),round(y),round(x)+im.width,round(y)+im.height]

def fit_lines(text,path,size,max_width,max_lines=2,min_size=28):
    for s in range(round(size),round(min_size)-1,-1):
        face=font(path,s);lines=['']
        for ch in text:
            if face.getlength(lines[-1]+ch)>max_width and lines[-1]:lines.append(ch)
            else:lines[-1]+=ch
        if len(lines)<=max_lines:return lines,s
    raise ValueError('Text cannot fit declared capsule capacity; revise input or use alternate layout')

def identity(cfg,t):
    layer=blank(cfg);card=resolve(cfg)['name_card'];start,end=cfg.get('identity_times',[0,2.4]);k=cfg['size'][0]/1080
    if not card['visible'] or not start<=t<end:return layer
    x=76*k;cy=1042*k;slots=[]
    for role,path,size,color,ink in [('name',cfg['fonts']['title'],64*k,(38,93,232,255),(255,255,255,255)),('description',cfg['fonts']['body'],44*k,(255,255,255,255),(30,30,30,255))]:
        value=card[role]
        if not value:continue
        lines,s=fit_lines(value,path,size,820*k,max_lines=2,min_size=30*k)
        maxw=max(font(path,s).getlength(line) for line in lines);width=maxw+40*k;height=max(72*k,len(lines)*s*1.22+24*k)
        slots.append((role,path,lines,s,color,ink,width,height))
    total=sum(a[-2] for a in slots)
    # If both fields are long, wrap each into its own row instead of squeezing.
    stacked=total>900*k
    for role,path,lines,s,color,ink,width,height in slots:
        if stacked:width=min(width,900*k)
        top=cy-height/2;draw=ImageDraw.Draw(layer);draw.rounded_rectangle((x,top,x+width,top+height),radius=min(height/2,50*k),fill=color)
        for j,line in enumerate(lines):text_at(layer,line,path,s,x+width/2,top+12*k+j*s*1.22,ink,'center')
        if stacked:cy+=height+8*k
        else:x+=width
    return layer

def card(cfg,t):
    layer=blank(cfg);k=cfg['size'][0]/1080;items=cfg.get('items',[])
    if not items:return layer
    a,b=cfg['card_times'];q=ease(a,b,t)
    if q<=0:return layer
    out=cfg.get('card_exit')
    leave=ease(*out,t) if out else 0
    # Native rows retain source style; count and long text change actual capacity.
    title=resolve(cfg)['title'];title_size=cfg.get('title_size',48)*k
    title_lines,ts=fit_lines(title,cfg['fonts']['title'],title_size,840*k,2,36*k) if title else ([],title_size)
    has_material=active_material(cfg,t) is not None
    row_size=36*k;maxw=(400 if has_material else 750)*k
    card_font=cfg['fonts'].get('card_body',cfg['fonts']['title'])
    rows=[fit_lines(item['text'],card_font,row_size,maxw,2,30*k) for item in items]
    y0=289*k+(1-q)*100*k
    header_height=max(60*k,len(title_lines)*ts*1.18) if title else 0
    row_top=y0+66*k+header_height+50*k
    heights=[max(88*k,len(lines)*s*1.25+36*k) for lines,s in rows]
    conclusion=cfg.get('conclusion');reserve=193*k if conclusion and conclusion.get('text') else 28*k
    h=max(390*k,row_top-y0+sum(heights)+reserve)
    if 289*k+h>1000*k:raise ValueError('Information card exceeds validated reading area; split points into pages')
    d=ImageDraw.Draw(layer);d.rounded_rectangle((54*k,y0,1026*k,y0+h),radius=48*k,fill='white')
    ty=y0+66*k
    for line in title_lines:text_at(layer,line,cfg['fonts']['title'],ts,120*k,ty,(0,0,0,255));ty+=ts*1.18
    y=row_top
    for i,((lines,s),item,rh) in enumerate(zip(rows,items,heights)):
        if i<len(items)-1:d.line((120*k,y+rh-23*k,(620 if has_material else 962)*k,y+rh-23*k),fill=(233,233,233,255),width=max(1,round(2*k)))
        progress=ease(item['at'],item['at']+cfg.get('row_reveal_duration',.12),t)
        if progress:
            row=blank(cfg);rd=ImageDraw.Draw(row);cx=137*k;cy=y+15*k
            rd.line((cx-11*k,cy,cx+11*k,cy),fill=(110,110,110,255),width=max(1,round(3*k)));rd.line((cx,cy-11*k,cx,cy+11*k),fill=(110,110,110,255),width=max(1,round(3*k)))
            for j,line in enumerate(lines):text_at(row,line,card_font,s,189*k,y+j*s*1.25+(1-progress)*12*k,(0,0,0,255))
            layer.alpha_composite(alpha(row,progress,(1-progress)*2*k))
        y+=rh
    if conclusion and conclusion.get('text'):
        bar_y=y+35*k
        arrow=blank(cfg);ad=ImageDraw.Draw(arrow);aq=ease(conclusion['at']-.32,conclusion['at']-.20,t)
        ad.line((540*k,bar_y-48*k,540*k,bar_y-25*k),fill=(110,110,110,255),width=max(1,round(4*k)))
        ad.line((529*k,bar_y-36*k,540*k,bar_y-25*k,551*k,bar_y-36*k),fill=(110,110,110,255),width=max(1,round(4*k)))
        layer.alpha_composite(alpha(arrow,aq))
        scale_keys=cfg['conclusion_scale_keys'];dt=t-conclusion['at'];z=float(np.interp(dt,[v[0] for v in scale_keys],[v[1] for v in scale_keys]))
        if z>0:
            foot=blank(cfg);fd=ImageDraw.Draw(foot)
            fd.rounded_rectangle((120*k,bar_y,960*k,bar_y+97*k),radius=48*k,fill=(38,93,232,255))
            lines,s=fit_lines(conclusion['text'],cfg['fonts']['title'],40*k,750*k,1,28*k)
            text_at(foot,lines[0],cfg['fonts']['title'],s,540*k,bar_y+27*k,(255,255,255,255),'center')
            crop=foot.crop((round(120*k),round(bar_y),round(960*k),round(bar_y+97*k)))
            crop=crop.convert('RGBa').resize((max(1,round(crop.width*z)),max(1,round(crop.height*z))),Image.Resampling.LANCZOS).convert('RGBA')
            layer.alpha_composite(crop,(round(540*k-crop.width/2),round(bar_y+48.5*k-crop.height/2)))
    return alpha(layer,q*(1-leave)**3,leave*20*k)

def caption(cfg,t):
    layer=blank(cfg);k=cfg['size'][0]/1080
    cue=next((c for c in cfg.get('captions',[]) if c['time'][0]<=t<c['time'][1]),None)
    if not cue:return layer
    lines=cue.get('lines',[dict(text=cue['text'],emphasis_spans=[])]);allparts=[]
    for line in lines:
        allparts.append(approved_visual.caption_parts(line))
    regular=cfg.get('caption_size',62)*k;large=cfg.get('emphasis_size',74)*k
    widths=[sum(font(cfg['fonts']['caption'],large if active else regular).getlength(text) for text,active in parts) for parts in allparts]
    if max(widths)>990*k:
        raise ValueError('Caption exceeds measured capacity; compile semantic line breaks instead of distorting glyphs')
    for j,(parts,width) in enumerate(zip(allparts,widths)):
        x=(cfg['size'][0]-width)/2;y=(1605+j*88-(len(lines)-1)*44)*k
        for text,active in parts:
            size=large if active else regular;path=cfg['fonts']['caption'];face=font(path,size)
            # Shared visual caption parser keeps semantic emphasis spans intact.
            im=text_image(text,path,size,(38,93,232,255) if active else (0,0,0,255),stroke=round(8*k),stroke_fill='white')[0]
            box=im.getchannel('A').getbbox();im=im.crop(box);layer.alpha_composite(im,(round(x-8*k),round(y-(size-regular)-8*k)));x+=face.getlength(text)
    a,b=cue['time'];enter=min(cfg.get('caption_enter_duration',.32),(b-a)*.35);z=ease(a,a+enter,t)*(1-ease(b-.08,b,t));return alpha(layer,z,(1-z)*2*k)

def render_layers(frame:Image.Image,t:float,cfg:dict)->dict:
    W,H=cfg['size'];k=W/1080;pos=pose(cfg,t);texture=crop_texture(frame,cfg,t)
    key=dict(time=0,matrix=[[pos['w']/1080,0,pos['x']/2],[0,pos['h']/1920,pos['y']/2]],rect=[pos['x']/2,pos['y']/2,(pos['x']+pos['w'])/2,(pos['y']+pos['h'])/2],radius=pos['radius']/2,background_opacity=0)
    # Matrix scale must use raw resized output dimensions. Ratios above are
    # canonical1080 coordinates and remain invariant under output scaling.
    approved=approved_visual.render('V02',texture,0,dict(size=[W,H],fps=25,stage_color=[247,247,245],visual_keys=[key]))
    background=approved['background'];back=blank(cfg)
    if cfg.get('opening_title') and t<cfg['motion']['times'][0]:
        d=ImageDraw.Draw(back);d.rounded_rectangle((54*k,390*k,1026*k,819*k),radius=48*k,fill='white');text_at(back,cfg['opening_title'],cfg['fonts']['body'],34*k,120*k,461*k,(80,80,80,255))
        back=alpha(back,1-ease(2.4,2.6,t))
    border=blank(cfg);d=ImageDraw.Draw(border);box=[pos['x']*k,pos['y']*k,(pos['x']+pos['w'])*k,(pos['y']+pos['h'])*k]
    d.rounded_rectangle(box,radius=pos['radius']*k,fill=(3,3,3,255));inside=approved['presenter'];edge=round(max(1,2*k))
    # Use the actual approved mask, eroded for an independent outline behind it.
    inside.putalpha(inside.getchannel('A').filter(ImageFilter.MinFilter(edge*2+1)))
    return dict(background=background,back_card=back,information=blank(cfg),material=material(cfg,t),presenter_border=border,presenter=inside,identity=identity(cfg,t),caption=caption(cfg,t))

def composite(layers):
    result=next(iter(layers.values())).copy()
    for image in list(layers.values())[1:]:result.alpha_composite(image)
    return result.convert('RGB')
