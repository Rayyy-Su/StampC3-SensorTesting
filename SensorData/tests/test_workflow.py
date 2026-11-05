"""Offline contract and scientific-workflow checks; no robot measurements are claimed."""
from pathlib import Path
import sys
import tempfile
import json
import io
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from RecordSensorData import SimulatedSerial, Connection, capture, validate_row
from sensor_io import load_data, canonicalize, snapshot_times, quality_report
from AnalyzeSensorData import main as analyze


def dataset(test, tones, trials=(1,2,3), n=20, chapter=2, **extra):
    rng=np.random.default_rng(17);rows=[]
    for tone in tones:
        for trial in trials:
            run=f'{test}_{tone}_{trial}'
            for sample in range(1,n+1):
                for sensor in range(5):
                    shift=1800*((255-tone)/255)**1.6
                    rows.append(dict(test_name=test,surface_value=tone,trial_num=trial,sample_num=sample,
                        sample_time=sample*10000,sensor_num=sensor,sensor_reading=int(round(250+sensor*20+shift+rng.normal(0,5))),
                        session_id='SIMULATED_fixture',run_id=run,chapter=chapter,**extra))
    return pd.DataFrame(rows)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_protocol_capture(self):
        row=validate_row(dict(test_name='readingTest',surface_value=255,samples=12))
        dev=SimulatedSerial();c=Connection(dev,io.StringIO())
        p=capture(c,row,self.root,'SIMULATED_test')
        d=load_data([p]);self.assertEqual(len(d),60)
        self.assertEqual(quality_report(d).snapshots.iloc[0],12)
        self.assertEqual(json.loads(p.with_suffix('.json').read_text())['status'],'COMPLETE')
    def test_zero_settling_is_preserved_and_zero_samples_rejected(self):
        row=validate_row(dict(test_name='readingTest',surface_value=255,settle_ms=0))
        self.assertEqual(row['settle_ms'],0)
        with self.assertRaises(ValueError):
            validate_row(dict(test_name='readingTest',surface_value=255,samples=0))
        with self.assertRaises(ValueError):
            validate_row(dict(test_name='readingTest',surface_value=255,samples=1.5))
    def test_fragmented_serial_capture(self):
        class Fragmented(SimulatedSerial):
            def __init__(self): super().__init__();self.remainder=b''
            def readline(self):
                if self.remainder:
                    raw=self.remainder;self.remainder=b'';return raw
                raw=super().readline()
                if len(raw)>4:
                    self.remainder=raw[4:];return raw[:4]
                return raw
        row=validate_row(dict(test_name='readingTest',surface_value=255,samples=4))
        path=capture(Connection(Fragmented(),io.StringIO()),row,self.root,'SIMULATED_fragments')
        self.assertEqual(len(load_data([path])),20)
    def test_ack_matching_does_not_accept_run_prefix(self):
        class Source:
            def __init__(self):self.lines=iter([b'#ACK,CONFIG,abc_extra\n',b'#ACK,CONFIG,abc\n'])
            def readline(self):return next(self.lines,b'')
        self.assertEqual(Connection(Source(),io.StringIO()).wait('#ACK,CONFIG,abc'), '#ACK,CONFIG,abc')
    def test_incomplete_metadata_rejected_by_shared_loader(self):
        p=self.root/'raw.csv';dataset('readingTest',[255],trials=(1,)).to_csv(p,index=False)
        p.with_suffix('.json').write_text(json.dumps({'status':'INCOMPLETE'}))
        with self.assertRaisesRegex(ValueError,'incomplete capture'):
            load_data([p])
    def test_run_cannot_change_its_condition(self):
        d=dataset('readingTest',[255],trials=(1,),n=2)
        d.loc[d.sample_num==2,'surface_value']=0
        with self.assertRaisesRegex(ValueError,'within one run'):canonicalize(d)
    def test_quality_includes_missing_initial_sequence(self):
        d=dataset('readingTest',[255],trials=(1,),n=3)
        d=d[d.sample_num>1]
        self.assertEqual(quality_report(canonicalize(d)).missing_sequences.iloc[0],1)
    def test_invalid_baseline_rejected(self):
        from AnalyzeSensorData import baseline_map
        p=self.root/'baseline.csv'
        pd.DataFrame({'sensor_num':range(5),'white_reference_us':[250,270,np.nan,280,290]}).to_csv(p,index=False)
        with self.assertRaisesRegex(ValueError,'finite'):baseline_map(p)
    def test_missing_serial_snapshot_fails_and_preserves_partial(self):
        class DropOne(SimulatedSerial):
            def write(self,payload):
                super().write(payload)
                if payload==b'START\n':self.queue=[line for line in self.queue if not line.startswith(f'DATA,{self.run},2,')]
        row=validate_row(dict(test_name='readingTest',surface_value=255,samples=4))
        with self.assertRaisesRegex(RuntimeError,'sequence'):
            capture(Connection(DropOne(),io.StringIO()),row,self.root,'SIMULATED_drop')
        self.assertEqual(len(list(self.root.glob('*.partial.csv'))),1)
        self.assertEqual(json.loads(next(self.root.glob('*.json')).read_text())['status'],'INCOMPLETE')
    def test_noncomplete_end_fails(self):
        class BadEnd(SimulatedSerial):
            def write(self,payload):
                super().write(payload)
                if payload==b'START\n':self.queue=[line.replace(',COMPLETE,',',TIMEOUT,') for line in self.queue]
        with self.assertRaisesRegex(RuntimeError,'Incomplete capture'):
            capture(Connection(BadEnd(),io.StringIO()),validate_row(dict(test_name='readingTest',surface_value=255,samples=2)),self.root,'SIMULATED_bad')
    def test_rollover_and_backwards_time(self):
        d=pd.DataFrame(dict(sample_num=[1,2,3],sample_time=[2**32-10000,0,10000]))
        self.assertTrue(np.allclose(snapshot_times(d).elapsed_s,[0,.01,.02]))
        d.loc[2,'sample_time']=2**32-20000
        with self.assertRaises(ValueError):snapshot_times(d)
    def test_incomplete_or_duplicate_snapshot_rejected(self):
        d=dataset('offsetTest_white',[255],trials=(1,),n=2)
        with self.assertRaises(ValueError):canonicalize(d.iloc[:-1])
        with self.assertRaises(ValueError):canonicalize(pd.concat([d,d.iloc[:1]]))
    def test_response_holdout_leakage_rejected(self):
        from AnalyzeSensorData import split_conditions
        d=pd.DataFrame({'surface_value':[120,120,200],'split':['fit','held_out','fit']})
        with self.assertRaisesRegex(ValueError,'complete surface'):split_conditions(d)
    def test_legacy_darkness_requires_explicit_verification(self):
        d=dataset('saturationTest',[255]).drop(columns='surface_value');d['darkness_pct']=0
        with self.assertRaisesRegex(ValueError,'verified conversion'):canonicalize(d)
    def test_all_seven_analysis_routes(self):
        def run(ch,df,*extra):
            path=self.root/f'ch{ch}.csv';df.to_csv(path,index=False)
            out=self.root/f'result{ch}'
            self.assertEqual(analyze(['--inputs',str(path),'--chapter',str(ch),'--output',str(out),'--allow-simulated',*extra]),0)
            self.assertTrue((out/'quality_report.csv').exists());return out
        run(1,dataset('readingTest',[255,0],n=5,chapter=1))
        offset=pd.concat([dataset('offsetTest_white',[255]),dataset('offsetTest_offwhite',[240])])
        b=run(2,offset);base=str(b/'baseline.csv')
        sat=run(3,dataset('saturationTest',[255,180,100,0],chapter=3))
        tones=[240,220,200,180,160,140,120]
        d=dataset('responseTest',tones,chapter=4)
        d['split']=np.where(d.surface_value.isin([220,160]),'held_out','fit')
        c=run(4,d,'--baseline',base,'--usable-range','120','240','--fit-range','120','240')
        self.assertEqual(set(pd.read_csv(c/'model_scores.csv')['split']),{'fit','held_out'})
        cfg={str(i):dict(usable_fill_min=120,usable_fill_max=240,upper_reference_us=2050+i*20,upper_reference_kind="black_reference") for i in range(5)}
        config=self.root/'calibration.json';config.write_text(json.dumps(cfg))
        run(5,d,'--baseline',base,'--calibration',str(config))
        n=run(6,dataset('noiseTest',[220,140],n=40,chapter=6))
        models=pd.read_csv(n/'noise_models.csv');self.assertEqual(len(models),10)
        refs=pd.concat([dataset('footprintWhiteReference',[255],chapter=7),dataset('footprintBlackReference',[0],chapter=7)])
        scan=[]
        for width in [1.,3.,8.]:
            for trial,direction in [(1,'increasing'),(2,'decreasing')]:
                for pos in [-6.,-2.,0.,2.,6.]:
                    frame=dataset('footprintTest',[0],trials=(trial,),n=5,chapter=7,
                                  rectangle_width_mm=width,position_mm=pos,direction=direction,target_sensor=2)
                    frame['run_id']=frame.run_id+f'_{width}_{pos}'
                    response=np.exp(-.5*(pos/(width/2+1))**2)*min(width/5,1)
                    frame['sensor_reading']=np.rint(250+frame.sensor_num*20+1800*response).astype(int)
                    scan.append(frame)
        f=run(7,pd.concat([refs,*scan],ignore_index=True))
        self.assertEqual(set(pd.read_csv(f/'strip_peaks.csv').sensor_num),{2})

if __name__=='__main__':unittest.main()
