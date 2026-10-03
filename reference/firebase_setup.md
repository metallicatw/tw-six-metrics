# 啟用 Google 帳號登入＋雲端同步（Firebase）

設定一次，大約 10 分鐘。全部在網頁上點，不用裝任何東西。Firebase 的免費方案（Spark）對幾位使用者綽綽有餘，不需要綁信用卡。

## 1. 建立 Firebase 專案

1. 用 **eggeggyang2005@gmail.com** 開啟 <https://console.firebase.google.com> → **建立專案**。
2. 專案名稱隨意（例如 `tw-six-metrics`）。Google Analytics 選**不要啟用**，然後建立。

## 2. 開啟 Google 登入

1. 左側 **建構 → Authentication** → **開始使用**。
2. **Sign-in method** 分頁 → **Google** → 啟用。專案支援電子郵件選你自己的 Gmail → **儲存**。
3. **Settings** 分頁 → **授權網域** → **新增網域**，填 `metallicatw.github.io`。

## 3. 建立資料庫並貼上規則

1. 左側 **建構 → Firestore Database** → **建立資料庫**。
2. 位置選 **asia-east1（台灣）**，模式選**正式版（production mode）**，建立。
3. 上方 **規則** 分頁：把裡面原本的內容整段刪掉，貼上 repo 裡 `reference/firestore.rules` 的全部內容 → **發布**。

## 4. 取得網頁設定

1. 左上齒輪 **專案設定** → **一般** → 下方「你的應用程式」→ 點 **</>（網頁）** 圖示。
2. 暱稱隨意，**不要**勾 Firebase Hosting → 註冊。
3. 畫面會出現一段 `const firebaseConfig = { apiKey: "...", authDomain: "...", ... };`，整段複製下來。
   這段是公開的網頁設定（每個用 Firebase 的網站都會放在頁面上），不是密碼；真正保護資料的是第 3 步的規則。

## 5. 貼到 GitHub

1. GitHub → **tw-six-metrics** → **Settings** → **Secrets and variables** → **Actions**。
2. 切到 **Variables** 分頁（不是 Secrets）→ **New repository variable**。
3. Name 填 `FIREBASE_CONFIG`，Value 貼上第 4 步複製的整段 → **Add variable**。
4. 到 **Actions** → **pages** → **Run workflow**，網站重建後就會換成 Google 登入。

## 6. 第一次登入

1. 用 **eggeggyang2005@gmail.com** 開網站 → 「使用 Google 帳號登入」。
2. 第一次登入會自動建立授權名單：eggeggyang2005@gmail.com、nirvanatw@gmail.com、doris.yang1108@gmail.com。
   這台瀏覽器原本的觀察清單、持有成本、篩選條件，會自動搬到你的帳號底下。
3. 之後到其他電腦或手機用同一個帳號登入，就是同一份資料。

## 日常使用

- **新增或移除使用者**：管理員登入後，頁首右上角有「兩個人」的圖示 → 一行填一個 Gmail → 儲存，立即生效。
- **登出**：頁首右上角最右邊的圖示。登出時會清掉這台瀏覽器上的個人清單，下一位登入的人看不到上一位的資料。
- **會同步的**：觀察清單、各檔的持有成本、評等清單／觀察清單的篩選條件、選股功能四個分頁的條件。
- **不會同步的**：GitHub 權杖（只留在這台瀏覽器）、手機版／電腦版切換（每台裝置各自的偏好）。
- **兩台裝置同時修改**時，以最後存的那一份為準。

## 換回帳號密碼登入或關掉登入

- 刪掉 `FIREBASE_CONFIG` 這個 variable，網站就會改用 secret `SITE_LOGIN_USERS`（一行一組 `帳號:密碼`）。
- 兩個都沒有設定，就沒有登入畫面。
