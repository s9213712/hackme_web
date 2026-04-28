# Agent 實作指令檔：兼顧防毒與用戶隱私的加密上傳系統

## 0. 任務目標

請在 hackme_web 專案中設計並實作「隱私分級上傳 + 防毒掃描 + 端到端加密」系統。

目標不是單純把所有檔案都加密，也不是讓 root 可以看所有檔案，而是建立一套分級策略：

1. 一般公開附件：伺服器可掃毒、可產生縮圖、可審核。
2. 私密附件：伺服器可掃毒，但盡量降低明文暴露時間。
3. 加密保險庫 / 私密雲端：端到端加密，root/admin/伺服器不可讀內容。
4. 高風險檔案：即使使用端到端加密，也要限制下載、分享、執行風險。
5. 使用者必須清楚知道不同模式的隱私與安全取捨。
6. 所有上傳、掃描、隔離、解鎖、分享、刪除都要有 audit log。

---

## 1. 核心原則

### 1.1 不要假裝「端到端加密也能完整防毒」

端到端加密後，伺服器無法看到明文，所以伺服器無法做完整內容掃描。

因此要採用分級策略：

- 需要公開顯示、縮圖、搜尋、審核的內容，不使用端到端加密。
- 需要最高隱私的內容，使用端到端加密，但伺服器只能掃 metadata / 密文特徵 / 檔案大小 / 副檔名 / 使用者行為。
- 若使用者希望雲端掃毒，必須選擇「可掃描私密上傳」模式，讓客戶端暫時授權掃描。

---

## 2. 上傳模式設計

請建立 upload_privacy_mode，至少支援以下四種模式。

### 2.1 public_attachment

用途：

- 公開文章圖片
- 公開下載附件
- 頭像
- 相簿公開圖片

特性：

- 伺服器可讀明文
- 必須防毒掃描
- 可產生縮圖
- 可做內容審核
- 可搜尋 metadata
- 不宣稱 root 不可讀

適用政策：

```text
公開附件會由伺服器處理與掃毒。請勿上傳需要端到端保密的資料。
```

---

### 2.2 private_scannable

用途：

- 私人訊息附件
- 私人相簿
- 需要一定隱私，但也希望伺服器防毒

特性：

- 上傳時可由伺服器短暫取得明文進行掃毒
- 掃描通過後，伺服器以 server-side encryption 保存
- root 理論上仍可能透過伺服器密鑰取得內容
- 不宣稱 root 不可讀
- 可提供較完整防毒能力

適用政策：

```text
此模式提供伺服器端掃毒與加密儲存，但不是端到端加密。站方高權限仍可能在合法管理流程下存取。
```

---

### 2.3 e2ee_vault

用途：

- 使用者私密雲端
- 不希望 root/admin/伺服器看到內容
- 個人敏感檔案

特性：

- 上傳前在使用者本機 / 瀏覽器加密
- 伺服器只保存密文
- 檔名、mime type、描述、標籤也要加密
- root/admin/伺服器不可解密
- 伺服器不能完整掃毒
- 忘記密碼或遺失金鑰可能無法救回
- 分享時只分享 file_key，不重新上傳明文

適用政策：

```text
端到端加密保險庫：站方無法讀取內容，也無法完整掃毒。請只下載並開啟你信任來源的檔案。遺失金鑰可能導致永久無法取回。
```

---

### 2.4 e2ee_vault_with_client_scan

用途：

- 想要 root 不可讀
- 同時希望上傳前做本機掃毒 / 檢查

特性：

- 客戶端上傳前執行本機檢查
- 可做副檔名、magic bytes、壓縮炸彈初步檢查
- 可整合瀏覽器端 WASM 掃描器或本機代理程式
- 伺服器仍無法完整掃毒
- 掃描結果由 client report 回傳，可信度低於 server scan

適用政策：

```text
此模式在本機加密前進行基本安全檢查，但站方無法驗證所有內容。安全性依賴你的裝置與本機掃描結果。
```

---

## 3. 風險分級策略

請為所有上傳檔案建立 risk_level：

- low
- medium
- high
- blocked
- unknown_encrypted

判斷來源：

