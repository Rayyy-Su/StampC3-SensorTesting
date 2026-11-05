"""Reproducible per-channel reflectance analysis. Outputs never replace raw CSV."""
import argparse
import json
import os
from pathlib import Path
import tempfile
os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir())/'reflectance_mpl'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sensor_io import load_data, snapshot_times, quality_report, BASE


def save_table(df, out, name):
    df.to_csv(out/f'{name}.csv', index=False)


def save_fig(fig, out, name):
    fig.tight_layout(); fig.savefig(out/f'{name}.png', dpi=160); plt.close(fig)


def trial_summary(data):
    keys=['session_id','run_id','test_name','surface_value','trial_num','sensor_num']
    return data.groupby(keys, dropna=False, as_index=False).agg(
        samples=('sensor_reading','size'),mean_us=('sensor_reading','mean'),
        median_us=('sensor_reading','median'),sd_us=('sensor_reading','std'),
        min_us=('sensor_reading','min'),max_us=('sensor_reading','max'),
        mad_us=('sensor_reading',lambda x: np.median(np.abs(x-np.median(x)))))


def common_plots(data, out):
    summary=trial_summary(data); save_table(summary,out,'placement_summary')
    fig,axes=plt.subplots(5,1,figsize=(11,12))
    for (session,run,sensor),g in data.groupby(['session_id','run_id','sensor_num'],sort=False):
        t=snapshot_times(g)
        axes[int(sensor)].plot(t.elapsed_s,t.sensor_reading,alpha=.7,label=f'{str(run)[:8]} f={g.surface_value.iloc[0]}')
        axes[int(sensor)].set(ylabel=f'Sensor {sensor} (us)',xlabel='Elapsed time within capture (s)')
    if data.run_id.nunique()<=8: axes[0].legend(fontsize=7)
    save_fig(fig,out,'time_traces')
    return summary


def offset(data, out):
    white=data[data.test_name=='offsetTest_white']
    if white.empty: raise ValueError('Need offsetTest_white measurements')
    stats=trial_summary(white)
    refs=stats.groupby('sensor_num',as_index=False).agg(
        white_reference_us=('median_us','median'),between_placement_sd_us=('median_us','std'),
        typical_within_sd_us=('sd_us','median'),placements=('run_id','size'))
    refs['offset_from_common_reference_us']=refs.white_reference_us-refs.white_reference_us.median()
    # Placement-level bootstrap: individual correlated snapshots are not independent trials.
    rng=np.random.default_rng(2026)
    bounds=[]
    for sensor,g in stats.groupby('sensor_num'):
        centres=g.median_us.to_numpy()
        if len(centres)>=3:
            b=np.median(rng.choice(centres,(5000,len(centres)),replace=True),axis=1)
            lo,hi=np.quantile(b,[.025,.975])
        else: lo=hi=np.nan
        bounds.append(dict(sensor_num=sensor,placement_bootstrap_low_us=lo,placement_bootstrap_high_us=hi))
    refs=refs.merge(pd.DataFrame(bounds),on='sensor_num');save_table(refs,out,'baseline')
    fig,axes=plt.subplots(1,5,figsize=(15,4))
    for sensor,g in white.groupby('sensor_num'):
        groups=list(g.groupby(['session_id','run_id'],sort=False))
        axes[int(sensor)].boxplot([v.sensor_reading for _,v in groups])
        axes[int(sensor)].set(title=f'Sensor {sensor}',xlabel='Placement',ylabel='Reading (us)')
    save_fig(fig,out,'white_boxplots')
    check=data[data.test_name=='offsetTest_offwhite']
    if not check.empty:
        c=trial_summary(check).merge(refs,on='sensor_num',validate='many_to_one')
        c['white_relative_change_us']=c.median_us-c.white_reference_us
        save_table(c,out,'offwhite_check')
    (out/'interpretation.txt').write_text('White baselines are operational references, not hidden middleware parameters.\n'
        'Bootstrap intervals resample placement medians; with few placements coverage is weak and systematic errors are not included.\n')


