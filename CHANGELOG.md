# Changelog — HLK Viewer

## v1.2.7 (2026-11-13)
- README 由 `README.txt`（版本紀錄式）改寫為 `README.md`：功能表、需求、快速開始、Web／GUI／命令列用法、
  資料位置、已知限制與專案結構，格式比照 Dev-Toolbox 其他工具。
- 測試樣本改用假名機器（PLATA-H-01／PLATB-H-02）；產出的 `tests/sample.*` 一律 git-ignore。
- **直接開單一 .wtl 檔**（不在封裝內，GUI 與 Web 都支援）：
  - Web：開檔／瀏覽／拖曳上傳收 `.wtl` → 進入單檔模式（新卡片＋自動開預覽），
    線上預覽 Complete Test Log 單頁，可「下載 .htm」（`GET /api/wtl?dl=1`）。
  - GUI：「檔案→開啟」與「Log→獨立 .wtl 轉單頁 .htm…」選 .wtl 後選資料夾即轉
    「主檔名.htm」（重複自動加 (2)、(3)…）；把 .wtl 拖到桌面捷徑同此流程。
  - 共用 `hlk_wtl.convert_wtl_file()`，與封裝內 log 同一條轉換管線。
- **.hlkp「Log 串流」chunk 預覽新增「下載 .htm」**（`/api/pchunk?c=&dl=htm` 回轉換後
  的 HTML；原「下載原始檔」＝ `.wtl`/`.xml` 原始位元組，兩者並列）。
- 測試 fixture：`make_fixture.py` 另產 `sample.hlkp`（telemetry＋streamdata chunk）
  與獨立 `sample.wtl`。
- `tool.json` version 1.2.7。

## v1.2.6 (2026-11-13)
- Web 版補齊 GUI 獨有功能：
  - **單筆 Log 下載 .htm**：Log 預覽彈窗新增「下載此檔（.htm）」（`GET /api/log?i=&l=&dl=1`
    回轉換後的 HTML，檔名＝側項名稱 - log 主檔名.htm，中文檔名用 RFC 5987 帶出）。
  - **Excel 側項結果報表**：匯出列新增「匯出 Excel 報表」按鈕（`POST /api/export-xlsx`，
    範圍＝目前篩選/排序後的可見側項，樣式與 GUI 相同：統計列、PASS/FAIL 填色、
    凍結窗格、autoFilter），產物存 <dataDir>\reports\<日期>（重複自動加 -1、-2…）
    並經 /report/<file> 自動下載（不影響 HTML 匯出的 /export/ 連結）。
  - **所有類型 Log 匯出（跨側項）**：匯出列新增對話框，可過濾＋逐筆勾選所有側項的
    全部 log（含非 Te.wtl），預設勾選集：全選／只選 .wtl・.html／清空，送出走
    `/api/export` all 模式（上限 2000 筆，非文字 log 原樣複製）。
  - **結束時間欄**：結果清單新增「結束時間」可排序欄位（資料原本就有，補顯示）。
- `tool.json` version 1.2.6。

## v1.2.5 (2026-11-13)
- 介面框架同步 Build Runner／Git Ref Manager：
  - 頂部列改 `tool-topbar`：工具圖示＋名稱、本機服務 port、伺服器連線狀態徽章
    （每 3 秒輪詢 `/api/health`，Hub 嵌入時跳過）、icon 式主題鈕（圖示與提示隨
    淺色／深色／跟隨系統切換重繪）。
  - `.hlkp` 的「執行紀錄／錯誤／Log 串流」三選一切換從清單工具列的 tb-seg 升級為
    頁面頂部 `tb-tabs` 分頁列（「錯誤／Log 串流」僅專案檔顯示；换開非專案檔或
    關檔時自動重置回「測試項」）。
  - 檔案載入狀態徽章（尚未載入／載入中／已載入）移到「HLK 結果檔」卡列頭；
    頂部列原版本字串移除，版本改顯示於視窗標題。
- `tool.json` version 1.2.5。

## v1.2.4 (2026-11-11)
- `.wtl → .htm` 時間修復（GUI／Web 共用 `hlk_wtl.py`，Web 線上預覽與匯出一併生效）：
  - 條目引用「其後才出現」的 RTI 時不再遺失時間（改為先預掃全部 RTI 建對照表）。
  - PFRollup 只有 `<rti>` 引用、沒有 `WexTraceInfo`，改用 RTI `BaseTime` 顯示時間。
- Report Summary / Test Results 貼齊 HLK Manager：Sum 列在上、各 PFRollup 以時間戳
  為 Description 列於「TimeStamp」子表頭下，新增 Blocked / Skipped / Pass Rate 欄。
- GUI 新增「匯出側項結果 Excel」（`hlk_xlsx.py`，純標準函式庫產 .xlsx）：依目前
  篩選/搜尋/排序條件匯出側項清單，PASS 綠底 / FAIL 紅底、凍結窗格、autoFilter，
  完成後可直接以 Excel 開啟；檔案被 Excel 佔用時給明確提示。
- `tool.json` version 1.2.4。

## v1.2.3 (2026-11-11)
- 單項 Log 清單按「← 回 Log 清單」不再捲回頂端：進入預覽前記住捲動位置、返回時還原；
  改開另一個側項則從頭開始。