1. 檔案模式
2. 副檔名
3. magic bytes
4. MIME type
5. 檔案大小
6. 壓縮層數
7. 是否可執行
8. 是否含巨集
9. 掃描結果
10. 使用者信任等級
11. 分享對象
12. 下載次數異常
13. 檢舉紀錄

---

## 4. 檔案類型政策

### 4.1 一律禁止或強限制

以下檔案預設禁止公開分享：

- .exe
- .dll
- .bat
- .cmd
- .ps1
- .scr
- .msi
- .vbs
- .js
- .jar
- .apk
- .ipa
- .reg
- .lnk

若是 e2ee_vault，可允許保存，但：

- 不允許公開分享
- 下載前強警告
- 不自動開啟
- 不提供 inline preview
- risk_level = high 或 unknown_encrypted

---

### 4.2 壓縮檔政策

壓縮檔：

- .zip
- .7z
- .rar
- .tar
- .gz

public_attachment / private_scannable：

- 必須解壓掃描
- 限制最大解壓大小
- 限制最大檔案數
- 限制最大壓縮層數
- 防止 zip bomb
- 防止 path traversal

e2ee_vault：

- 只能檢查密文大小與副檔名
- 標記 unknown_encrypted
- 下載前提示無法雲端掃描

---

### 4.3 Office 文件政策

Office 文件：

- .doc
- .docx
- .xls
- .xlsx
- .ppt
- .pptx
- .xlsm
- .docm
- .pptm

public_attachment / private_scannable：

- 掃描巨集
- 巨集文件標記 high risk
- 可選擇禁止上傳或只允許 trusted/vip

e2ee_vault：

- 無法檢查巨集
- 下載前提示

---

## 5. 資料庫設計

請依現有專案調整，但至少建立或擴充以下欄位。

### 5.1 uploaded_files

```sql
CREATE TABLE uploaded_files (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    scan_status TEXT NOT NULL,
    original_filename_encrypted TEXT,
    original_filename_plain_for_public TEXT,
    mime_type_encrypted TEXT,
    mime_type_plain_for_public TEXT,
    size_bytes INTEGER NOT NULL,
    ciphertext_sha256 TEXT,
    plaintext_sha256 TEXT,
    encryption_algorithm TEXT,
    encryption_version TEXT,
    nonce TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    deleted_at DATETIME
);
```

scan_status：

- not_required
- pending
- scanning
- clean
- infected
- failed
- skipped_e2ee
- unknown_encrypted
- quarantined

---

### 5.2 encrypted_file_keys

```sql
CREATE TABLE encrypted_file_keys (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    recipient_user_id INTEGER NOT NULL,
    encrypted_file_key TEXT NOT NULL,
    wrapped_by TEXT NOT NULL,
    key_version INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    revoked_at DATETIME
);
```

用途：

- 每個檔案一把 file_key
- file_key 在客戶端產生
- 伺服器只存加密後的 file_key
- 分享給其他使用者時，新增一筆 recipient_user_id 的 encrypted_file_key

---

### 5.3 file_scan_results

```sql
CREATE TABLE file_scan_results (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    scanner_name TEXT NOT NULL,
    scanner_version TEXT,
    scan_started_at DATETIME,
    scan_completed_at DATETIME,
    result TEXT NOT NULL,
    malware_name TEXT,
    details_json TEXT,
    created_at DATETIME NOT NULL
);
```

result：

- clean
- infected
- suspicious
- failed
- skipped
- unsupported
- encrypted_unknown

---

### 5.4 file_access_logs

```sql
CREATE TABLE file_access_logs (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    actor_user_id INTEGER,
    action TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    result TEXT NOT NULL,
    reason TEXT,
    created_at DATETIME NOT NULL
);
```

action：

- upload
- scan
- quarantine
- download
- decrypt_metadata
- share
- revoke_share
- delete
- restore
- admin_review_attempt

---

## 6. 加密設計

### 6.1 e2ee_vault 加密流程

上傳前：

1. client 產生隨機 file_key
2. client 使用 file_key 加密檔案內容
3. client 加密檔名、mime type、描述、標籤
4. client 使用 user_master_key 包裝 file_key
5. client 上傳：
   - encrypted_blob
   - encrypted_file_key
   - nonce
   - algorithm
   - encrypted_metadata

伺服器保存：