def saturation(data,out):
    if data.surface_value.nunique()<3: raise ValueError('Use at least three distinct tones to inspect a plateau')
    s=data.groupby(['sensor_num','surface_value'],as_index=False).agg(
        samples=('sensor_reading','size'),typical_us=('sensor_reading','median'),sd_us=('sensor_reading','std'))
    s=s.sort_values(['sensor_num','surface_value'],ascending=[True,False])
    s['previous_fill']=s.groupby('sensor_num').surface_value.shift()
    s['median_change_us']=s.groupby('sensor_num').typical_us.diff().abs()
    s['local_sd_us']=(s.sd_us+s.groupby('sensor_num').sd_us.shift())/2
    s['not_separated']=s.median_change_us<=s.local_sd_us
    save_table(s,out,'response_summary')
    # Preserve pass-specific evidence rather than relying only on pooled trials.
    per=data.groupby(['session_id','trial_num','sensor_num','surface_value'],as_index=False).agg(
        median_us=('sensor_reading','median'),sd_us=('sensor_reading','std'),samples=('sensor_reading','size'))
    save_table(per,out,'per_trial_response')
    fig,axes=plt.subplots(1,5,figsize=(17,4))
    for sensor,g in data.groupby('sensor_num'):
        tones=sorted(g.surface_value.unique(),reverse=True)
        axes[int(sensor)].boxplot([g[g.surface_value==f].sensor_reading for f in tones])
        axes[int(sensor)].set_xticks(range(1,len(tones)+1),[str(f) for f in tones])
        axes[int(sensor)].tick_params(axis='x',rotation=60)
        axes[int(sensor)].set(title=f'Sensor {sensor}',xlabel='Printed fill (light to dark)',ylabel='Reading (us)')
    save_fig(fig,out,'surface_boxplots')
    fig,ax=plt.subplots(figsize=(9,5))
    for sensor,g in s.groupby('sensor_num'):ax.errorbar(g.surface_value,g.typical_us,yerr=g.sd_us,marker='o',label=f'Sensor {sensor}')
    ax.invert_xaxis();ax.set(xlabel='Printed fill (255 white, 0 black)',ylabel='Median ± SD (us)');ax.legend();save_fig(fig,out,'median_response')
    template={str(i):dict(usable_fill_min=None,usable_fill_max=None,upper_reference_us=None,upper_reference_kind='black_reference',
                         linear_fill_min=None,linear_fill_max=None) for i in range(5)}
    (out/'calibration_template.json').write_text(json.dumps(template,indent=2))
    (out/'interpretation.txt').write_text('not_separated is a screening rule, not proof of saturation.\n'
        'Inspect consecutive pairs and independent passes; enter justified usable/linear ranges and upper_reference_us in the template.\n'
        'Null limits are intentional: the program does not invent unmeasured thresholds.\n')


def baseline_map(path):
    if not path:raise ValueError('--baseline must select the Chapter 02 baseline.csv')
    b=pd.read_csv(path)
    if set(b.sensor_num)!=set(range(5)) or b.sensor_num.duplicated().any():raise ValueError('Need one baseline per sensor')
    if not np.isfinite(b.white_reference_us).all() or not b.white_reference_us.between(0,65535).all():
        raise ValueError('Baselines must be finite raw-unit readings in 0..65535')
    return b.set_index('sensor_num').white_reference_us.to_dict()


def split_conditions(data):
    if 'split' not in data or not data['split'].isin(['fit','held_out']).all():
        raise ValueError('Response fits require explicit fit/held_out labels on every row')
    if (data.groupby('surface_value')['split'].nunique()>1).any():
        raise ValueError('Hold out complete surface conditions, not individual rows')
    if not {'fit','held_out'}<=set(data['split']):raise ValueError('Need both fitting and held-out conditions')


