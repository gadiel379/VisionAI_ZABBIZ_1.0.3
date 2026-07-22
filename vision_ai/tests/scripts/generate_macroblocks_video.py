import cv2
import numpy as np
import os
W,H=1280,720
FPS=30
DURATION=60
os.makedirs("tests/output",exist_ok=True)
out="tests/output/Macroblocks_Test.mp4"
vw=cv2.VideoWriter(out,cv2.VideoWriter_fourcc(*"mp4v"),FPS,(W,H))
def macro(img,x,y,w,h,size):
    r=img[y:y+h,x:x+w]
    s=cv2.resize(r,(max(1,w//size),max(1,h//size)))
    r2=cv2.resize(s,(w,h),interpolation=cv2.INTER_NEAREST)
    img[y:y+h,x:x+w]=r2
for i in range(FPS*DURATION):
    t=i/FPS
    img=np.full((H,W,3),35,np.uint8)
    cv2.putText(img,"VISION AI TEST",(40,60),0,1.4,(255,255,255),3)
    cv2.putText(img,f"{t:05.2f}s",(1020,60),0,1,(0,255,255),2)
    x=int((t*180)%(W+200))-100
    cv2.rectangle(img,(x,250),(x+180,430),(0,180,255),-1)
    y=int(np.sin(t)*120+360)
    cv2.circle(img,(800,y),70,(255,100,0),-1)
    cv2.line(img,(0,650),(W,650),(255,255,255),2)
    if 10<=t<20: macro(img,200,150,420,260,8)
    if 20<=t<30: macro(img,100,100,700,450,16)
    if 30<=t<40:
        macro(img,500,180,700,420,16)
        macro(img,120,420,250,180,8)
    if 50<=t<60: macro(img,0,0,W,H,16)
    vw.write(img)
vw.release()
print(out)
