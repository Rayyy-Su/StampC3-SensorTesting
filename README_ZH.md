# Sensor testing：操作步驟

## 1. 第一次設定

   終端機進入本套件的 SensorData，執行：

```sh
cd /Users/ray/Documents/UoBRobotics/RobSystems/StampC3/StampC3-SensorTesting/SensorData
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python RecordSensorData.py --list-ports
```

7. 編輯 `session_config.json`：只填 team_name、port、robot_id；每台機器人另填設定、另開 session。
8. 編輯 plans：填紙上實際灰階值、條寬、位置；255 白、0 黑。預設 off-white = 200；不要只改標籤卻未更換實體色塊。
9. 每次開新終端機，先 `cd` 到 SensorData，再 `source .venv/bin/activate`。

## 2. 每次收資料

1. 依畫面擺放，按 Enter，移開手；等待 2 秒後記錄。
3. 看到 Saved 才移動；下一個 trial 先抬起、重新放置。
4. 記下 session 資料夾名稱；下列 `SESSION_*` 換成實際名稱。
5. Ctrl+C 中止；保留 partial 檔，另開 session 重測。
6. 所有 output 使用新名稱；不覆蓋舊結果。需要按鈕啟動時，在記錄命令後加 `--button`，按 Enter 後再按放機器人按鈕。

## 3. Chapter 01：讀值與通道

1. 依提示測白色、黑色，每次 200 份快照。

```sh
python RecordSensorData.py --plan plans/ch01.csv
python AnalyzeSensorData.py --inputs records/SESSION_01 --chapter 1 --output results/ch01_run1
```

2. 查看 time_traces.png、quality_report.csv。
3. 用窄黑片依序對準 DN1–DN5，其他感測器下方保持白色；每次 100 份。

```sh
python RecordSensorData.py --plan plans/ch01_mapping.csv
python AnalyzeSensorData.py --inputs records/SESSION_MAPPING --chapter 1 --test-name mapping_DN1 mapping_DN2 mapping_DN3 mapping_DN4 mapping_DN5 --output results/mapping_run1
```

4. 對照 placement_summary.csv，記下 DN 與 reading 索引。

## 4. Chapter 02：Offset

1. 準備大白區與實際灰階 200 的 off-white 區；若不同，先改 plans/ch02.csv。
2. 白色、off-white 各三次重新放置，每次 200 份。

```sh
python RecordSensorData.py --plan plans/ch02.csv
python AnalyzeSensorData.py --inputs records/SESSION_02 --chapter 2 --output results/ch02_run1
```

3. 查看白色箱形圖、baseline.csv、offwhite_check.csv；保留五個獨立基準。

## 5. Chapter 03：Saturation

1. 依計畫準備 255、200、150、100、50、0 色塊；必要時換成實際可用值。
2. 亮到暗、暗到亮各一輪，每次重新放置、200 份。

```sh
python RecordSensorData.py --plan plans/ch03.csv
python AnalyzeSensorData.py --inputs records/SESSION_03 --chapter 3 --output results/ch03_run1
```

3. 看 response_summary.csv、per_trial_response.csv、median_response.png；確認平台是否跨條件、跨試次重現。
4. 暗端仍增加時，準備實際的 40、30、20、10 色塊再補測；沒有平台就記錄未確認飽和。

```sh
python RecordSensorData.py --plan plans/ch03_dark_detail.csv
python AnalyzeSensorData.py --inputs records/SESSION_03_DETAIL --chapter 3 --output results/ch03_detail_run1
```

5. 在 calibration.json 逐通道填可用灰階範圍；不要將單點最大值當飽和。

## 6. Chapter 04：Gain

1. 修改 plans/ch04.csv：選可用範圍內至少四個 fit 條件和至少一個 held_out 條件；整個灰階條件保持相同 split。
2. 保留計畫開頭三次白色參考；各灰階三次重新放置，每次 200 份。

```sh
python RecordSensorData.py --plan plans/ch04.csv
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 2 --output results/ch04_baseline_run1
```

3. 在 calibration.json 逐通道填 usable_fill_min、usable_fill_max、linear_fill_min、linear_fill_max。