def response(data,out,args,nonlinear=False):
    split_conditions(data)
    baselines=baseline_map(args.baseline)
    cfg=json.loads(args.calibration.read_text()) if args.calibration else {}
    predictions=[]; parameters=[]; scores=[]
    normalized=[]; gamma_fits=[]
    fig,axes=plt.subplots(5,2,figsize=(13,18))
    for sensor,g in data.groupby('sensor_num'):
        sensor=int(sensor);c=cfg.get(str(sensor),{})
        usable=args.usable_range or [c.get('usable_fill_min'),c.get('usable_fill_max')]
        if any(x is None for x in usable) or not 0<=usable[0]<usable[1]<=255:
            raise ValueError('Supply justified --usable-range DARK LIGHT or calibration JSON limits')
        g=g.copy();g['baseline_adjusted_us']=g.sensor_reading-baselines[sensor]
        means=g.groupby(['surface_value','split'],as_index=False).agg(
            reading_us=('sensor_reading','mean'),adjusted_us=('baseline_adjusted_us','mean'),sd_us=('sensor_reading','std'))
        valid=means.surface_value.between(*usable)
        fit=valid & means['split'].eq('fit');held=valid & means['split'].eq('held_out')
        if fit.sum()<2 or not held.any():raise ValueError(f'Sensor {sensor}: not enough usable fit/held-out conditions')
        models={}
        if not nonlinear:
            linear=args.fit_range or [c.get('linear_fill_min'),c.get('linear_fill_max')]
            if any(v is None for v in linear) or not usable[0]<=linear[0]<linear[1]<=usable[1]:
                raise ValueError('Supply justified --fit-range DARK LIGHT inside usable range')
            chosen=fit & means.surface_value.between(*linear)
            if chosen.sum()<2:raise ValueError('Linear region needs two or more fitting conditions; use >=4 where feasible')
            m,b=np.polyfit(means.loc[chosen,'surface_value'],means.loc[chosen,'adjusted_us'],1)
            models={'linear_fit':m*means.surface_value.to_numpy()+b}
            fit=chosen  # training score uses only the region actually fitted
            observed=means.adjusted_us.to_numpy()
            parameters.append(dict(sensor_num=sensor,slope_us_per_fill=m,intercept_adjusted_us=b,
                                   intercept_raw_us=b+baselines[sensor],fit_min=linear[0],fit_max=linear[1]))
            yname='Baseline-adjusted reading (us)'
        else:
            sat=c.get('upper_reference_us', c.get('saturation_us'))
            reference_kind=c.get('upper_reference_kind', 'plateau')
            if reference_kind not in ('plateau', 'black_reference'):
                raise ValueError('upper_reference_kind must be plateau or black_reference')
            if sat is None or not np.isfinite(sat) or sat<=baselines[sensor]:raise ValueError(f'Sensor {sensor}: need upper_reference_us > white baseline')
            u=(usable[1]-means.surface_value.to_numpy())/(usable[1]-usable[0])
            v=(means.reading_us.to_numpy()-baselines[sensor])/(sat-baselines[sensor])
            if fit.sum()<3:raise ValueError('Quadratic needs at least three distinct fit conditions; collect more for assessment')
            uf=u[fit];vf=v[fit]
            result=minimize_scalar(lambda gamma:np.mean((vf-uf**gamma)**2),bounds=(.05,10),method='bounded')
            gamma=float(result.x);poly=np.polyfit(uf,vf,2)
            models={'linear_reference':u,'power':np.where(valid,np.maximum(u,0)**gamma,np.nan),
                    'quadratic':np.polyval(poly,u)}
            observed=v
            parameters.append(dict(sensor_num=sensor,gamma=gamma,quadratic_C=poly[0],quadratic_B=poly[1],quadratic_A=poly[2],
                                   usable_fill_min=usable[0],usable_fill_max=usable[1],upper_reference_us=sat,upper_reference_kind=reference_kind))
            gamma_fits.append((sensor,uf,vf))
            norm=means.copy();norm['sensor_num']=sensor;norm['u']=u;norm['v']=v;normalized.append(norm)
            yname='Normalised response (unclipped)'
        ax,resax=axes[sensor]
        ax.scatter(means.surface_value,observed,c=np.where(means['split'].eq('held_out'),'orange','black'),label='Condition means (orange: held-out)')
        order=np.argsort(means.surface_value)
        for name,pred in models.items():
            ax.plot(means.surface_value.to_numpy()[order],np.asarray(pred)[order],label=name)
            residual=observed-pred
            resax.plot(means.surface_value,residual,'-',alpha=.5,label=name)
            for split, marker in [('fit','o'),('held_out','x')]:
                mask=means['split'].eq(split)
                resax.scatter(means.loc[mask,'surface_value'],np.asarray(residual)[mask],marker=marker,
                              s=20,label=f'{name}: {split}')
            for split,mask in [('fit',fit),('held_out',held)]:
                scores.append(dict(sensor_num=sensor,model=name,split=split,conditions=int(mask.sum()),
                                   mae=float(np.mean(np.abs(residual[mask]))),rmse=float(np.sqrt(np.mean(residual[mask]**2)))))
            for k,row in means.iterrows():
                predictions.append(dict(sensor_num=sensor,surface_value=row.surface_value,split=row['split'],
                    inside_usable=bool(valid.iloc[k]),observed=observed[k],predicted=pred[k],residual=residual[k],model=name))
        ax.set(title=f'Sensor {sensor}',ylabel=yname,xlabel='Printed fill');ax.legend(fontsize=7)
        resax.axhline(0,color='gray');resax.set(ylabel='Residual',xlabel='Printed fill');resax.legend(fontsize=7)
    save_fig(fig,out,'response_and_residuals');save_table(pd.DataFrame(predictions),out,'predictions')
    save_table(pd.DataFrame(scores),out,'model_scores');save_table(pd.DataFrame(parameters),out,'model_parameters')
    if nonlinear:
        norm=pd.concat(normalized,ignore_index=True);save_table(norm,out,'normalized_condition_means')
        shared=minimize_scalar(lambda gamma:np.mean([np.mean((v-u**gamma)**2) for _,u,v in gamma_fits]),bounds=(.05,10),method='bounded').x
        shared_scores=[]
        fig,ax=plt.subplots(figsize=(9,5))
        for sensor,g in norm.groupby('sensor_num'):
            g=g.sort_values('u');valid=g.u.between(0,1);h=g[valid & g['split'].eq('held_out')]
            shared_scores.append(dict(sensor_num=sensor,shared_gamma=shared,held_out_mae=float(np.mean(abs(h.v-h.u**shared)))))
            ax.plot(g.loc[valid,'u'],g.loc[valid,'v'],'o-',label=f'Sensor {sensor}')
        ax.set(xlabel='Normalised printed condition u',ylabel='Normalised response v');ax.legend();save_fig(fig,out,'all_channel_normalized')
        save_table(pd.DataFrame(shared_scores),out,'shared_gamma_scores')