- 密文
- encrypted_file_key
- encrypted metadata
- ciphertext hash
- size
- risk_level = unknown_encrypted
- scan_status = skipped_e2ee 或 unknown_encrypted

---

### 6.2 推薦演算法

優先：

- XChaCha20-Poly1305
- 或 AES-256-GCM

密碼導出：

- Argon2id
- salt 每個使用者不同
- 不要使用單純 SHA256(password)

簽章：

- Ed25519，可作為進階功能
- 用於確認檔案分享者身份與 metadata 未被偽造

---

### 6.3 金鑰儲存原則

禁止：

- 伺服器保存明文 user_master_key
- 伺服器保存明文 file_key
- 伺服器可由資料庫直接還原 file_key

允許：

- 伺服器保存 public key
- 伺服器保存 encrypted private key
- 伺服器保存 encrypted_file_key
- 使用者本機保存 recovery key

---

## 7. 防毒掃描設計

### 7.1 public_attachment

流程：

1. 接收上傳
2. 暫存到 quarantine area
3. 掃描
4. 若 clean，移動到正式 storage
5. 若 infected，保留隔離記錄或刪除
6. 寫 audit log
7. 回傳使用者結果

---

### 7.2 private_scannable

流程：

1. 接收明文上傳到 quarantine area
2. 掃描
3. clean 後 server-side encrypt 保存
4. 刪除暫存明文
5. 寫 audit log
6. 若 infected，拒絕保存並隔離

要求：

- 明文暫存目錄不可被 web 直接存取
- 掃描後必須刪除明文
- 錯誤時也必須清理明文
- 明文停留時間要最短
- audit log 記錄明文處理流程，但不能記錄內容

---

### 7.3 e2ee_vault

流程：

1. client 本地加密
2. 上傳密文
3. server 檢查：
   - 檔案大小
   - 副檔名，若 client 有提供但應視為不可信
   - ciphertext hash
   - 上傳頻率
   - 分享行為
4. scan_status = unknown_encrypted 或 skipped_e2ee
5. 下載前顯示警告

---

### 7.4 e2ee_vault_with_client_scan

流程：

1. client 先做本機安全檢查
2. client 產生 client_scan_report
3. client 加密檔案
4. server 保存密文與 client_scan_report
5. server 標記 client_scan_unverified=true

client_scan_report：

```json
{
  "scanner": "client-basic-scan",
  "version": "1.0",
  "checked_magic_bytes": true,
  "checked_extension": true,
  "checked_zip_bomb": true,
  "result": "clean",
  "created_at": "..."
}
```

注意：

- 不可把 client report 當成完全可信
- 只能作為 UX 提示與風險評分參考

---

## 8. 掃描器建議

第一版：

- ClamAV

可選：

- YARA rules
- file magic detector
- zip bomb detector
- macro detector
- image parser safety check

建立 ScanService：

```python
class ScanService:
    def scan_file(self, *, file_path, file_id, mode) -> ScanResult:
        pass

    def detect_file_type(self, *, file_path) -> FileTypeResult:
        pass

    def check_archive_safety(self, *, file_path) -> ArchiveSafetyResult:
        pass

    def quarantine_file(self, *, file_id, reason):
        pass
```

---

## 9. 權限與產品政策

### 9.1 使用者等級限制

newbie：

- 不可上傳可執行檔
- 不可公開分享壓縮檔
- 上傳大小低
- 上傳需掃描完成後才可發布

normal：

- 可上傳一般附件
- 壓縮檔限制較低

trusted：

- 可上傳較大附件
- 可使用部分 private_scannable
- 可建立較多分享

vip：

- 可使用 e2ee_vault 高配額
- 可更多分享
- 仍不可繞過高風險限制

restricted：

- 不可上傳
- 不可分享
- 可下載自己既有檔案，視處分規則決定

suspended：

- 不可上傳
- 不可分享
- 只能下載申訴所需資料，視政策決定

---

### 9.2 管理員限制

admin：

- 可看 public_attachment
- 可看掃描結果
- 可隔離檔案
- 不可解密 e2ee_vault
- 不可取得 user file_key

root：

- 可管理檔案狀態
- 可刪除或隔離密文
- 可看風險 metadata
- 不可解密 e2ee_vault
- 不可取得 user file_key

