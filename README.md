# MailForwarder

A simple multi-account IMAP mail forwarder written in Python.

## 特徴

- 複数IMAPアカウント対応
- UID厳密比較による再送防止
- SMTP 465（SSL）/ 587（STARTTLS）両対応
- 添付ファイル転送対応
- ログローテーション（5MB × 5世代）
- Python標準ライブラリのみ使用

## 動作確認環境

- IMAPサーバー：mineo
- SMTPサーバー：アサヒネット

## 注意事項

- メール送信元アドレスは config.json で指定した from_address になります
- config.json は公開しないでください

## ライセンス

MIT License