def noise(data,out,args):
    if data.surface_value.nunique()<2:raise ValueError('Noise comparison needs at least two non-saturated operating points')
    # Keep trial-level split, independent of any fit/held_out CONDITION labels from gain.
    train=data[data.trial_num!=args.holdout_trial];test=data[data.trial_num==args.holdout_trial]
    if train.empty or test.empty:raise ValueError('Need fitting trials and --holdout-trial')
    summaries=trial_summary(data);save_table(summaries,out,'noise_trial_summary')
    residuals=[];models=[];checks=[];correlations=[]
    for (sensor,tone),g in data.groupby(['sensor_num','surface_value']):
        groups=[]
        for (session,run),trial in g.groupby(['session_id','run_id']):
            if len(trial)<3:raise ValueError('Noise analysis requires at least three fresh snapshots per placement')
            trial=snapshot_times(trial)
            centre=float(trial.sensor_reading.mean());trial['residual_us']=trial.sensor_reading-centre
            trial['trial_center_us']=centre
            residuals.append(trial)
            values=trial.residual_us.to_numpy();sd=np.std(values,ddof=1)
            acf1=float(np.corrcoef(values[:-1],values[1:])[0,1]) if np.std(values[:-1])>0 and np.std(values[1:])>0 else np.nan
            correlations.append(dict(sensor_num=sensor,surface_value=tone,run_id=run,lag1_correlation=acf1,
                                     trial_center_us=centre,held_out=bool(trial.trial_num.iloc[0]==args.holdout_trial)))
            groups.append(trial)
        fit_groups=[t for t in groups if t.trial_num.iloc[0]!=args.holdout_trial]
        held_groups=[t for t in groups if t.trial_num.iloc[0]==args.holdout_trial]
        if len(fit_groups)<2 or not held_groups:raise ValueError('Each noise point needs >=2 fitting placements and >=1 held-out placement')
        fit=pd.concat(fit_groups);held=pd.concat(held_groups)
        e=fit.residual_us.to_numpy();h=held.residual_us.to_numpy()
        mu=float(e.mean());sd=float(e.std(ddof=1));lo=float(e.min());hi=float(e.max())
        center=float(np.mean([t.trial_center_us.iloc[0] for t in fit_groups]))
        models.append(dict(sensor_num=sensor,surface_value=tone,gaussian_mean_us=mu,gaussian_sd_us=sd,
                           uniform_low_us=lo,uniform_high_us=hi,fit_center_us=center))
        checks.append(dict(sensor_num=sensor,surface_value=tone,held_samples=len(h),held_sd_us=np.std(h,ddof=1),
            gaussian_within_1sd=np.mean(abs(h-mu)<=sd),gaussian_within_2sd=np.mean(abs(h-mu)<=2*sd),
            uniform_outside_fraction=np.mean((h<lo)|(h>hi)),
            held_center_shift_us=float(held.sensor_reading.mean()-center)))
        fig,axes=plt.subplots(1,2,figsize=(11,4))
        for t in groups:axes[0].plot(t.elapsed_s,t.residual_us,label=f'trial {t.trial_num.iloc[0]}')
        axes[0].set(xlabel='Time within capture (s)',ylabel='Trial-centred residual (us)');axes[0].legend()
        axes[1].hist(e,bins='auto',density=True,alpha=.45,label='Fit residuals')
        axes[1].hist(h,bins='auto',density=True,alpha=.45,label='Held residuals')
        if sd>0:
            x=np.linspace(min(e.min(),h.min()),max(e.max(),h.max()),200)
            axes[1].plot(x,np.exp(-.5*((x-mu)/sd)**2)/(sd*np.sqrt(2*np.pi)),label='Gaussian')
        if hi>lo:axes[1].plot([lo,lo,hi,hi],[0,1/(hi-lo),1/(hi-lo),0],label='Uniform')
        axes[1].set(xlabel='Residual (us)',ylabel='Density');axes[1].legend()
        save_fig(fig,out,f'noise_sensor{sensor}_fill{tone:g}')
    save_table(pd.concat(residuals),out,'noise_residuals');save_table(pd.DataFrame(models),out,'noise_models')
    save_table(pd.DataFrame(checks),out,'held_out_noise_checks');save_table(pd.DataFrame(correlations),out,'time_correlation')
    (out/'interpretation.txt').write_text('Held trials are centred with their own mean ONLY for short-term residual-shape checks.\n'
        'Their mean shift is separately reported, not predicted away. Model bounds/spread are frozen from fitting trials.\n'
        '68/95 percent are reference coverage values, not pass tests. Inspect drift, quantisation, correlation and clipping before assuming IID noise.\n')