---

## 10. API 設計

### 10.1 初始化 E2EE

```http
POST /api/crypto/init
```

用途：

- 建立使用者 public key
- 保存 encrypted_private_key
- 保存 KDF salt
- 不上傳明文 master key

---

### 10.2 上傳檔案

```http
POST /api/files/upload
```

Form fields：

```json
{
  "privacy_mode": "public_attachment | private_scannable | e2ee_vault | e2ee_vault_with_client_scan",
  "encrypted_metadata": "...",
  "encrypted_file_key": "...",
  "client_scan_report": "...optional..."
}
```

---

### 10.3 查詢檔案狀態

```http
GET /api/files/{file_id}
```

Response 必須根據權限過濾：

- public_attachment 可回傳明文名稱
- e2ee_vault 只回傳 encrypted metadata
- admin/root 不可看到 e2ee 明文 metadata

---

### 10.4 下載檔案

```http
GET /api/files/{file_id}/download
```

e2ee_vault：

- 回傳密文
- 回傳 encrypted_file_key
- client 自行解密

public/private_scannable：

- 若 scan_status != clean，不允許下載
- infected/quarantined 不允許下載

---

### 10.5 分享 E2EE 檔案

```http
POST /api/files/{file_id}/share
```

Body：

```json
{
  "recipient_user_id": 123,
  "encrypted_file_key_for_recipient": "..."
}
```

伺服器不可自行解開 file_key。

---

### 10.6 撤銷分享

```http
POST /api/files/{file_id}/revoke-share
```

注意：

- 撤銷只阻止未來下載
- 已下載者可能已持有密文與 key
- UI 必須明確提示這點

---

## 11. UI 要求

### 11.1 上傳時顯示模式選擇

顯示四個選項：

1. 公開附件：可掃毒、可預覽，但站方可處理內容
2. 私密可掃描：站方短暫掃描，掃描後加密保存
3. 端到端加密保險庫：站方不可讀，但無法完整掃毒
4. 端到端加密 + 本機檢查：站方不可讀，上傳前由本機做基本安全檢查

---

### 11.2 E2EE 明確警告

使用者第一次啟用 e2ee_vault 必須看到：

```text
端到端加密代表伺服器、管理員、root 都無法讀取你的檔案內容。
但這也代表：
1. 忘記密碼或遺失 recovery key 可能無法救回檔案。
2. 伺服器無法完整掃毒。
3. 你需要自行判斷下載檔案是否可信。
```

---

### 11.3 下載高風險檔案警告

若 risk_level 為 high 或 unknown_encrypted：

```text
此檔案無法由伺服器完整掃描，或被判定為高風險。
請只在你信任來源時下載，並使用本機防毒軟體檢查。
```

---

## 12. Audit Log 要求

以下事件必須記錄：

- FILE_UPLOAD_STARTED
- FILE_UPLOAD_COMPLETED
- FILE_SCAN_STARTED
- FILE_SCAN_CLEAN
- FILE_SCAN_INFECTED
- FILE_SCAN_FAILED
- FILE_SCAN_SKIPPED_E2EE
- FILE_QUARANTINED
- FILE_DOWNLOAD
- FILE_SHARE_CREATED
- FILE_SHARE_REVOKED
- E2EE_INIT
- E2EE_RECOVERY_KEY_CREATED
- FILE_ADMIN_REVIEW_ATTEMPT
- FILE_DELETE

Audit log 不可記錄：

- 明文檔案內容
- 明文 file_key
- 明文 master_key
- E2EE 明文檔名
- E2EE 明文 metadata

---

## 13. 安全測試要求

### 13.1 E2EE 測試

- 上傳 e2ee_vault 檔案後，DB 不存在明文檔名
- DB 不存在明文 file_key
- root API 無法取得明文 metadata
- admin API 無法取得明文 metadata
- 下載後只有持有正確 key 的 client 可解密
- 錯誤 key 無法解密
- 分享時 recipient 可解密
- 未分享使用者不可解密

---

### 13.2 防毒測試

- public_attachment 必須掃描後才能下載
- infected 檔案不得發布
- private_scannable 掃描後刪除明文暫存
- scan failed 時不得進入 clean 狀態
- ClamAV 不可用時，系統必須 fail closed 或依設定進入 pending，不可當 clean

