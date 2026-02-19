# MailForwarder

A simple multi-account IMAP mail forwarder written in Python.

## 特徴

- 複数IMAPアカウント対応
- UID厳密比較による再送防止
- SMTP 465（SSL）/ 587（STARTTLS）両対応
- 添付ファイル転送対応
- ログローテーション（5MB × 5世代）
- Python標準ライブラリのみ使用

## Changelog

### [1.1.0] 2026-02-19
- Fixed
  - Prevent Gmail body mojibake by forcing 8bit encoding
  - Proper HTML priority multipart parsing
  - Multipart / mineo nested multipart fix

---

## 動作要件

- Python **3.8 以上**
- IMAP over SSL 対応サーバー
- SMTP（SSL または STARTTLS）対応サーバー

本ソフトウェアは Python 標準ライブラリのみを使用しています。  
追加のパッケージインストールは不要です。

---

## 動作確認環境

- IMAPサーバー：mineo
- SMTPサーバー：アサヒネット

※ 他のプロバイダでも、一般的な IMAP over SSL および SMTP（SSL / STARTTLS）環境であれば動作可能です。

---

## 実行方法

### 1. 設定ファイルを作成

cp config.sample.json config.json

config.json を編集し、IMAP・SMTP情報を設定してください。

### 2. スクリプトを実行

python3 mail_forward.py

初回実行時は既存メールを転送せず、最新UIDのみ保存します。  
2回目以降は新着メールのみ転送されます。

---

## cron による定期実行例

6時間ごとに実行する場合：

0 */6 * * * (cd /home/username/mail-forwarder && /usr/bin/python3 mail_forward.py) > /dev/null 2>&1

### 説明

- 0 */6 * * * → 6時間ごとに実行（0時・6時・12時・18時）
- /usr/bin/python3 → Pythonの絶対パス

※ 環境に応じてパスを変更してください。

---

## 注意事項

- メール送信元アドレスは config.json で指定した smtp.from_address になります
  - 迷惑メール判定を避けるため、smtp.from_address には使用するSMTPサーバーと同じドメインのメールアドレスを指定してください。
  - SPF や DMARC は送信元ドメインとSMTPサーバーの整合性を検証する仕組みで、
一致していないと迷惑メールと判定される場合があります。
- 元メールの差出人は本文および Reply-To ヘッダーに記載されます
- config.json は公開しないでください
- サーバー上では適切なファイルパーミッションを設定してください

chmod 600 config.json

---

## ライセンス

MIT License  
Copyright (c) 2026 ポカリ