```sh
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 4 --baseline results/ch04_baseline_run1/baseline.csv --calibration calibration.json --output results/ch04_run1
```

4. 看 model_parameters.csv、response_and_residuals.png、model_scores.csv；調整區間時使用新 output。用來選模型後，另留新條件作最終測試。

## 7. Chapter 05：Non-linearity

1. 優先沿用 Chapter 04 資料與 held_out 條件。
2. 在 calibration.json 填各通道 upper_reference_us：使用同條件下的大黑區代表值或已確認的平台值；upper_reference_kind 分別填 black_reference 或 plateau。
3. 若缺少上參考，先將機器人放在同紙材的大黑區收資料，從 placement_summary.csv 取各通道代表值。

```sh
python RecordSensorData.py --chapter 1 --test-name readingTest --surface-value 0 --trial 1 --samples 200
python AnalyzeSensorData.py --inputs records/SESSION_BLACK --chapter 1 --output results/ch05_black_reference_run1
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 5 --baseline results/ch04_baseline_run1/baseline.csv --calibration calibration.json --output results/ch05_run1
```

4. 看 model_scores.csv、shared_gamma_scores.csv、殘差圖，分別比較 fit／held_out。
5. 需要補測時，先修改 plans/ch05.csv 的灰階與 split，再執行；新批次使用自己的白色參考。

```sh
python RecordSensorData.py --plan plans/ch05.csv
python AnalyzeSensorData.py --inputs records/SESSION_05 --chapter 2 --output results/ch05_baseline_run1
python AnalyzeSensorData.py --inputs records/SESSION_05 --chapter 5 --baseline results/ch05_baseline_run1/baseline.csv --calibration calibration.json --output results/ch05_extra_run1
```

## 8. Chapter 06：Noise

1. plans/ch06.csv 選至少兩個未飽和操作點；預設 200、100，需按 Chapter 03 結果修改。
2. 每點三次重新放置，每次 1000 份；trial 3 保留，不用於擬合。

```sh
python RecordSensorData.py --plan plans/ch06.csv
python AnalyzeSensorData.py --inputs records/SESSION_06 --chapter 6 --holdout-trial 3 --output results/ch06_run1
```

3. 看時序、noise_trial_summary.csv、time_correlation.csv、held_out_noise_checks.csv；分開記錄短期波動與重放偏移。
4. 若 Chapter 04 已有足夠靜止資料，可改用下列命令；先排除移動或飽和條件。

```sh
python AnalyzeSensorData.py --inputs records/SESSION_04 --chapter 6 --test-name responseTest --holdout-trial 3 --output results/ch06_reuse_run1
```

## 9. Chapter 07：Spatial footprint

1. plans/ch07.csv 預設目標索引 2、條寬 1／3／8 mm、位置 −10 到 +10 mm、步距 1 mm；先換成實際條寬與可量測位置。
2. 先測同紙材的大白區、大黑區，各三次重新放置。
3. 以目標感測器對準條帶；條帶中心為 0。逐位置停穩後收 50 份；移動中不記錄。
4. 正向、反向使用相同原點；反向前重新對準。其餘感測器資料只保留，不當作已對準。

```sh
python RecordSensorData.py --plan plans/ch07.csv
python AnalyzeSensorData.py --inputs records/SESSION_07 --chapter 7 --output results/ch07_run1
```

5. 看 spatial_profiles.csv、strip_peaks.csv、footprint_sensor2.png；掃描兩端未回白色時擴大範圍。
6. 換感測器時另建計畫；以下數字先改成實際值。

```sh
python MakeExperimentPlan.py --chapter 7 --widths 1 3 8 --start -10 --stop 10 --step 1 --sensor 0 --output plans/ch07_sensor0.csv
python RecordSensorData.py --plan plans/ch07_sensor0.csv
python AnalyzeSensorData.py --inputs records/SESSION_07_SENSOR0 --chapter 7 --output results/ch07_sensor0_run1
```

## 10. 檢查與結束

```sh
python -m unittest discover -s tests -v
```

1. 將 records、results、JSON 設定與實驗筆記一起保存。
2. 結束記錄程式，重新上傳組員原本的 StampC3 sketch。
