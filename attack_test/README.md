# penetration test scripts（按嚴重度排序）

所有腳本皆預設目標 `http://127.0.0.1:5000`，可用環境變數覆寫：

- `BASE_URL`
- `ROOT_USERNAME` / `ROOT_PASSWORD`（預設 `root/root`）
- `MANAGER_USERNAME` / `MANAGER_PASSWORD`（預設 `s92137/Manager@1234`）

建議執行順序（由高到低）：

1. `01_critical_xff_auth_lock_bypass_check.sh`
   - 測試內容：測試 `X-Forwarded-For` 是否可繞過 `/api/login`、`/api/register` 的封鎖/節流
   - 對應風險：Critical（可放大暴力破解）

2. `02_high_malformed_login_inputs.sh`
   - 測試內容：多種 malformed 輸入下 `/api/login` 的回應與 `fail_log` 可見變化
   - 對應風險：High（邊界輸入可造成防護失效）

3. `03_medium_admin_rbac_matrix.sh`
   - 測試內容：一般用戶、管理者、super admin 在管理 API 的權限邊界（包含 promote/demote）
   - 對應風險：Medium

4. `04_low_hidden_endpoint_scan.sh`
   - 測試內容：常見可疑端點/敏感檔案暴露盤點
   - 對應風險：Low

5. `05_low_boundary_security_check.sh`
   - 測試內容：原始邊界整合腳本（CSRF、登入註冊、登出、路由列舉）
   - 對應風險：整體邊界回歸

執行方式：

- 單一腳本：`bash attack_test/<腳本名稱>.sh`
- 全部腳本：`for f in attack_test/0*_*\\.sh; do bash "$f"; done`

執行前先確認 app 正常啟動且為測試環境，避免對正式環境誤打擊。