---

### 13.3 壓縮檔安全測試

- zip bomb 被阻擋
- path traversal zip 被阻擋
- 超過最大檔案數被阻擋
- 超過最大解壓大小被阻擋
- 多層壓縮超限被阻擋

---

### 13.4 權限測試

- newbie 不可上傳高風險可執行檔
- restricted 不可上傳
- suspended 不可上傳
- admin 不可解密 e2ee_vault
- root 不可解密 e2ee_vault
- 未授權使用者不可下載 private 檔案
- revoked share 不可再下載

---

### 13.5 Metadata 隱私測試

- e2ee_vault 的 filename 不可明文存 DB
- e2ee_vault 的 mime type 不可明文存 DB
- e2ee_vault 的 description 不可明文存 DB
- e2ee_vault 的 tag 不可明文存 DB
- audit log 不可出現明文 e2ee metadata

---

## 14. 實作順序

### Phase 1：資料模型與政策

- 建立 uploaded_files
- 建立 encrypted_file_keys
- 建立 file_scan_results
- 建立 file_access_logs
- 加入 privacy_mode / risk_level / scan_status
- 建立檔案類型政策設定

---

### Phase 2：普通上傳與掃描

- public_attachment upload
- quarantine area
- ClamAV 掃描
- clean 後發布
- infected 隔離
- scan_status 狀態機
- audit log

---

### Phase 3：private_scannable

- 明文暫存
- 掃描
- server-side encryption
- 明文清除
- 掃描失敗 fail closed
- 測試明文不殘留

---

### Phase 4：E2EE vault

- client-side encryption API contract
- encrypted metadata
- encrypted file key
- download ciphertext
- client decrypt flow
- root/admin 不可解密測試

---

### Phase 5：分享與撤銷

- recipient public key
- encrypted_file_key per recipient
- share API
- revoke API
- 下載權限檢查

---

### Phase 6：風險提示與 UI

- 上傳模式選擇
- e2ee 警告
- 高風險下載警告
- 掃描狀態顯示
- admin 檔案風險管理頁

---

### Phase 7：完整測試與文件

- unit tests
- integration tests
- security tests
- README_privacy_uploads.md
- README_e2ee_vault.md
- recovery_key_user_guide.md
- admin_file_safety_policy.md

---

## 15. 驗收標準

完成後必須達成：

1. public_attachment 可以掃毒、預覽、發布。
2. infected public_attachment 不可下載。
3. private_scannable 掃描後加密保存，明文暫存被清除。
4. e2ee_vault 上傳後 root/admin 無法取得明文內容。
5. e2ee_vault 的 filename / metadata 不以明文保存。
6. e2ee_vault 下載時只回傳密文與 encrypted_file_key。
7. 分享 E2EE 檔案不需要伺服器解密 file_key。
8. 撤銷分享後 recipient 不可再透過伺服器下載。
9. newbie/restricted/suspended 權限限制正確。
10. 高風險檔案有明確限制與警告。
11. 壓縮炸彈與 path traversal 壓縮檔被阻擋。
12. ClamAV 掃描失敗不會被當 clean。
13. audit log 完整，但不洩漏 E2EE 明文 metadata 或 key。
14. README 清楚說明防毒與隱私的取捨。

---

## 16. 禁止事項

請不要：

- 宣稱 E2EE 檔案已被伺服器完整掃毒
- 把 E2EE file_key 明文存進 DB
- 把 user master key 傳到伺服器
- 把 E2EE 檔名明文存進 DB
- 讓 root/admin 取得 E2EE 解密 key
- scan failed 時標記為 clean
- 讓未掃描 public_attachment 直接下載
- 讓壓縮檔不受限制地解壓
- 把 quarantine 目錄放在 web 可直接存取路徑
- 在 audit log 寫入敏感明文資料
- 混淆 private_scannable 和真正 E2EE

---

## 17. 最終交付物

請交付：

1. DB migrations
2. FileUploadService
3. ScanService
4. E2EEVaultService
5. FilePolicyService
6. API routes
7. Admin UI / User UI
8. 測試
9. README_privacy_uploads.md
10. README_e2ee_vault.md
11. admin_file_safety_policy.md
12. 實測報告
