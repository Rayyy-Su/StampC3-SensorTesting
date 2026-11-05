"""Generate editable plans. Default tones/widths are starting choices, not measured limits."""
import argparse
import csv
from pathlib import Path
import numpy as np

FIELDS=['chapter','test_name','surface_value','trial_num','samples','settle_ms','timeout_ms',
        'rectangle_width_mm','direction','position_mm','target_sensor','split']

def make_plan(chapter, tones, positions, widths, sensor, offwhite_tone=200):
    rows=[]
    def add(test, tone, trial, n=200, **extra):
        rows.append(dict(chapter=chapter,test_name=test,surface_value=tone,trial_num=trial,
                         samples=n,settle_ms=2000,timeout_ms=max(30000,n*30),**extra))
    if chapter==1:
        for tone in [255,0]: add('readingTest',tone,1)
    elif chapter==2:
        for test,tone in [('offsetTest_white',255),('offsetTest_offwhite',offwhite_tone)]:
            for trial in range(1,4): add(test,tone,trial)
    elif chapter==3:
        for trial,order in [(1,sorted(tones,reverse=True)),(2,sorted(tones))]:
            for tone in order: add('saturationTest',tone,trial)
    elif chapter in (4,5):
        if len(tones)<4: raise ValueError('Use at least four distinct surface conditions')
        # Entire surface conditions, not random rows, are held out.
        held=set(tones[1::3])
        rng=np.random.default_rng(2026)
        for trial in range(1,4):
            for tone in rng.permutation(tones):
                add('responseTest',int(tone),trial,split='held_out' if tone in held else 'fit')
    elif chapter==6:
        if len(tones)<2: raise ValueError('Noise requires two or more non-saturated tones')
        for trial in range(1,4):
            for tone in tones: add('noiseTest',tone,trial,1000,split='held_out' if trial==3 else 'fit')
    elif chapter==7:
        for test,tone in [('footprintWhiteReference',255),('footprintBlackReference',0)]:
            for trial in range(1,4): add(test,tone,trial,target_sensor=sensor)
        for width in widths:
            for trial,direction,order in [(1,'increasing',positions),(2,'decreasing',positions[::-1])]:
                for pos in order:
                    add('footprintTest',0,trial,50,rectangle_width_mm=width,direction=direction,
                        position_mm=round(float(pos),4),target_sensor=sensor)
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--chapter',type=int,choices=range(1,8),required=True)
    p.add_argument('--tones',type=int,nargs='+',default=[255,220,180,140,100,60,0])
    p.add_argument('--offwhite-tone',type=int,default=200)
    p.add_argument('--widths',type=float,nargs='+',default=[1,3,8])
    p.add_argument('--start',type=float,default=-10);p.add_argument('--stop',type=float,default=10)
    p.add_argument('--step',type=float,default=1);p.add_argument('--sensor',type=int,choices=range(5),default=2)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if len(set(a.tones))!=len(a.tones) or any(not 0<=t<=255 for t in a.tones):p.error('Use distinct tones in 0..255')
    if not all(np.isfinite([a.start,a.stop,a.step,*a.widths])) or a.step<=0 or a.stop<a.start or any(w<=0 for w in a.widths):p.error('Invalid geometry')
    if len(set(a.widths)) != len(a.widths):p.error('Use distinct strip widths')
    if (a.stop-a.start)/a.step >= 10000:p.error('Too many positions')
    positions=np.arange(a.start,a.stop+a.step/100,a.step)
    if len(positions)>10000:p.error('Too many positions')
    if not 0 <= a.offwhite_tone < 255:p.error("Off-white tone must be 0..254")
    rows=make_plan(a.chapter,a.tones,positions,a.widths,a.sensor,a.offwhite_tone)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    print(f'{len(rows)} captures -> {a.output}. Review actual tones, widths and placement before use.')
if __name__=='__main__':main()