def footprint(data,out,args):
    refs=load_data(args.references) if args.references else data
    if not args.allow_simulated and refs.session_id.astype(str).str.contains('SIMULATED',case=False).any():
        raise ValueError('Synthetic footprint references require --allow-simulated')
    ref=refs[refs.test_name.isin(['footprintWhiteReference','footprintBlackReference'])]
    if ref.empty:raise ValueError('Need refreshed footprint white/black references (same environment/material)')
    rs=ref.groupby(['sensor_num','test_name'],as_index=False).agg(reference_us=('sensor_reading','median'),sd_us=('sensor_reading','std'))
    save_table(rs,out,'footprint_references')
    scans=data[data.test_name=='footprintTest'].copy()
    for col in ['position_mm','rectangle_width_mm','direction','target_sensor']:
        if col not in scans or scans[col].isna().any():raise ValueError(f'Footprint scans need {col}')
    if not scans.direction.isin(['increasing','decreasing']).all() or not scans.rectangle_width_mm.gt(0).all():
        raise ValueError('Invalid footprint direction or strip width')
    if not scans.target_sensor.isin(range(5)).all():raise ValueError('target_sensor must be 0..4')
    scans=scans[scans.sensor_num==scans.target_sensor]
    if scans.empty:raise ValueError('No scans aligned to target_sensor')
    profiles=[];peaks=[]
    for sensor,g in scans.groupby('sensor_num'):
        r=rs[rs.sensor_num==sensor].set_index('test_name')
        if not {'footprintWhiteReference','footprintBlackReference'}<=set(r.index):raise ValueError('Missing white/black reference')
        W=r.loc['footprintWhiteReference','reference_us'];B=r.loc['footprintBlackReference','reference_us']
        if B<=W:raise ValueError('Black reference must exceed white reference')
        summary=g.groupby(['session_id','trial_num','rectangle_width_mm','direction','position_mm'],as_index=False).agg(
            median_us=('sensor_reading','median'),sd_us=('sensor_reading','std'),samples=('sensor_reading','size'))
        summary['sensor_num']=sensor;summary['normalized']=(summary.median_us-W)/(B-W);profiles.append(summary)
        fig,ax=plt.subplots(figsize=(11,5))
        for (session,trial,width,direction),s in summary.groupby(['session_id','trial_num','rectangle_width_mm','direction']):
            s=s.sort_values('position_mm')
            ax.errorbar(s.position_mm,s.normalized,yerr=s.sd_us/(B-W),marker='.',label=f'w={width:g}, trial={trial}, {direction}')
            # Plan uses strip centre as position zero.
            ax.axvline(-width/2,alpha=.15,color='black');ax.axvline(width/2,alpha=.15,color='black')
            peak=s.loc[s.median_us.idxmax()]
            tolerance=max(float(r.loc['footprintBlackReference','sd_us']),float(peak.sd_us))
            peaks.append(dict(sensor_num=sensor,session_id=session,trial_num=trial,rectangle_width_mm=width,
                direction=direction,peak_us=peak.median_us,peak_normalized=peak.normalized,
                peak_position_mm=peak.position_mm,black_reference_us=B,screen_tolerance_us=tolerance,
                near_black_screen=bool(abs(peak.median_us-B)<=tolerance)))
        ax.axhline(0,color='gray');ax.axhline(1,color='gray',linestyle='--')
        ax.set(title=f'Sensor {sensor}: position zero = strip centre',xlabel='Measured position (mm)',ylabel='(reading-W)/(B-W), unclipped');ax.legend(fontsize=7)
        save_fig(fig,out,f'footprint_sensor{sensor}')
    save_table(pd.concat(profiles),out,'spatial_profiles');save_table(pd.DataFrame(peaks),out,'strip_peaks')
    (out/'interpretation.txt').write_text('near_black_screen compares peak with black reference using repeated spread; it is not a physical footprint estimator.\n'
        'Confirm across independently registered traverses. Edge lines assume measured strip centre is position zero.\n'
        'One-dimensional profiles do not establish a unique two-dimensional footprint.\n')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,nargs='+',required=True);p.add_argument('--chapter',type=int,choices=range(1,8),required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--test-name',nargs='+')
    p.add_argument('--baseline',type=Path);p.add_argument('--calibration',type=Path)
    p.add_argument('--usable-range',type=float,nargs=2,metavar=('DARK','LIGHT'))
    p.add_argument('--fit-range',type=float,nargs=2,metavar=('DARK','LIGHT'))
    p.add_argument('--holdout-trial',type=int,default=3);p.add_argument('--references',type=Path,nargs='+')
    p.add_argument('--allow-simulated',action='store_true')
    a=p.parse_args(argv)
    for name in ['usable_range','fit_range']:
        value=getattr(a,name)
        if value and (not np.isfinite(value).all() or not 0<=value[0]<value[1]<=255):
            p.error(f'--{name.replace("_","-")} needs finite DARK < LIGHT within 0..255')
    if a.holdout_trial < 1:p.error('--holdout-trial must be positive')
    data=load_data(a.inputs)
    if not a.allow_simulated and data.session_id.astype(str).str.contains('SIMULATED',case=False).any():
        p.error('Synthetic data: use --allow-simulated only for pipeline checks')
    if a.test_name:data=data[data.test_name.isin(a.test_name)].copy()
    else:
        names={1:['readingTest'],2:['offsetTest_white','offsetTest_offwhite'],3:['saturationTest'],
               4:['responseTest'],5:['responseTest'],6:['noiseTest'],
               7:['footprintTest','footprintWhiteReference','footprintBlackReference']}[a.chapter]
        data=data[data.test_name.isin(names)].copy()
    if a.chapter==6 and a.usable_range:
        data=data[data.surface_value.between(*a.usable_range)].copy()
    if data.empty:p.error('No selected rows; check --test-name, range and inputs')
    if a.chapter != 2 and data.surface_value.isna().any():
        p.error('Every selected row needs a known printed surface_value')
    report=quality_report(data)
    a.output.mkdir(parents=True,exist_ok=False)
    provenance=dict(chapter=a.chapter,inputs=[str(x.resolve()) for x in a.inputs],test_names=sorted(data.test_name.unique()),
                    baseline=str(a.baseline.resolve()) if a.baseline else None,
                    calibration=str(a.calibration.resolve()) if a.calibration else None,
                    usable_range=a.usable_range,fit_range=a.fit_range,holdout_trial=a.holdout_trial,
                    simulated=bool(data.session_id.astype(str).str.contains('SIMULATED',case=False).any()),
                    references=[str(x.resolve()) for x in a.references] if a.references else [])
    (a.output/'analysis_settings.json').write_text(json.dumps(provenance,indent=2))
    save_table(report,a.output,'quality_report');common_plots(data,a.output)
    if a.chapter==2:offset(data,a.output)
    elif a.chapter==3:saturation(data,a.output)
    elif a.chapter in (4,5):response(data,a.output,a,nonlinear=a.chapter==5)
    elif a.chapter==6:noise(data,a.output,a)
    elif a.chapter==7:footprint(data,a.output,a)
    (a.output/'analysis_complete.json').write_text(json.dumps({'status':'COMPLETE','chapter':a.chapter}))
    print(f'Analysis saved to {a.output.resolve()}')
    return 0
if __name__=='__main__':raise SystemExit(main())