## v1.2.2 (2026-11-11)
- 錯誤清單可追蹤來源：`.hlkp` 的「錯誤」表新增「來源／機器」欄（Error telemetry 沒有
  任務欄位，來源由訊息首行前綴解析：Machine／MachinePool／Project／Test／LogoManager；
  機器由 MachineId→TargetName 對應表或訊息內文取得；`Preparing to run test: X` 的錯誤
  一併列出測試任務）。搜尋現在也比對來源／機器／任務；訊息彈窗上方顯示
  「來源・機器・工作」一列。
- 彈窗放大、免左右捲動：彈窗寬度 860→1180px、高度上限 92vh；單項 Log 清單改為固定
  欄位寬度＋超長截斷（滑鼠停留看全名），「預覽／下載」按鈕永遠可見，底部橫向捲軸移除；
  Log 預覽 iframe 加大（68vh，小螢幕自動縮，不產生二層捲動）。
- `tool.json` version 1.2.2。GUI 不變。

## v1.2.1 (2026-11-11)
- `.hlkp` 新增「Log 串流」分頁：解析 streamdata SQLite 的 Chunk 表（Controller 上傳的
  原始 log 流），列出每條 chunk 的類型／來源程式／機器／時間／大小；WTL chunk（同
  Te.wtl 格式）即時轉 Complete Report HTML 預覽，Comm 訊息（含 Controller 端 Log 分享
  路徑）與其他 chunk 以純文字預覽，皆可下載原始檔。新增
  `GET /api/chunks`、`GET /api/pchunk?c=&dl=`；清單首次切分頁才解析（lazy），
  解析結果快取於 `%TEMP%\HLK_Viewer_Cache`。
- 拖曳上傳暫存檔自動清除：服務啟動、優雅關閉（`POST /api/shutdown`）、父工程序消失
  或 Ctrl+C 退出時清 `<dataDir>\uploads\`（使用中的檔案靜默跳過）。
- 右下角通知卡：開檔／上傳顯示載入中（轉圈），完成變綠自動消失，失敗變紅保留 12 秒
  可手動關閉（Esc 不受影響）。
- `tool.json` version 1.2.1。GUI 不變。

## v1.2.0 (2026-11-11)
- 支援 `.hlkp`（HLK Studio 專案檔，僅 Web）：`hlk_core.HlkProject` 解析
  PackageInfo（專案/Target/ProductInstance 狀態/Features/TestRollup）與
  `hck/telemetry/*.txt` 遙測 —「執行紀錄」表（TestCompletedDataPoint：時間/
  狀態/測試項/機器/耗時/Bugcheck）＋「錯誤」表（Error：點列看完整訊息）。
  .hlkp 的逐項結果與 Log 存在 HLK Controller 端，`/api/log`、`/api/export`
  對 project 模式回 409；副檔名誤用（結果檔改名 .hlkp 等）給明確錯誤。
- 新增「瀏覽…」檔案選取視窗：`GET /api/browse`（磁碟機清單＋目錄瀏覽，
  只列 .hlk/.hlkx/.hlkp），點資料夾進入、點檔案直接開啟。
- 新增拖曳檔案分析：拖入視窗即上傳（瀏覽器拿不到完整路徑，改傳檔案內容），
  XHR 上傳進度 → 存於 `<dataDir>\uploads\`（同名自動去重）→ 自動開啟；
  `POST /api/upload` 副檔名白名單＋檔名 sanitize，上限 4GB。
- 換檔／關檔改為延後釋放舊封裝（避免進行中的載入／預覽請求失敗）；
  上傳暫存檔改 `mkstemp`、中斷清理、保留裝置名（CON/NUL…）加前綴。
- `tool.json` version 1.2.0。GUI 不變（不支援 .hlkp）。

## v1.1.0 (2026-11-11)
- 新增 Web 介面（`hlk_web.py` + `ui/`，Dev-Toolbox TOOL-SPEC 5）：純標準函式庫
  ThreadingHTTPServer，僅綁定 127.0.0.1，預設 port 8780；Hub 可啟動嵌入。
  - 開啟／關閉 .hlkx（背景載入＋進度狀態）
  - 摘要 chips、狀態篩選、搜尋、只顯示已執行、欄位排序
  - 點側項看 Log 清單；單筆 Log 線上預覽（Te.wtl 即時轉 Complete Report HTML）
  - 勾選批次匯出 Te.wtl（.htm）或單項全部 Log；匯出進度與結果、直接開索引頁
  - 載入／匯出互斥（409 BUSY）；Host/Origin/X-Toolbox-Request 檢查與安全標頭
- 新增 `HLK-Web.ps1` web 啟動入口（runtime.kind 維持 powershell，轉呼 python）。
- `tool.json`：version 1.1.0、web 段、dataDir、requires python、uiKit 3.0.0。
- `hlk_core.py`：PackageInfo.xml 支援自訂 XML 命名空間（Project/TestRollup 節點比對）。
- 新增 `tests/make_fixture.py`：鑄最小 .hlkx 測試樣本（含 Run Test/Deployment
  雙 Te.wtl、二進位 log、非 SQLite decoy 等邊界情境）。
- GUI（hlk_viewer.pyw）與 CLI 用法不變。

## v1.0.0 (2026-11-09)
- 初始版本：tkinter GUI 檢視 .hlk/.hlkx 側項與 log；Te.wtl → HLK 風格 .htm
  匯出（含 index.html）；CLI `--cli-export-all` / `--cli-export-all-logs`；
  Dev-Toolbox tool.json + Launch-HLK.ps1。
