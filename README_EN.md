# Sensor testing: steps

## 1. First setup

   Open a terminal in this kit's `SensorData` folder. Run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python RecordSensorData.py --list-ports
```

7. Fill in `session_config.json`: team_name, port, and robot_id only. Use a new session for each robot.
8. Check the CSV files in plans. Use the actual printed tones, strip widths, and positions. Use 255 for white and 0 for black. The off-white plan uses 200; change the paper or plan to match.
9. In each new terminal, open SensorData and run `source .venv/bin/activate`.

## 2. Each capture

1. Place the robot as shown on screen. Press Enter and move your hands away. Capture starts after 2 seconds.
3. Wait for Saved before moving. Lift and replace the robot for each new trial.
4. Write down the session folder. Replace `SESSION_*` below with the real name.
5. Press Ctrl+C to stop. Keep partial files and start a new session to try again.
6. Use a new output folder each time. To start with the robot button, add `--button`; press Enter, then press and release the button.

## 3. Chapter 01: readings and sensor order

1. Measure white and black. Take 200 snapshots at each spot.

```sh
python RecordSensorData.py --plan plans/ch01.csv
python AnalyzeSensorData.py --inputs records/SESSION_01 --chapter 1 --output results/ch01_run1
```

2. Check time_traces.png and quality_report.csv.
3. Place a thin black strip under DN1, then DN2 through DN5. Keep the other sensors over white. Take 100 snapshots each.

```sh
python RecordSensorData.py --plan plans/ch01_mapping.csv
python AnalyzeSensorData.py --inputs records/SESSION_MAPPING --chapter 1 --test-name mapping_DN1 mapping_DN2 mapping_DN3 mapping_DN4 mapping_DN5 --output results/mapping_run1
```

4. Use placement_summary.csv to write down each DN-to-array match.

## 4. Chapter 02: offset

1. Use large white and off-white patches. The plan uses off-white tone 200; edit plans/ch02.csv if needed.
2. Lift and replace the robot three times on each patch. Take 200 snapshots each time.

```sh
python RecordSensorData.py --plan plans/ch02.csv
python AnalyzeSensorData.py --inputs records/SESSION_02 --chapter 2 --output results/ch02_run1
```

3. Check the white boxplots, baseline.csv, and offwhite_check.csv. Keep one baseline for each sensor.

## 5. Chapter 03: saturation

1. Prepare tones 255, 200, 150, 100, 50, and 0, or edit the plan to match your paper.
2. Go from light to dark, then dark to light. Replace the robot at each spot. Take 200 snapshots each time.

```sh
python RecordSensorData.py --plan plans/ch03.csv
python AnalyzeSensorData.py --inputs records/SESSION_03 --chapter 3 --output results/ch03_run1
```

3. Check response_summary.csv, per_trial_response.csv, and median_response.png. Look for a flat response across nearby tones in both passes.
4. If the dark response still rises, prepare actual tones 40, 30, 20, and 10 and run the extra plan. If no plateau is found, record that result.

```sh
python RecordSensorData.py --plan plans/ch03_dark_detail.csv
python AnalyzeSensorData.py --inputs records/SESSION_03_DETAIL --chapter 3 --output results/ch03_detail_run1
```

5. Fill in the supported usable range for each sensor in calibration.json. Do not use one peak reading as a saturation level.

## 6. Chapter 04: gain

1. Edit plans/ch04.csv. Pick at least four usable fit tones and at least one held_out tone. Keep each whole tone in the same split.
2. Keep the three white trials at the start. Replace the robot three times per tone. Take 200 snapshots each time.

```sh
python RecordSensorData.py --plan plans/ch04.csv
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 2 --output results/ch04_baseline_run1
```

3. In calibration.json, fill in usable_fill_min, usable_fill_max, linear_fill_min, and linear_fill_max for each sensor.

```sh
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 4 --baseline results/ch04_baseline_run1/baseline.csv --calibration calibration.json --output results/ch04_run1
```

4. Check model_parameters.csv, response_and_residuals.png, and model_scores.csv. Use a new output folder when changing the range. Keep new final test tones if earlier held-out tones helped you pick the model.

## 7. Chapter 05: non-linearity

1. Reuse Chapter 04 data and its held-out tones first.
2. Set upper_reference_us for each sensor in calibration.json. Use a measured large black patch or a confirmed plateau. Set upper_reference_kind to black_reference or plateau.
3. If needed, measure a large black patch on the same paper and use its per-sensor values from placement_summary.csv.

```sh
python RecordSensorData.py --chapter 1 --test-name readingTest --surface-value 0 --trial 1 --samples 200
python AnalyzeSensorData.py --inputs records/SESSION_BLACK --chapter 1 --output results/ch05_black_reference_run1
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 5 --baseline results/ch04_baseline_run1/baseline.csv --calibration calibration.json --output results/ch05_run1
```

4. Check model_scores.csv, shared_gamma_scores.csv, and the residual plots. Compare fit and held_out results separately.
5. If more data is needed, edit plans/ch05.csv first. Use the new batch's white baseline.

```sh
python RecordSensorData.py --plan plans/ch05.csv
python AnalyzeSensorData.py --inputs records/SESSION_05 --chapter 2 --output results/ch05_baseline_run1
python AnalyzeSensorData.py --inputs records/SESSION_05 --chapter 5 --baseline results/ch05_baseline_run1/baseline.csv --calibration calibration.json --output results/ch05_extra_run1
```

## 8. Chapter 06: noise

1. Pick at least two non-saturated tones in plans/ch06.csv. It starts with 200 and 100; change them using Chapter 03 results.
2. Use three new placements per tone and 1000 snapshots each. Keep trial 3 for testing only.

```sh
python RecordSensorData.py --plan plans/ch06.csv
python AnalyzeSensorData.py --inputs records/SESSION_06 --chapter 6 --holdout-trial 3 --output results/ch06_run1
```

3. Check time plots, noise_trial_summary.csv, time_correlation.csv, and held_out_noise_checks.csv. Keep short-term spread and placement shifts separate.
4. Reuse Chapter 04 if it already has enough still, non-saturated data. Leave out moving or saturated records first.

```sh
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 6 --test-name responseTest --holdout-trial 3 --output results/ch06_reuse_run1
```

## 9. Chapter 07: spatial footprint

1. Check plans/ch07.csv. It starts with sensor index 2, strip widths 1/3/8 mm, positions −10 to +10 mm, and 1 mm steps. Use real measured sizes and positions.
2. Measure large white and black patches on the same paper, with three new placements each.
3. Line up the target sensor with the strip. Set the strip centre to zero. Stop at each position and take 50 snapshots. Do not record while moving.
4. Keep the same zero for both directions. Line up again before the return pass. Keep the other sensor readings, but do not treat them as aligned scans.

```sh
python RecordSensorData.py --plan plans/ch07.csv
python AnalyzeSensorData.py --inputs records/SESSION_07 --chapter 7 --output results/ch07_run1
```

5. Check spatial_profiles.csv, strip_peaks.csv, and footprint_sensor2.png. Extend the scan if either end has not reached white.
6. Make a new plan for another sensor. Change these sample sizes and positions to your real values.

```sh
python MakeExperimentPlan.py --chapter 7 --widths 1 3 8 --start -10 --stop 10 --step 1 --sensor 0 --output plans/ch07_sensor0.csv
python RecordSensorData.py --plan plans/ch07_sensor0.csv
python AnalyzeSensorData.py --inputs records/SESSION_07_SENSOR0 --chapter 7 --output results/ch07_sensor0_run1
```

## 10. Check and finish

```sh
python -m unittest discover -s tests -v
```

1. Save records, results, JSON settings, and experiment notes together.
2. Close the recorder and upload your teammate's original StampC3 sketch again.
