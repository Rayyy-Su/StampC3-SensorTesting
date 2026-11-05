"""Protocol-v1 experiment runner. Use --help; no firmware edits between trials."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
import numpy as np
import serial
from serial.tools import list_ports
from sensor_io import BASE, COLUMNS


class SimulatedSerial:
    """Protocol simulator for offline pipeline checks, never robot evidence."""
    def __init__(self, seed=2026):
        self.queue = []; self.rng = np.random.default_rng(seed); self.condition = 255
        self.team = 'UNSET'; self.ts = 0; self.run = ''; self.n = 0
    def write(self, payload):
        command = payload.decode().strip(); p = command.split()
        if command == 'STATUS': self.queue.append(f'#READY,1,LAB,{self.team}')
        elif command in ('STOP', 'MODE LAB'): self.queue.append('#ACK,STOP')
        elif command.startswith('TEAM '): self.team = command[5:]; self.queue.append('#ACK,TEAM')
        elif p[0] == 'CONFIG':
            self.run, self.n = p[1], int(p[2]); self.queue.append(f'#ACK,CONFIG,{self.run}')
        elif command == 'ARM': self.queue.append(f'#ACK,ARM,{self.run}')
        elif command == 'START':
            self.queue.extend([f'#SETTLING,{self.run}', f'#BEGIN,{self.run}'])
            for i in range(1, self.n+1):
                self.ts = (self.ts + 10000) % 2**32
                darkness = (255-self.condition)/255
                means = 250 + np.arange(5)*20 + 1800*darkness**1.6
                r = np.clip(np.rint(means+self.rng.normal(0, 8, 5)), 0, 65535).astype(int)
                self.queue.append(','.join(map(str, ['DATA', self.run, i, self.ts, *r])))
            self.queue.append(f'#END,{self.run},COMPLETE,{self.n},0,0,0')
    def readline(self):
        return (self.queue.pop(0)+'\n').encode() if self.queue else b''
    def close(self): pass


class Connection:
    def __init__(self, port, log):
        self.port = port; self.log = log
        self.pending = bytearray()
    def send(self, command):
        self.log.write('> '+command+'\n'); self.log.flush()
        self.port.write((command+'\n').encode('ascii'))
    def line(self):
        raw = self.port.readline()
        if not raw: return ''
        self.log.write('< '+repr(raw)+'\n'); self.log.flush()
        # A serial timeout can return a fragment of a perfectly valid line.
        # Keep it until a newline arrives; never parse partial records.
        self.pending.extend(raw)
        if len(self.pending) > 4096:
            raise RuntimeError('Serial line exceeds 4096 bytes')
        if not self.pending.endswith(b'\n'): return ''
        complete = bytes(self.pending); self.pending.clear()
        try: text = complete.decode('ascii').strip()
        except UnicodeDecodeError: raise RuntimeError('Non-ASCII Serial data')
        if text.startswith('#ERROR'): raise RuntimeError(text)
        return text
    def wait(self, prefix, seconds=10):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            line = self.line()
            if line == prefix or (prefix.endswith(',') and line.startswith(prefix)):
                return line
        raise TimeoutError(f'No response: {prefix}')
    def command(self, command, reply, seconds=10):
        self.send(command); return self.wait(reply, seconds)


def validate_row(row):
    r = dict(row)
    for key, default in [('samples', 200), ('settle_ms', 2000), ('timeout_ms', 30000), ('trial_num', 1), ('chapter', 1)]:
        value = r.get(key)
        if value in ('', None): value = default
        r[key] = int(value)
        if float(value) != r[key]: raise ValueError(f'{key} must be an integer')
    for key, lo, hi in [('samples',1,1000000),('settle_ms',0,60000),('timeout_ms',100,3600000),('chapter',1,7),('trial_num',1,1000000)]:
        if not lo <= r[key] <= hi: raise ValueError(f'Invalid {key}: {r[key]}')
    r['surface_value'] = float(r['surface_value'])
    if not np.isfinite(r['surface_value']) or not 0 <= r['surface_value'] <= 255:
        raise ValueError('surface_value must be 0 (black)..255 (white)')
    if not isinstance(r.get('test_name'), str) or not r['test_name'].strip():
        raise ValueError('test_name required')
    for key in ['position_mm', 'rectangle_width_mm', 'target_sensor']:
        if r.get(key) not in ('', None):
            r[key] = float(r[key])
            if not np.isfinite(r[key]): raise ValueError(f'Invalid {key}')
    if r['chapter'] == 7 and r['test_name'] == 'footprintTest':
        if any(r.get(k) in ('', None) for k in ['position_mm', 'rectangle_width_mm', 'target_sensor']):
            raise ValueError('Footprint scans need width, measured position and target sensor')
        if r['rectangle_width_mm'] <= 0 or r['target_sensor'] not in range(5):
            raise ValueError('Invalid strip width or target sensor')
        if r.get('direction') not in ('increasing', 'decreasing'): raise ValueError('Invalid direction')
    if r.get('split', '') not in ('', 'fit', 'held_out'): raise ValueError('split must be fit or held_out')
    return r


def capture(conn, row, folder, session, button=False, arm_timeout=120):
    run = uuid.uuid4().hex[:12]
    path = folder / f'{run}.csv'
    partial = path.with_suffix('.partial.csv')
    meta = dict(row, session_id=session, run_id=run, status='RUNNING', accepted=0,
                timestamp_utc=datetime.now(timezone.utc).isoformat())
    meta_path = path.with_suffix('.json')
    previous = None; last_seq = 0; elapsed = 0; began = False
    try:
        conn.command(f"CONFIG {run} {row['samples']} {row['settle_ms']} {row['timeout_ms']}", f'#ACK,CONFIG,{run}')
        conn.command('ARM', f'#ACK,ARM,{run}')
        if not button: conn.send('START')
        deadline = time.monotonic() + (arm_timeout if button else 0) + row['settle_ms']/1000 + 10
        with partial.open('x', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS); writer.writeheader()
            while time.monotonic() < deadline:
                line = conn.line()
                if not line: continue
                p = line.split(',')
                if line == f'#BEGIN,{run}':
                    if began: raise RuntimeError('Duplicate BEGIN marker')
                    began = True
                    deadline = time.monotonic() + row['timeout_ms']/1000 + 10
                elif line.startswith('#READY'): raise RuntimeError('Device restarted during capture')
                elif p[0] == '#END':
                    if len(p) != 7 or p[1] != run: raise RuntimeError('Invalid END or stale run')
                    meta.update(reason=p[2], device_samples=int(p[3]), i2c_failures=int(p[4]),
                                duplicate_snapshots=int(p[5]), tx_skips=int(p[6]))
                    if any(int(x) < 0 for x in p[3:]): raise RuntimeError('Negative END counters')
                    break
                elif p[0] == 'DATA':
                    if not began or len(p) != 9 or p[1] != run: raise RuntimeError('Invalid/out-of-run DATA')
                    seq, ts, *readings = map(int, p[2:])
                    if seq != last_seq+1 or seq > row['samples']:
                        raise RuntimeError('Missing/duplicate/excess Serial snapshot sequence')
                    if not 0 <= ts < 2**32 or any(not 0 <= x <= 65535 for x in readings):
                        raise RuntimeError('Snapshot out of range')
                    if previous is not None:
                        dt = (ts-previous) % 2**32
                        if not 0 < dt < 2**31: raise RuntimeError('Repeated/backward clock; restart run')
                        elapsed += dt
                    for sensor, value in enumerate(readings):
                        out = {k: row.get(k, '') for k in COLUMNS}
                        out.update(session_id=session, run_id=run, sample_num=seq, sample_time=ts,
                                   sensor_num=sensor, sensor_reading=value, elapsed_us=elapsed)
                        writer.writerow(out)
                    previous = ts; last_seq = seq; meta['accepted'] = seq
                    if seq % 50 == 0: f.flush(); print(f'  {seq}/{row["samples"]} snapshots')
            else: raise TimeoutError('Capture/physical-button deadline exceeded')
        if meta.get('reason') != 'COMPLETE' or last_seq != row['samples'] or meta['device_samples'] != last_seq:
            raise RuntimeError(f'Incomplete capture: {meta}')
        meta['status'] = 'COMPLETE'; partial.rename(path)
        return path
    except BaseException as exc:
        meta['status'] = 'INCOMPLETE'; meta['error'] = str(exc) or type(exc).__name__
        try: conn.send('STOP')
        except Exception: pass
        raise
    finally:
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list-ports', action='store_true'); p.add_argument('--port')
    p.add_argument('--baudrate', type=int, default=115200)
    p.add_argument('--config', type=Path, default=BASE/'session_config.json')
    p.add_argument('--team', help='Record label only; does not set robot middleware'); p.add_argument('--session'); p.add_argument('--plan', type=Path)
    p.add_argument('--chapter', type=int, choices=range(1,8), default=1)
    p.add_argument('--test-name', default='readingTest'); p.add_argument('--surface-value', type=float, default=255)
    p.add_argument('--trial', type=int, default=1); p.add_argument('--samples', type=int, default=200)
    p.add_argument('--settle-ms', type=int, default=2000); p.add_argument('--max-seconds', type=float, default=30)
    p.add_argument('--button', action='store_true'); p.add_argument('--yes', action='store_true')
    p.add_argument('--simulate', action='store_true', help='Synthetic protocol check; output is not robot evidence')
    p.add_argument('--output-dir', type=Path, default=BASE/'records')
    args=p.parse_args()
    if args.list_ports:
        for port in list_ports.comports(): print(port.device, port.description)
        return 0
    try:
        cfg=json.loads(args.config.read_text()) if args.config.exists() else {}
        if not isinstance(cfg, dict): raise ValueError('Configuration must be a JSON object')
    except (OSError, ValueError) as exc: p.error(str(exc))
    team=args.team or cfg.get('team_name', '')
    if args.simulate: team='SIMULATION'
    if not isinstance(team, str) or not team.strip() or team == 'YOUR_TEAM_NAME':
        p.error('Set team_name in session_config.json or pass --team')
    if not team.isascii() or not all(32 <= ord(c) < 127 for c in team) or ',' in team or len(team)>31:
        p.error('Team must be 1..31 printable ASCII characters, without commas')
    if args.plan and args.yes and not args.simulate: p.error('--yes is only allowed for a single real capture; plans require placement confirmation')
    if args.simulate and args.button: p.error('Simulation uses host start, not --button')
    try:
        if args.baudrate <= 0: raise ValueError('baudrate must be positive')
        if not np.isfinite(args.max_seconds): raise ValueError('max-seconds must be finite')
        if args.plan:
            with args.plan.open(newline='', encoding='utf-8-sig') as f: rows=[validate_row(r) for r in csv.DictReader(f)]
        else:
            rows=[validate_row(dict(chapter=args.chapter,test_name=args.test_name,surface_value=args.surface_value,
                                   trial_num=args.trial,samples=args.samples,settle_ms=args.settle_ms,timeout_ms=int(args.max_seconds*1000)))]
    except (OSError, ValueError, TypeError, OverflowError) as exc: p.error(str(exc))
    if not rows: p.error('Empty plan')
    port=args.port or cfg.get('port')
    if not args.simulate and (not isinstance(port, str) or not port.strip()):
        p.error('Choose --port (see --list-ports), or set config port')
    session=args.session or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6]
    if not all(c.isascii() and (c.isalnum() or c in '_-') for c in session): p.error('Invalid session name')
    if args.simulate: session='SIMULATED_'+session
    folder=args.output_dir/session
    try: folder.mkdir(parents=True,exist_ok=False)
    except OSError as exc: p.error(str(exc))
    (folder/'session.json').write_text(json.dumps(dict(cfg,team_name=team,middleware_team_applied=False,simulated=args.simulate,plan=rows),indent=2,ensure_ascii=False))
    device=None
    try:
        device=SimulatedSerial() if args.simulate else serial.Serial(port,args.baudrate,timeout=0.25,write_timeout=2)
        with (folder/'serial.log').open('x',encoding='utf-8') as log:
            conn=Connection(device,log)
            # STATUS can be lost during reset; probe until boot completes.
            end=time.monotonic()+15
            while True:
                try: conn.command('STATUS','#READY,1,',2); break
                except TimeoutError:
                    if time.monotonic()>end: raise
            conn.command('MODE LAB','#ACK,STOP')
            conn.command('TEAM '+team,'#ACK,TEAM')
            for i,row in enumerate(rows,1):
                print(f'[{i}/{len(rows)}] {row}')
                if not args.yes:
                    input('Place robot, release hands; Enter to arm (Ctrl+C stops). ')
                if args.button: print('Press and release the StampC3 button within 120 s.')
                if args.simulate: device.condition=row['surface_value']
                path=capture(conn,row,folder,session,args.button)
                print('Saved:',path)
            conn.command('STOP','#ACK,STOP')
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'STOPPED: {exc or type(exc).__name__}. Retain incomplete data in {folder}')
        if device:
            try: device.write(b'STOP\n')
            except Exception: pass
        return 1
    finally:
        if device: device.close()

if __name__=='__main__': raise SystemExit(main())
