# HLK Viewer

**HLK Viewer 1.2.7** 是 Windows HLK（Hardware Lab Kit）測試結果的離線檢視工具，有桌面 GUI（tkinter）和本機 Web 介面兩種用法。

它主要解決一件事：**不用開 HLK Studio／HLK Manager，也能看懂 `.hlkx` 結果檔。** 直接列出每個測試項的 PASS／FAIL，把 `Te.wtl` 轉成和 HLK Manager 一樣的「Complete Report」`.htm`，也能把結果清單匯出成 Excel。

> 它是 [Dev-Toolbox](https://github.com/tpe28601/Dev-Toolbox) 的工具之一，可以從 Hub 啟動並嵌入顯示，也可以單獨使用。

## 功能

| 功能 | 說明 |
|---|---|
| **結果清單** | 開啟 `.hlk`／`.hlkx`，列出所有測試項：PASS 綠底、FAIL 紅底，可篩選狀態、搜尋、排序，可切換是否顯示未執行的項目。 |
| **Log 預覽與轉檔** | 點測試項看它的 Log 清單。`Te.wtl` 轉成 HLK Manager 風格的 Complete Report（Report Summary、Test Results、機器／OS 資訊、完整 Test Log，錯誤紅字），可線上預覽或匯出 `.htm`。 |
| **批次匯出** | 勾選多個測試項，一次匯出 `Te.wtl`（`.htm`）或所有類型的 Log，附 `index.html` 索引頁。 |
| **Excel 報表** | 把目前篩選／排序後的結果清單匯出成 `.xlsx`：統計列、PASS／FAIL 填色、凍結窗格、自動篩選。不需要安裝 Excel 套件。 |
| **`.hlkp` 專案檔**（Web） | HLK Studio 專案檔：執行紀錄、錯誤清單（含來源與機器），以及「Log 串流」分頁可預覽 Controller 收到的原始 log。 |
| **單一 `.wtl`** | 不在封裝裡的 `.wtl` 也能直接開：Web 進入單檔預覽並可下載 `.htm`，GUI 直接轉成單頁 `.htm`。 |

### 安全原則

- **只讀取結果檔**，不修改 `.hlkx`／`.hlkp`／`.wtl` 本身。轉出的檔案寫到你選的資料夾或工具的資料夾，同名檔自動加 `(2)`、`-1` 等序號，不會覆蓋。
- Web 版只綁定 `127.0.0.1`，並檢查 `Host`、`Origin` 與 `X-Toolbox-Request` 標頭，其他網站的網頁無法操作它。
- 拖曳上傳的暫存檔在服務啟動和關閉時自動清除。

## 需求

- Windows 10／11
- Python 3（只用標準函式庫，不需要 `pip install`）
- Windows PowerShell 5.1 或 PowerShell 7+（啟動腳本用）
- 不需要安裝 HLK Studio

找 Python 的順序：`%DEVTOOLBOX_PYTHON%` → 工具資料夾下的 `.venv` → `py`／`pyw` 啟動器 → `PATH` 上的 `python`（會略過 Microsoft Store 的假捷徑）。

## 快速開始

```bat
git clone https://github.com/tpe28601/hlk-viewer.git
cd hlk-viewer
```

| 想做的事 | 執行 |
|---|---|
| 開 Web 介面 | `powershell -File HLK-Web.ps1`，再用瀏覽器開視窗上印的網址（預設 `http://127.0.0.1:8780`）；要自動開瀏覽器就用 `py hlk_web.py --open-browser` |
| 開桌面 GUI | `powershell -File Launch-HLK.ps1`（或直接雙擊 `hlk_viewer.pyw`） |
| 從 Dev-Toolbox Hub 用 | Hub 側欄點「HLK Viewer」→「啟動這個工具」，Web 介面直接嵌在 Hub 裡 |
| 不開視窗批次匯出 | 見下方〈命令列〉 |

第一次使用，建議先用 `tests\make_fixture.py` 產生的樣本試一次（見〈測試樣本〉）。

## Web 介面

- 開檔方式：輸入路徑、按「瀏覽…」選檔，或把檔案直接拖進視窗。支援 `.hlk`、`.hlkx`、`.hlkp`、`.wtl`。
- 開啟 `.hlkx` 後：摘要、狀態篩選、搜尋、排序（含結束時間欄）→ 點測試項看 Log 清單 → 線上預覽或下載單筆 `.htm` → 勾選多項批次匯出。
- 「所有類型 Log 匯出…」：跨測試項逐筆勾選全部 Log（含非 `Te.wtl`），非文字 Log 原樣複製，一次最多 2000 筆。
- `.hlkp`：逐項結果與 Log 存在 HLK Controller 端，所以只顯示專案資訊、執行紀錄、錯誤和 Log 串流，沒有逐項 Log 清單。
- 載入或匯出時，右下角會顯示進度通知，失敗時保留 12 秒。

## Web 伺服器參數與安全

```powershell
.\HLK-Web.ps1 [-Port 8780] [-DataDir <路徑>] [-ParentPid <pid>] [-HubOrigin <url>]
# 或直接呼叫 Python
py hlk_web.py [--port 8780] [--open-browser] [--data-dir <路徑>] [--parent-pid <pid>] [--hub-origin <url>]
```

| 參數（PowerShell／Python） | 說明 |
|---|---|
| `-Port`／`--port` | 指定 port；有指定時只試這一個。沒指定時從 8780 往上找可用的 port |
| `--open-browser` | 啟動後自動開瀏覽器（只有直接呼叫 Python 時可用） |
| `-DataDir`／`--data-dir` | 資料夾位置（見〈資料存放位置〉） |
| `-ParentPid`／`--parent-pid` | 父行程（例如 Dev-Toolbox Hub）結束時，自動關閉 |
| `-HubOrigin`／`--hub-origin` | Hub 的實際網址，允許它嵌入本頁 |

啟動成功時，stdout 第一行會印出 `READY http://127.0.0.1:<port>`。

安全設計：

- 只綁定 `127.0.0.1`，不對外開放。
- 檢查 `Host`、`Origin` 與 `X-Toolbox-Request` 標頭，其他網站的網頁無法替你開檔或匯出。
- Log 預覽頁使用嚴格的 CSP（不執行任何腳本），結果檔裡的內容不會在瀏覽器裡執行。
- 上傳只接受 `.hlk`／`.hlkx`／`.hlkp`／`.wtl`，檔名會先清理；Windows 保留名稱（`CON`、`NUL`…）自動加前綴。
- 同一時間只會有一個載入或匯出工作，重複送出會回 `409 BUSY`。

## 桌面 GUI

- 雙擊測試項（或選取後按 Enter）→ 匯出視窗已勾好該項的 `Te.wtl` → 「轉換成 .htm 並匯出…」→ 選資料夾。
- 「Log」功能表：批次多選（全選、只選 FAIL、只選 PASS），或「選擇所有類型 Log 匯出…」。
- 「Log → 獨立 .wtl 轉單頁 .htm…」：轉單一 `.wtl`。把 `.hlkx` 或 `.wtl` 拖到桌面捷徑上也可以。
- 「報表 → 匯出側項結果 Excel…」：依目前的篩選條件產生 `.xlsx`，例如先篩出 FAIL 再匯出，就是 FAIL 清單。
- 第一次開某個結果檔時，會把封裝內的測試資料庫解到暫存資料夾（可能上百 MB），之後同一個檔案會很快開啟。

## 命令列

```powershell
py hlk_viewer.pyw --cli-export-all       "result.hlkx" "C:\out"   # 所有測試項的 Te.wtl → .htm
py hlk_viewer.pyw --cli-export-all-logs  "result.hlkx" "C:\out"   # 所有類型的 Log
```

也可以透過 `Launch-HLK.ps1` 傳入同樣的參數。

## 資料存放位置

```
%LOCALAPPDATA%\DevToolbox\hlk-viewer\
├─ exports\<時間>\    Web 版匯出的 .htm（可在畫面上改位置）
├─ reports\<日期>\    Web 版匯出的 Excel 報表
└─ uploads\           拖曳上傳的暫存檔（自動清除）
%TEMP%\HLK_Viewer_Cache\   解出的測試資料庫快取
```

位置的優先順序：`-DataDir`／`--data-dir`，其次是 `%DEVTOOLBOX_DATA%\hlk-viewer`，最後才是上面的預設位置。

## 已知限制

- `.hlkp` 只有 Web 版支援，而且沒有逐項 Log（Log 在 HLK Controller 上）。
- 單獨開的 `.wtl` 沒有 test config 的脈絡，Report Summary 只會列出 WTL 本身的資訊。
- 狀態碼對應：0＝未執行、1＝PASS、2＝FAIL（已和封裝內的 TestRollup 交叉驗證）。
- Web 版單一 `.wtl` 預覽會整份讀進記憶體，非常大的檔案（超過 512 MB）請改用 GUI 轉檔。

## 疑難排解

| 狀況 | 處理 |
|---|---|
| 啟動時說找不到 Python | 安裝 Python 3，或設定 `%DEVTOOLBOX_PYTHON%` 指向 `python.exe`；Microsoft Store 的 `python` 假捷徑不算 |
| 瀏覽器連不上 | 確認啟動視窗還開著，並看視窗上印的實際 port |
| 第一次開檔很慢 | 正常現象：要先把封裝內的資料庫解到 `%TEMP%\HLK_Viewer_Cache`，之後同一個檔案會很快 |
| 拖曳的檔案找不到原始路徑 | 瀏覽器拿不到完整路徑，所以是上傳一份複本到 `uploads\`；要匯出到原本的資料夾，請改用「瀏覽…」或輸入路徑 |
| `.hlkp` 沒有逐項 Log | 專案檔的 Log 存在 HLK Controller 上，請改用從 HLK Studio 匯出的 `.hlkx` |
| 介面更新後沒變 | 按 `Ctrl+F5` 強制重新整理 |

## 專案結構

```
hlk_viewer.pyw        桌面 GUI（tkinter）與命令列
hlk_web.py            Web 伺服器（標準函式庫，只綁 127.0.0.1）
hlk_core.py           .hlk/.hlkx/.hlkp 解析（ZIP + SQLite + telemetry）
hlk_wtl.py            .wtl → HLK 風格 .htm 轉換與匯出
hlk_xlsx.py           結果清單 → .xlsx（標準函式庫）
HLK-Web.ps1           Web 啟動入口（找 Python 後轉呼 hlk_web.py）
Launch-HLK.ps1        GUI／命令列啟動入口
cli-kit.ps1           CLI 樣式（Dev-Toolbox 同步的複本）
ui\                   Web 前端（ui-kit 3.x）
tests\make_fixture.py 產生最小測試樣本（.hlkx／.hlkp／.wtl）
tool.json             Dev-Toolbox 工具描述檔
```

## 測試樣本

`tests\make_fixture.py` 會產生三個最小的樣本檔，涵蓋 PASS／FAIL／未執行、Run Test 與 Deployment 雙 `Te.wtl`、二進位 Log 等邊界情況，機器名稱都是假名（`PLATA-H-01`、`PLATB-H-02`）：

```powershell
py -3 tests\make_fixture.py
```

| 檔案 | 內容 |
|---|---|
| `tests\sample.hlkx` | 結果封裝（4 個測試項、8 個 Log） |
| `tests\sample.hlkp` | 專案檔（執行紀錄、錯誤、Log 串流 chunk） |
| `tests\sample.wtl` | 單一 `.wtl`（單檔預覽與轉檔用） |

產出的 `tests\sample.*` 已被 `.gitignore` 排除，不會進版控。

## 版本紀錄

見 [CHANGELOG.md](CHANGELOG.md)。

## 授權

[MIT](LICENSE)。介面圖標來自 [Lucide](https://lucide.dev)（ISC 授權）。
