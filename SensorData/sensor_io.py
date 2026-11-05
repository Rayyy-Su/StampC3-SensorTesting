"""Canonical long-table loading and validation. Raw values are never corrected here."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
CORE = ['test_name', 'surface_value', 'trial_num', 'sample_num', 'sample_time',
        'sensor_num', 'sensor_reading']
EXTRA = ['session_id', 'run_id', 'chapter', 'rectangle_width_mm', 'direction',
         'position_mm', 'target_sensor', 'split', 'elapsed_us']
COLUMNS = CORE + EXTRA


def canonicalize(df, source='data'):
    df = df.copy()
    if 'timestamp_us' in df and 'sample_time' not in df:
        df = df.rename(columns={'timestamp_us': 'sample_time'})
    if 'surface_value' not in df:
        if 'darkness_pct' in df:
            raise ValueError(f'{source}: legacy darkness_pct requires verified conversion; '
                             'add surface_value explicitly after checking experiment notes')
        # The original offset notebook uses these documented labels.
        if 'test_name' in df and set(df.test_name) <= {'offsetTest_white', 'offsetTest_offwhite'}:
            df['surface_value'] = np.where(df.test_name.eq('offsetTest_white'), 255, np.nan)
        else:
            raise ValueError(f'{source}: missing surface_value')
    if all(f'reading{i}' in df for i in range(5)):
        df = df.melt(id_vars=[c for c in df if not c.startswith('reading')],
                     value_vars=[f'reading{i}' for i in range(5)],
                     var_name='sensor_num', value_name='sensor_reading')
        df['sensor_num'] = df.sensor_num.str.replace('reading', '', regex=False).astype(int)
    missing = set(CORE) - set(df)
    if missing:
        raise ValueError(f'{source}: missing columns {sorted(missing)}')
    for col in ['trial_num', 'sample_num', 'sample_time', 'sensor_num', 'sensor_reading']:
        df[col] = pd.to_numeric(df[col], errors='raise')
        if df[col].isna().any() or not np.isfinite(df[col]).all() or (df[col] % 1 != 0).any():
            raise ValueError(f'{source}: {col} must contain finite integers')
    for col in ['surface_value', 'rectangle_width_mm', 'position_mm', 'target_sensor', 'elapsed_us']:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors='raise')
            if np.isinf(df[col]).any():
                raise ValueError(f'{source}: infinite {col}')
    for col, low, high in [('sensor_num', 0, 4), ('sensor_reading', 0, 65535),
                            ('sample_time', 0, 2**32-1)]:
        if not df[col].between(low, high).all():
            raise ValueError(f'{source}: {col} out of range')
    if (df[['trial_num', 'sample_num']] < 1).any().any():
        raise ValueError(f'{source}: trial/sample numbers start at 1')
    if not df.surface_value.dropna().between(0, 255).all():
        raise ValueError(f'{source}: surface_value must be 0..255')
    if 'run_id' not in df:
        keys = ['test_name', 'surface_value', 'trial_num']
        for col in ['position_mm', 'rectangle_width_mm', 'direction']:
            if col in df: keys.append(col)
        df['run_id'] = df[keys].astype(str).agg('_'.join, axis=1)
    if 'session_id' not in df: df['session_id'] = str(source)
    if df.empty: raise ValueError(f'{source}: empty dataset')
    names = df[['test_name', 'run_id', 'session_id']]
    if names.isna().any().any() or names.astype(str).apply(lambda s: s.str.strip().eq('')).any().any():
        raise ValueError(f'{source}: missing identity labels')
    identity = ['session_id', 'run_id', 'sample_num']
    if df.duplicated(identity + ['sensor_num']).any():
        raise ValueError(f'{source}: duplicate sensor rows (possibly loading wide + split copies)')
    grouped = df.groupby(identity, sort=False)
    if grouped.size().ne(5).any() or grouped.sample_time.nunique().ne(1).any():
        raise ValueError(f'{source}: every snapshot needs five channels and one timestamp')
    # Range + unique channel rows + size five imply exactly channels 0..4.
    labels = ['test_name', 'surface_value', 'trial_num'] + [
        c for c in EXTRA if c in df and c not in ('elapsed_us', 'run_id', 'session_id')]
    if grouped[labels].nunique(dropna=False).gt(1).any().any():
        raise ValueError(f'{source}: inconsistent snapshot labels')
    run_labels = list(dict.fromkeys(['test_name', 'surface_value', 'trial_num'] + [
        c for c in EXTRA if c in df and c not in ('elapsed_us', 'run_id', 'session_id')]))
    if df.groupby(['session_id', 'run_id'])[run_labels].nunique(dropna=False).gt(1).any().any():
        raise ValueError(f'{source}: condition labels changed within one run')
    return df


def load_data(paths):
    files = []
    for text in paths:
        p = Path(text)
        files.extend(sorted(p.glob('*.csv')) if p.is_dir() else [p])
    if not files: raise ValueError('No CSV files selected')
    frames = []
    for p in files:
        if '.partial.' in p.name:
            raise ValueError(f'{p}: incomplete capture; inspect and explicitly curate it first')
        meta = p.with_suffix('.json')
        if meta.exists() and json.loads(meta.read_text()).get('status') != 'COMPLETE':
            raise ValueError(f'{p}: incomplete capture metadata')
        frames.append(canonicalize(pd.read_csv(p), p.resolve().as_posix()))
    data = pd.concat(frames, ignore_index=True)
    return canonicalize(data, 'combined data')


def snapshot_times(group):
    """Unwrap only forward uint32 deltas; reject duplicates/backwards/restarts."""
    g = group.sort_values('sample_num').copy()
    ts = g.sample_time.to_numpy(dtype=np.int64)
    dt = np.diff(ts) % 2**32
    if (dt == 0).any() or (dt >= 2**31).any():
        raise ValueError('Repeated/backward timestamp: separate reset runs; do not pool')
    g['elapsed_s'] = np.r_[0, np.cumsum(dt)] / 1e6
    return g


def quality_report(data):
    rows = []
    for (session, run), g in data.groupby(['session_id', 'run_id'], sort=False):
        s = g[g.sensor_num == 0].sort_values('sample_num')
        timed = snapshot_times(s)
        dt = np.diff(timed.elapsed_s) * 1000
        seq = s.sample_num.to_numpy()
        rows.append(dict(session_id=session, run_id=run, snapshots=len(s),
                         duration_s=timed.elapsed_s.iloc[-1], missing_sequences=int(seq[0]-1 + np.maximum(np.diff(seq)-1, 0).sum()),
                         median_dt_ms=float(np.median(dt)) if len(dt) else np.nan,
                         min_dt_ms=float(dt.min()) if len(dt) else np.nan,
                         max_dt_ms=float(dt.max()) if len(dt) else np.nan))
    return pd.DataFrame(rows)
