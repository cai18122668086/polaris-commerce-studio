from PIL import Image,ImageDraw
import numpy as np
W,H=1080,1920
def blank():return Image.new('RGBA',(W,H))

def normalize(im):
 a=np.array(im.convert('RGBA'));a[a[:,:,3]==0,:3]=0;return Image.fromarray(a)

def opacity(im,q):
 if q>=1:return im
 out=im.copy();out.putalpha(out.getchannel('A').point(lambda x:round(x*max(0,q))));return out

def quadmask(poly,radius=0):
 scale=2;pts=np.array(poly,float);path=[]
 for i,p in enumerate(pts):
  a=pts[(i-1)%4]-p;b=pts[(i+1)%4]-p;r=min(radius,np.linalg.norm(a)/3,np.linalg.norm(b)/3)
  if r<=0:path.append(tuple(p*scale));continue
  a=p+a/np.linalg.norm(a)*r;b=p+b/np.linalg.norm(b)*r
  for q in np.linspace(0,1,9):path.append(tuple(((1-q)**2*a+2*(1-q)*q*p+q*q*b)*scale))
 m=Image.new('L',(2160,3840));ImageDraw.Draw(m).polygon(path,fill=255);return m.resize((1080,1920),Image.Resampling.LANCZOS)
