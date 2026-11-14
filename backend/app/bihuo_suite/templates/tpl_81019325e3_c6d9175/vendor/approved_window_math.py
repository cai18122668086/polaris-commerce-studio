import numpy as np
from .apple_minimal import visual as approved_visual
W,H=1080,1920
def fade(im,q):
 im=im.copy();im.putalpha(im.getchannel('A').point([round(a*max(0,min(1,q))) for a in range(256)]));return im

def lerp(keys,n):
 if n<=keys[0][0]:return keys[0][1]
 for (a,v),(b,w) in zip(keys,keys[1:]):
  if a<=n<=b:return np.asarray(v)*(1-(n-a)/(b-a))+np.asarray(w)*(n-a)/(b-a)
 return keys[-1][1]

def v02(raw,matrix,rect,radius):
 key=dict(time=0,matrix=[[float(matrix[0]),0,float(matrix[2])/2],[0,float(matrix[1]),float(matrix[3])/2]],rect=[float(v)/2 for v in rect],radius=float(radius)/2,background_opacity=0)
 return approved_visual.render('V02',raw,0,dict(size=[W,H],fps=25,stage_color=[17,17,24],visual_keys=[key]))['presenter']